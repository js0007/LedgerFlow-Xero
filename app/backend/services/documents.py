"""Subledger Documents Service: Quotes, Purchase Orders, Invoices, Bills, Credit Notes, Allocations & Payments."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from ..db import ApiError, atomic_tx, new_id, utc_now_iso
from ..money import cents_from_value, compute_line_amounts, decimal_str_from_cents
from .ledger import (
    assert_can_write,
    assert_period_unlocked,
    get_system_account,
    get_tax_rate_by_code,
    parse_iso_date,
    post_journal,
    reverse_journal,
    write_audit,
)

RECEIVABLE_TYPES = {"ACCREC", "ACCRECCREDIT"}
PAYABLE_TYPES = {"ACCPAY", "ACCPAYCREDIT"}
CREDIT_NOTE_TYPES = {"ACCRECCREDIT", "ACCPAYCREDIT"}


def _next_doc_number(conn: sqlite3.Connection, org_id: str, doc_kind: str) -> str:
    row = conn.execute("SELECT * FROM org_settings WHERE org_id = ?", (org_id,)).fetchone()
    if row is None:
        raise ApiError(500, "SETTINGS_MISSING", "Organisation settings missing.")
    mapping = {
        "ACCREC": ("invoice_prefix", "next_invoice_seq"),
        "ACCRECCREDIT": ("credit_note_prefix", "next_invoice_seq"),
        "ACCPAYCREDIT": ("credit_note_prefix", "next_credit_note_seq"),
        "QUOTE": ("quote_prefix", "next_quote_seq"),
        "PO": ("po_prefix", "next_po_seq"),
    }
    prefix_col, seq_col = mapping.get(doc_kind, ("invoice_prefix", "next_invoice_seq"))
    prefix = row[prefix_col]
    seq = int(row[seq_col])
    conn.execute(f"UPDATE org_settings SET {seq_col} = ? WHERE org_id = ?", (seq + 1, org_id))
    return f"{prefix}{seq:04d}"


def _prepare_commercial_lines(
    conn: sqlite3.Connection, org_id: str, tax_mode: str, raw_lines: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Compute authoritative server-side line totals using Xero line-by-line rounding."""
    if not raw_lines:
        raise ApiError(422, "NO_LINES", "Document requires at least one line item.")
    no_tax_tr = get_tax_rate_by_code(conn, org_id, "BASEXCLUDED")
    prepared = []
    sub_total = 0
    total_tax = 0
    total = 0

    for idx, line in enumerate(raw_lines, start=1):
        desc = (line.get("description") or "").strip()
        if not desc:
            raise ApiError(422, "DESCRIPTION_REQUIRED", f"Line {idx}: description is required.")
        acc_id = line.get("accountId")
        acc = conn.execute("SELECT * FROM accounts WHERE id = ? AND org_id = ?", (acc_id, org_id)).fetchone()
        if acc is None:
            raise ApiError(422, "INVALID_ACCOUNT", f"Line {idx}: account not found.")

        if tax_mode.upper() == "NO_TAX":
            tr = no_tax_tr
        else:
            tr_id = line.get("taxRateId") or acc["default_tax_rate_id"] or no_tax_tr["id"]
            tr = conn.execute("SELECT * FROM tax_rates WHERE id = ? AND org_id = ?", (tr_id, org_id)).fetchone()
            if tr is None:
                raise ApiError(422, "INVALID_TAX_RATE", f"Line {idx}: tax rate not found.")

        qty = str(line.get("quantity", "1"))
        unit_amt = str(line.get("unitAmount", "0.00"))
        disc = str(line.get("discountPct", "0"))
        net_c, tax_c, gross_c = compute_line_amounts(qty, unit_amt, disc, tr["rate_decimal"], tax_mode)

        sub_total += net_c
        total_tax += tax_c
        total += gross_c
        prepared.append(
            {
                "line_no": idx,
                "product_id": line.get("productId"),
                "description": desc,
                "quantity_decimal": qty,
                "unit_amount_decimal": unit_amt,
                "discount_pct_decimal": disc,
                "account_id": acc["id"],
                "account_code": acc["code"],
                "tax_rate_id": tr["id"],
                "tax_type_code": tr["code"],
                "net_cents": net_c,
                "tax_cents": tax_c,
                "gross_cents": gross_c,
                "tracking_1_option_id": line.get("tracking1OptionId"),
                "tracking_2_option_id": line.get("tracking2OptionId"),
            }
        )
    return prepared, sub_total, total_tax, total


def get_invoice(conn: sqlite3.Connection, org_id: str, invoice_id: str) -> dict[str, Any]:
    inv = conn.execute(
        """
        SELECT i.*, c.name AS contact_name, c.email AS contact_email, j.journal_number AS posted_journal_number
        FROM invoices i
        JOIN contacts c ON c.id = i.contact_id
        LEFT JOIN journals j ON j.id = i.posted_journal_id
        WHERE i.id = ? AND i.org_id = ?
        """,
        (invoice_id, org_id),
    ).fetchone()
    if inv is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Invoice / Bill / Credit Note not found.")

    lines = conn.execute(
        """
        SELECT l.*, a.code AS account_code, a.name AS account_name, tr.code AS tax_code, tr.name AS tax_name
        FROM invoice_lines l
        JOIN accounts a ON a.id = l.account_id
        JOIN tax_rates tr ON tr.id = l.tax_rate_id
        WHERE l.invoice_id = ? ORDER BY l.line_no
        """,
        (invoice_id,),
    ).fetchall()

    payments = conn.execute(
        """
        SELECT p.*, a.name AS bank_account_name, j.journal_number
        FROM payments p
        JOIN accounts a ON a.id = p.bank_account_id
        JOIN journals j ON j.id = p.journal_id
        WHERE p.invoice_id = ? AND p.status = 'AUTHORISED'
        ORDER BY p.payment_date, p.created_at
        """,
        (invoice_id,),
    ).fetchall()

    allocs = conn.execute(
        """
        SELECT ca.*, src.invoice_number AS credit_note_number, tgt.invoice_number AS target_invoice_number
        FROM credit_note_allocations ca
        JOIN invoices src ON src.id = ca.credit_note_id
        JOIN invoices tgt ON tgt.id = ca.target_invoice_id
        WHERE (ca.credit_note_id = ? OR ca.target_invoice_id = ?) AND ca.status = 'ACTIVE'
        ORDER BY ca.allocation_date
        """,
        (invoice_id, invoice_id),
    ).fetchall()

    amount_due_cents = int(inv["total_cents"]) - int(inv["amount_paid_cents"]) - int(inv["amount_credited_cents"])
    return {
        "id": inv["id"],
        "orgId": inv["org_id"],
        "invoiceType": inv["invoice_type"],
        "contactId": inv["contact_id"],
        "contactName": inv["contact_name"],
        "contactEmail": inv["contact_email"],
        "invoiceNumber": inv["invoice_number"],
        "reference": inv["reference"],
        "issueDate": inv["issue_date"],
        "dueDate": inv["due_date"],
        "currencyCode": inv["currency_code"],
        "taxMode": inv["tax_mode"],
        "status": inv["status"],
        "subTotal": decimal_str_from_cents(inv["sub_total_cents"]),
        "totalTax": decimal_str_from_cents(inv["total_tax_cents"]),
        "total": decimal_str_from_cents(inv["total_cents"]),
        "amountPaid": decimal_str_from_cents(inv["amount_paid_cents"]),
        "amountCredited": decimal_str_from_cents(inv["amount_credited_cents"]),
        "amountDue": decimal_str_from_cents(amount_due_cents),
        "postedJournalId": inv["posted_journal_id"],
        "postedJournalNumber": inv["posted_journal_number"],
        "reversalJournalId": inv["reversal_journal_id"],
        "version": inv["version"],
        "createdAt": inv["created_at"],
        "updatedAt": inv["updated_at"],
        "lines": [
            {
                "id": l["id"],
                "lineNo": l["line_no"],
                "productId": l["product_id"],
                "description": l["description"],
                "quantity": l["quantity_decimal"],
                "unitAmount": l["unit_amount_decimal"],
                "discountPct": l["discount_pct_decimal"],
                "accountId": l["account_id"],
                "accountCode": l["account_code"],
                "accountName": l["account_name"],
                "taxRateId": l["tax_rate_id"],
                "taxCode": l["tax_code"],
                "taxName": l["tax_name"],
                "netAmount": decimal_str_from_cents(l["net_cents"]),
                "taxAmount": decimal_str_from_cents(l["tax_cents"]),
                "grossAmount": decimal_str_from_cents(l["gross_cents"]),
                "tracking1OptionId": l["tracking_1_option_id"],
                "tracking2OptionId": l["tracking_2_option_id"],
            }
            for l in lines
        ],
        "payments": [
            {
                "id": p["id"],
                "bankAccountId": p["bank_account_id"],
                "bankAccountName": p["bank_account_name"],
                "paymentDate": p["payment_date"],
                "amount": decimal_str_from_cents(p["amount_cents"]),
                "reference": p["reference"],
                "isReconciled": bool(p["is_reconciled"]),
                "journalNumber": p["journal_number"],
            }
            for p in payments
        ],
        "allocations": [
            {
                "id": a["id"],
                "creditNoteId": a["credit_note_id"],
                "creditNoteNumber": a["credit_note_number"],
                "targetInvoiceId": a["target_invoice_id"],
                "targetInvoiceNumber": a["target_invoice_number"],
                "allocationDate": a["allocation_date"],
                "amount": decimal_str_from_cents(a["amount_cents"]),
            }
            for a in allocs
        ],
    }


def list_invoices(
    conn: sqlite3.Connection,
    org_id: str,
    invoice_type: str | None = None,
    status: str | None = None,
    contact_id: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT id FROM invoices WHERE org_id = ?"
    params: list[Any] = [org_id]
    if invoice_type:
        types = [t.strip().upper() for t in invoice_type.split(",") if t.strip()]
        placeholders = ",".join("?" for _ in types)
        sql += f" AND invoice_type IN ({placeholders})"
        params.extend(types)
    if status and status.upper() != "ALL":
        sql += " AND status = ?"
        params.append(status.upper())
    if contact_id:
        sql += " AND contact_id = ?"
        params.append(contact_id)
    sql += " ORDER BY issue_date DESC, created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return [get_invoice(conn, org_id, r["id"]) for r in rows]


def create_invoice(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    payload: dict[str, Any],
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    assert_can_write(actor_role)
    inv_type = (payload.get("invoiceType") or "ACCREC").upper()
    if inv_type not in (RECEIVABLE_TYPES | PAYABLE_TYPES):
        raise ApiError(400, "INVALID_INVOICE_TYPE", f"Invalid invoiceType '{inv_type}'")

    contact_id = payload.get("contactId")
    contact = conn.execute("SELECT * FROM contacts WHERE id = ? AND org_id = ?", (contact_id, org_id)).fetchone()
    if contact is None:
        raise ApiError(422, "CONTACT_NOT_FOUND", "Contact does not exist in organisation.")

    issue_date = payload.get("issueDate") or date.today().isoformat()
    due_date = payload.get("dueDate") or issue_date
    parse_iso_date(issue_date)
    parse_iso_date(due_date)

    default_tax_mode = "EXCLUSIVE" if inv_type in RECEIVABLE_TYPES else "INCLUSIVE"
    tax_mode = (payload.get("taxMode") or default_tax_mode).upper()
    prepared, sub_total, total_tax, total = _prepare_commercial_lines(conn, org_id, tax_mode, payload.get("lines", []))

    now = utc_now_iso()
    inv_id = new_id()
    initial_status = "SUBMITTED" if payload.get("submitForApproval") else "DRAFT"

    with atomic_tx(conn):
        inv_number = (payload.get("invoiceNumber") or "").strip() or (
            _next_doc_number(conn, org_id, inv_type) if inv_type != "ACCPAY" else f"BILL-{new_id()[:6].upper()}"
        )
        conn.execute(
            """
            INSERT INTO invoices (
                id, org_id, invoice_type, contact_id, invoice_number, reference,
                issue_date, due_date, currency_code, tax_mode, status,
                sub_total_cents, total_tax_cents, total_cents, amount_paid_cents, amount_credited_cents,
                source_quote_id, source_po_id, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'AUD', ?, ?, ?, ?, ?, 0, 0, ?, ?, 1, ?, ?)
            """,
            (
                inv_id,
                org_id,
                inv_type,
                contact_id,
                inv_number,
                payload.get("reference"),
                issue_date,
                due_date,
                tax_mode,
                initial_status,
                sub_total,
                total_tax,
                total,
                payload.get("sourceQuoteId"),
                payload.get("sourcePoId"),
                now,
                now,
            ),
        )
        _insert_invoice_lines(conn, inv_id, prepared)
        # Update contact customer/supplier flags organically just like Xero
        if inv_type in RECEIVABLE_TYPES:
            conn.execute("UPDATE contacts SET is_customer = 1 WHERE id = ?", (contact_id,))
        else:
            conn.execute("UPDATE contacts SET is_supplier = 1 WHERE id = ?", (contact_id,))

        write_audit(conn, org_id, actor_user_id, actor_name, inv_type, inv_id, "CREATED", f"{inv_type} {inv_number} created ({initial_status}).")

    if payload.get("approveImmediately"):
        return approve_invoice(conn, org_id=org_id, invoice_id=inv_id, actor_user_id=actor_user_id, actor_name=actor_name, actor_role=actor_role)
    return get_invoice(conn, org_id, inv_id)


def _insert_invoice_lines(conn: sqlite3.Connection, invoice_id: str, prepared: list[dict[str, Any]]) -> None:
    for p in prepared:
        conn.execute(
            """
            INSERT INTO invoice_lines (
                id, invoice_id, line_no, product_id, description,
                quantity_decimal, unit_amount_decimal, discount_pct_decimal,
                account_id, tax_rate_id, net_cents, tax_cents, gross_cents,
                tracking_1_option_id, tracking_2_option_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                invoice_id,
                p["line_no"],
                p["product_id"],
                p["description"],
                p["quantity_decimal"],
                p["unit_amount_decimal"],
                p["discount_pct_decimal"],
                p["account_id"],
                p["tax_rate_id"],
                p["net_cents"],
                p["tax_cents"],
                p["gross_cents"],
                p["tracking_1_option_id"],
                p["tracking_2_option_id"],
            ),
        )


def _build_invoice_gl_lines(conn: sqlite3.Connection, org_id: str, inv: sqlite3.Row, lines: list[sqlite3.Row]) -> list[dict[str, Any]]:
    inv_type = inv["invoice_type"]
    ar_acc = get_system_account(conn, org_id, "DEBTORS")
    ap_acc = get_system_account(conn, org_id, "CREDITORS")
    gst_acc = get_system_account(conn, org_id, "GST")

    gl_lines: list[dict[str, Any]] = []
    if inv_type == "ACCREC":
        gl_lines.append({
            "account_id": ar_acc["id"],
            "contact_id": inv["contact_id"],
            "description": f"Invoice {inv['invoice_number']}",
            "debit_cents": int(inv["total_cents"]),
            "credit_cents": 0,
        })
        for l in lines:
            gl_lines.append({
                "account_id": l["account_id"],
                "contact_id": inv["contact_id"],
                "description": l["description"],
                "debit_cents": 0,
                "credit_cents": int(l["net_cents"]),
                "tax_rate_id": l["tax_rate_id"],
                "tax_type_code": l["tax_type_code"],
                "gross_cents": int(l["gross_cents"]),
                "net_cents": int(l["net_cents"]),
                "tax_cents": int(l["tax_cents"]),
                "tracking_1_option_id": l["tracking_1_option_id"],
                "tracking_2_option_id": l["tracking_2_option_id"],
            })
        if int(inv["total_tax_cents"]) > 0:
            gl_lines.append({
                "account_id": gst_acc["id"],
                "description": f"GST on {inv['invoice_number']}",
                "debit_cents": 0,
                "credit_cents": int(inv["total_tax_cents"]),
            })
    elif inv_type == "ACCPAY":
        for l in lines:
            gl_lines.append({
                "account_id": l["account_id"],
                "contact_id": inv["contact_id"],
                "description": l["description"],
                "debit_cents": int(l["net_cents"]),
                "credit_cents": 0,
                "tax_rate_id": l["tax_rate_id"],
                "tax_type_code": l["tax_type_code"],
                "gross_cents": int(l["gross_cents"]),
                "net_cents": int(l["net_cents"]),
                "tax_cents": int(l["tax_cents"]),
                "tracking_1_option_id": l["tracking_1_option_id"],
                "tracking_2_option_id": l["tracking_2_option_id"],
            })
        if int(inv["total_tax_cents"]) > 0:
            gl_lines.append({
                "account_id": gst_acc["id"],
                "description": f"GST on {inv['invoice_number']}",
                "debit_cents": int(inv["total_tax_cents"]),
                "credit_cents": 0,
            })
        gl_lines.append({
            "account_id": ap_acc["id"],
            "contact_id": inv["contact_id"],
            "description": f"Bill {inv['invoice_number']}",
            "debit_cents": 0,
            "credit_cents": int(inv["total_cents"]),
        })
    elif inv_type == "ACCRECCREDIT":
        for l in lines:
            gl_lines.append({
                "account_id": l["account_id"],
                "contact_id": inv["contact_id"],
                "description": l["description"],
                "debit_cents": int(l["net_cents"]),
                "credit_cents": 0,
                "tax_rate_id": l["tax_rate_id"],
                "tax_type_code": l["tax_type_code"],
                "gross_cents": -int(l["gross_cents"]),
                "net_cents": -int(l["net_cents"]),
                "tax_cents": -int(l["tax_cents"]),
                "tracking_1_option_id": l["tracking_1_option_id"],
                "tracking_2_option_id": l["tracking_2_option_id"],
            })
        if int(inv["total_tax_cents"]) > 0:
            gl_lines.append({
                "account_id": gst_acc["id"],
                "description": f"GST Credit {inv['invoice_number']}",
                "debit_cents": int(inv["total_tax_cents"]),
                "credit_cents": 0,
            })
        gl_lines.append({
            "account_id": ar_acc["id"],
            "contact_id": inv["contact_id"],
            "description": f"Credit Note {inv['invoice_number']}",
            "debit_cents": 0,
            "credit_cents": int(inv["total_cents"]),
        })
    elif inv_type == "ACCPAYCREDIT":
        gl_lines.append({
            "account_id": ap_acc["id"],
            "contact_id": inv["contact_id"],
            "description": f"Supplier Credit Note {inv['invoice_number']}",
            "debit_cents": int(inv["total_cents"]),
            "credit_cents": 0,
        })
        for l in lines:
            gl_lines.append({
                "account_id": l["account_id"],
                "contact_id": inv["contact_id"],
                "description": l["description"],
                "debit_cents": 0,
                "credit_cents": int(l["net_cents"]),
                "tax_rate_id": l["tax_rate_id"],
                "tax_type_code": l["tax_type_code"],
                "gross_cents": -int(l["gross_cents"]),
                "net_cents": -int(l["net_cents"]),
                "tax_cents": -int(l["tax_cents"]),
                "tracking_1_option_id": l["tracking_1_option_id"],
                "tracking_2_option_id": l["tracking_2_option_id"],
            })
        if int(inv["total_tax_cents"]) > 0:
            gl_lines.append({
                "account_id": gst_acc["id"],
                "description": f"GST Credit {inv['invoice_number']}",
                "debit_cents": 0,
                "credit_cents": int(inv["total_tax_cents"]),
            })
    return gl_lines


def update_invoice(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    invoice_id: str,
    payload: dict[str, Any],
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Update a DRAFT/SUBMITTED document directly, or edit an unpaid/unallocated AUTHORISED document via reversal + repost."""
    assert_can_write(actor_role)
    with atomic_tx(conn):
        inv = conn.execute("SELECT * FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id)).fetchone()
        if inv is None:
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document not found.")
        expected_version = payload.get("version")
        if expected_version is not None and int(inv["version"]) != int(expected_version):
            raise ApiError(409, "VERSION_CONFLICT", "Document was modified by another request. Refresh and retry.")
        if inv["status"] not in ("DRAFT", "SUBMITTED", "AUTHORISED"):
            raise ApiError(422, "NOT_EDITABLE", f"Cannot edit a {inv['status']} document.")
        if inv["status"] == "AUTHORISED" and (int(inv["amount_paid_cents"]) > 0 or int(inv["amount_credited_cents"]) > 0):
            raise ApiError(422, "HAS_PAYMENTS_OR_ALLOCATIONS", "Cannot edit an authorised document with payments or credit allocations. Remove them first.")

        contact_id = payload.get("contactId") or inv["contact_id"]
        issue_date = payload.get("issueDate") or inv["issue_date"]
        due_date = payload.get("dueDate") or inv["due_date"]
        parse_iso_date(issue_date)
        parse_iso_date(due_date)
        tax_mode = (payload.get("taxMode") or inv["tax_mode"]).upper()
        inv_number = (payload.get("invoiceNumber") or inv["invoice_number"]).strip()
        reference = payload.get("reference", inv["reference"])
        prepared, sub_total, total_tax, total = _prepare_commercial_lines(conn, org_id, tax_mode, payload.get("lines", []))

        if inv["status"] == "AUTHORISED":
            assert_period_unlocked(conn, org_id, inv["issue_date"], actor_role)
            assert_period_unlocked(conn, org_id, issue_date, actor_role)
            if total <= 0:
                raise ApiError(422, "ZERO_TOTAL", "Authorised document total must be greater than zero.")

        rev_jid = inv["reversal_journal_id"]
        new_posted_jid = inv["posted_journal_id"]
        if inv["status"] == "AUTHORISED" and inv["posted_journal_id"]:
            rev_jid, _ = reverse_journal(
                conn,
                org_id=org_id,
                original_journal_id=inv["posted_journal_id"],
                reversal_date=inv["issue_date"],
                source_type=f"{inv['invoice_type']}_REVERSAL",
                source_id=invoice_id,
                narration=f"Edit reversal {inv['invoice_number']}",
                actor_user_id=actor_user_id,
            )

        conn.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))
        _insert_invoice_lines(conn, invoice_id, prepared)
        now = utc_now_iso()
        conn.execute(
            """
            UPDATE invoices SET contact_id=?, invoice_number=?, reference=?, issue_date=?, due_date=?, tax_mode=?,
            sub_total_cents=?, total_tax_cents=?, total_cents=?, version=version+1, updated_at=? WHERE id=?
            """,
            (contact_id, inv_number, reference, issue_date, due_date, tax_mode, sub_total, total_tax, total, now, invoice_id),
        )

        if inv["status"] == "AUTHORISED":
            updated_inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            updated_lines = conn.execute(
                "SELECT l.*, tr.code AS tax_type_code FROM invoice_lines l JOIN tax_rates tr ON tr.id = l.tax_rate_id WHERE l.invoice_id = ? ORDER BY l.line_no",
                (invoice_id,),
            ).fetchall()
            gl_lines = _build_invoice_gl_lines(conn, org_id, updated_inv, updated_lines)
            new_posted_jid, jnum = post_journal(
                conn,
                org_id=org_id,
                journal_date=issue_date,
                source_type=inv["invoice_type"],
                source_id=invoice_id,
                reference=inv_number,
                narration=f"Edited {inv['invoice_type']} {inv_number}",
                lines=gl_lines,
                actor_user_id=actor_user_id,
            )
            conn.execute(
                "UPDATE invoices SET posted_journal_id=?, reversal_journal_id=? WHERE id=?",
                (new_posted_jid, rev_jid, invoice_id),
            )
            write_audit(conn, org_id, actor_user_id, actor_name, inv["invoice_type"], invoice_id, "EDITED_AUTHORISED", f"{inv_number} edited via reversal + repost (Journal #{jnum}).")
        else:
            write_audit(conn, org_id, actor_user_id, actor_name, inv["invoice_type"], invoice_id, "UPDATED", f"{inv_number} edited.")
    return get_invoice(conn, org_id, invoice_id)


update_draft_invoice = update_invoice


def delete_invoice(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    invoice_id: str,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Delete an unposted DRAFT/SUBMITTED Invoice, Bill, or Credit Note."""
    assert_can_write(actor_role)
    with atomic_tx(conn):
        inv = conn.execute("SELECT * FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id)).fetchone()
        if inv is None:
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document not found.")
        if inv["status"] not in ("DRAFT", "SUBMITTED") or inv["posted_journal_id"] is not None:
            raise ApiError(422, "CANNOT_DELETE_POSTED", "Only DRAFT or SUBMITTED documents can be deleted; void posted documents instead.")
        if int(inv["amount_paid_cents"]) > 0 or int(inv["amount_credited_cents"]) > 0:
            raise ApiError(422, "HAS_PAYMENTS_OR_ALLOCATIONS", "Cannot delete document with payments or allocations.")
        conn.execute("UPDATE quotes SET converted_invoice_id=NULL, status='ACCEPTED' WHERE org_id=? AND converted_invoice_id=?", (org_id, invoice_id))
        conn.execute("UPDATE purchase_orders SET converted_bill_id=NULL, status='APPROVED' WHERE org_id=? AND converted_bill_id=?", (org_id, invoice_id))
        conn.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))
        conn.execute("DELETE FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id))
        write_audit(conn, org_id, actor_user_id, actor_name, inv["invoice_type"], invoice_id, "DELETED", f"Deleted draft {inv['invoice_number']}.")
    return {"deleted": True, "id": invoice_id}


def approve_invoice(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    invoice_id: str,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    assert_can_write(actor_role)
    with atomic_tx(conn):
        inv = conn.execute("SELECT * FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id)).fetchone()
        if inv is None:
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document not found.")
        if inv["status"] not in ("DRAFT", "SUBMITTED"):
            raise ApiError(422, "ALREADY_APPROVED", f"Document is already {inv['status']}.")

        assert_period_unlocked(conn, org_id, inv["issue_date"], actor_role)
        if int(inv["total_cents"]) <= 0:
            raise ApiError(422, "ZERO_TOTAL", "Approved document total must be greater than zero.")

        lines = conn.execute(
            """
            SELECT l.*, tr.code AS tax_type_code
            FROM invoice_lines l JOIN tax_rates tr ON tr.id = l.tax_rate_id
            WHERE l.invoice_id = ? ORDER BY l.line_no
            """,
            (invoice_id,),
        ).fetchall()

        inv_type = inv["invoice_type"]
        gl_lines = _build_invoice_gl_lines(conn, org_id, inv, lines)
        jid, jnum = post_journal(
            conn,
            org_id=org_id,
            journal_date=inv["issue_date"],
            source_type=inv_type,
            source_id=invoice_id,
            reference=inv["invoice_number"],
            narration=f"{inv_type} {inv['invoice_number']}",
            lines=gl_lines,
            actor_user_id=actor_user_id,
        )
        conn.execute(
            "UPDATE invoices SET status='AUTHORISED', posted_journal_id=?, version=version+1, updated_at=? WHERE id=?",
            (jid, utc_now_iso(), invoice_id),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, inv_type, invoice_id, "APPROVED", f"{inv['invoice_number']} approved (Journal #{jnum}).")
    return get_invoice(conn, org_id, invoice_id)


def void_invoice(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    invoice_id: str,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    assert_can_write(actor_role)
    with atomic_tx(conn):
        inv = conn.execute("SELECT * FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id)).fetchone()
        if inv is None:
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document not found.")
        if inv["status"] == "VOIDED":
            return get_invoice(conn, org_id, invoice_id)
        if int(inv["amount_paid_cents"]) > 0 or int(inv["amount_credited_cents"]) > 0:
            raise ApiError(422, "HAS_PAYMENTS_OR_ALLOCATIONS", "Cannot void document with active payments or credit allocations. Remove them first.")

        rev_jid = None
        if inv["status"] == "AUTHORISED" and inv["posted_journal_id"]:
            assert_period_unlocked(conn, org_id, inv["issue_date"], actor_role)
            rev_jid, _ = reverse_journal(
                conn,
                org_id=org_id,
                original_journal_id=inv["posted_journal_id"],
                reversal_date=inv["issue_date"],
                source_type=f"{inv['invoice_type']}_REVERSAL",
                source_id=invoice_id,
                narration=f"Void {inv['invoice_number']}",
                actor_user_id=actor_user_id,
            )
        conn.execute(
            "UPDATE invoices SET status='VOIDED', reversal_journal_id=?, version=version+1, updated_at=? WHERE id=?",
            (rev_jid, utc_now_iso(), invoice_id),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, inv["invoice_type"], invoice_id, "VOIDED", f"{inv['invoice_number']} voided.")
    return get_invoice(conn, org_id, invoice_id)


def allocate_credit_note(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    credit_note_id: str,
    allocations: list[dict[str, Any]],
    allocation_date: str | None,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Allocate an AUTHORISED Credit Note against matching Invoices or Bills (triggers Cash BAS allocation date!)."""
    assert_can_write(actor_role)
    alloc_date = allocation_date or date.today().isoformat()
    parse_iso_date(alloc_date)
    if not allocations:
        raise ApiError(422, "INVALID_ALLOCATION_AMOUNT", "Select at least one invoice/bill to allocate.")

    with atomic_tx(conn):
        cn = conn.execute("SELECT * FROM invoices WHERE id = ? AND org_id = ?", (credit_note_id, org_id)).fetchone()
        if cn is None or cn["invoice_type"] not in CREDIT_NOTE_TYPES:
            raise ApiError(404, "CREDIT_NOTE_NOT_FOUND", "Credit Note not found.")
        if cn["status"] != "AUTHORISED":
            raise ApiError(422, "INVALID_CN_STATE", "Only AUTHORISED Credit Notes with remaining credit can be allocated.")

        assert_period_unlocked(conn, org_id, alloc_date, actor_role)

        cn_remaining = int(cn["total_cents"]) - int(cn["amount_credited_cents"]) - int(cn["amount_paid_cents"])
        requested_total = sum(cents_from_value(a.get("amount", 0)) for a in allocations)
        if requested_total <= 0 or requested_total > cn_remaining:
            raise ApiError(422, "INVALID_ALLOCATION_AMOUNT", f"Allocation sum ({requested_total}) must be > 0 and <= remaining credit ({cn_remaining}).")

        expected_target_type = "ACCREC" if cn["invoice_type"] == "ACCRECCREDIT" else "ACCPAY"

        for a in allocations:
            amt_c = cents_from_value(a.get("amount", 0))
            if amt_c <= 0:
                continue
            target_id = a.get("targetInvoiceId")
            if not target_id:
                raise ApiError(422, "TARGET_REQUIRED", "targetInvoiceId is required for each allocation.")
            tgt = conn.execute("SELECT * FROM invoices WHERE id = ? AND org_id = ?", (target_id, org_id)).fetchone()
            if tgt is None or tgt["invoice_type"] != expected_target_type or tgt["contact_id"] != cn["contact_id"]:
                raise ApiError(422, "INVALID_ALLOCATION_TARGET", "Target document must match contact and invoice/bill direction.")
            if tgt["status"] != "AUTHORISED":
                raise ApiError(422, "TARGET_NOT_OPEN", f"Target document {tgt['invoice_number']} is not open for allocation.")

            tgt_due = int(tgt["total_cents"]) - int(tgt["amount_paid_cents"]) - int(tgt["amount_credited_cents"])
            if amt_c > tgt_due:
                raise ApiError(422, "OVER_ALLOCATION", f"Amount exceeds balance due on {tgt['invoice_number']}.")

            conn.execute(
                """
                INSERT INTO credit_note_allocations (id, org_id, credit_note_id, target_invoice_id, allocation_date, amount_cents, status, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
                """,
                (new_id(), org_id, credit_note_id, tgt["id"], alloc_date, amt_c, actor_user_id, utc_now_iso()),
            )
            new_tgt_credited = int(tgt["amount_credited_cents"]) + amt_c
            tgt_new_status = "PAID" if (int(tgt["total_cents"]) - int(tgt["amount_paid_cents"]) - new_tgt_credited) == 0 else "AUTHORISED"
            conn.execute(
                "UPDATE invoices SET amount_credited_cents=?, status=?, version=version+1, updated_at=? WHERE id=?",
                (new_tgt_credited, tgt_new_status, utc_now_iso(), tgt["id"]),
            )

        new_cn_credited = int(cn["amount_credited_cents"]) + requested_total
        cn_new_status = "PAID" if (int(cn["total_cents"]) - int(cn["amount_paid_cents"]) - new_cn_credited) == 0 else "AUTHORISED"
        conn.execute(
            "UPDATE invoices SET amount_credited_cents=?, status=?, version=version+1, updated_at=? WHERE id=?",
            (new_cn_credited, cn_new_status, utc_now_iso(), credit_note_id),
        )
        write_audit(
            conn,
            org_id,
            actor_user_id,
            actor_name,
            "CREDIT_NOTE_ALLOCATION",
            credit_note_id,
            "ALLOCATED",
            f"Allocated {decimal_str_from_cents(requested_total)} from {cn['invoice_number']} on {alloc_date}.",
        )
    return get_invoice(conn, org_id, credit_note_id)


def deallocate_credit_note(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    allocation_id: str,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Unallocate an ACTIVE credit note allocation and reopen remaining credits/balances."""
    assert_can_write(actor_role)
    with atomic_tx(conn):
        alloc = conn.execute(
            "SELECT * FROM credit_note_allocations WHERE id = ? AND org_id = ?",
            (allocation_id, org_id),
        ).fetchone()
        if alloc is None or alloc["status"] != "ACTIVE":
            raise ApiError(404, "ALLOCATION_NOT_FOUND", "Active credit note allocation not found.")
        assert_period_unlocked(conn, org_id, alloc["allocation_date"], actor_role)

        cn = conn.execute("SELECT * FROM invoices WHERE id = ?", (alloc["credit_note_id"],)).fetchone()
        tgt = conn.execute("SELECT * FROM invoices WHERE id = ?", (alloc["target_invoice_id"],)).fetchone()
        amt_c = int(alloc["amount_cents"])
        now = utc_now_iso()

        conn.execute("UPDATE credit_note_allocations SET status = 'REVERSED' WHERE id = ?", (allocation_id,))
        for doc in (cn, tgt):
            new_cred = max(0, int(doc["amount_credited_cents"]) - amt_c)
            rem = int(doc["total_cents"]) - int(doc["amount_paid_cents"]) - new_cred
            new_status = "AUTHORISED" if rem > 0 else "PAID"
            conn.execute(
                "UPDATE invoices SET amount_credited_cents=?, status=?, version=version+1, updated_at=? WHERE id=?",
                (new_cred, new_status, now, doc["id"]),
            )
        write_audit(
            conn,
            org_id,
            actor_user_id,
            actor_name,
            "CREDIT_NOTE_ALLOCATION",
            allocation_id,
            "UNALLOCATED",
            f"Unallocated {decimal_str_from_cents(amt_c)} from {cn['invoice_number']} / {tgt['invoice_number']}.",
        )
    return get_invoice(conn, org_id, cn["id"])


def record_payment(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    invoice_id: str,
    bank_account_id: str,
    payment_date: str,
    amount_cents: int,
    reference: str | None,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
    is_reconciled: bool = False,
) -> dict[str, Any]:
    """Record full/partial payment on Invoice/Bill OR cash refund on Credit Note and post immutable GL journal."""
    assert_can_write(actor_role)
    assert_period_unlocked(conn, org_id, payment_date, actor_role)
    pay_id = new_id()
    now = utc_now_iso()

    with atomic_tx(conn):
        inv = conn.execute("SELECT * FROM invoices WHERE id = ? AND org_id = ?", (invoice_id, org_id)).fetchone()
        if inv is None or inv["invoice_type"] not in ("ACCREC", "ACCPAY", "ACCRECCREDIT", "ACCPAYCREDIT"):
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "Payable/Receivable document not found.")
        if inv["status"] != "AUTHORISED":
            raise ApiError(422, "DOCUMENT_NOT_AUTHORISED", f"Cannot record payment or refund on {inv['status']} document.")

        due_cents = int(inv["total_cents"]) - int(inv["amount_paid_cents"]) - int(inv["amount_credited_cents"])
        if amount_cents <= 0 or amount_cents > due_cents:
            raise ApiError(422, "INVALID_PAYMENT_AMOUNT", f"Amount must be > 0 and <= remaining balance ({decimal_str_from_cents(due_cents)}).")

        bank = conn.execute("SELECT * FROM accounts WHERE id = ? AND org_id = ?", (bank_account_id, org_id)).fetchone()
        if bank is None or (bank["account_type"] != "BANK" and int(bank["enable_payments_to_account"]) != 1):
            raise ApiError(422, "INVALID_PAYMENT_ACCOUNT", "Payments/refunds must use a BANK account or an account with 'Enable payments to this account'.")

        ar_acc = get_system_account(conn, org_id, "DEBTORS")
        ap_acc = get_system_account(conn, org_id, "CREDITORS")

        inv_type = inv["invoice_type"]
        if inv_type == "ACCREC":
            source_type = "ACCREC_PAYMENT"
            gl_lines = [
                {"account_id": bank["id"], "contact_id": inv["contact_id"], "description": f"Payment: {inv['invoice_number']}", "debit_cents": amount_cents, "credit_cents": 0},
                {"account_id": ar_acc["id"], "contact_id": inv["contact_id"], "description": f"Payment: {inv['invoice_number']}", "debit_cents": 0, "credit_cents": amount_cents},
            ]
        elif inv_type == "ACCRECCREDIT":
            # Cash refund back to customer: Dr AR, Cr Bank
            source_type = "ACCREC_PAYMENT"
            gl_lines = [
                {"account_id": ar_acc["id"], "contact_id": inv["contact_id"], "description": f"Cash Refund: {inv['invoice_number']}", "debit_cents": amount_cents, "credit_cents": 0},
                {"account_id": bank["id"], "contact_id": inv["contact_id"], "description": f"Cash Refund: {inv['invoice_number']}", "debit_cents": 0, "credit_cents": amount_cents},
            ]
        elif inv_type == "ACCPAY":
            source_type = "ACCPAY_PAYMENT"
            gl_lines = [
                {"account_id": ap_acc["id"], "contact_id": inv["contact_id"], "description": f"Payment: {inv['invoice_number']}", "debit_cents": amount_cents, "credit_cents": 0},
                {"account_id": bank["id"], "contact_id": inv["contact_id"], "description": f"Payment: {inv['invoice_number']}", "debit_cents": 0, "credit_cents": amount_cents},
            ]
        else:  # ACCPAYCREDIT: Cash refund received from supplier -> Dr Bank, Cr AP
            source_type = "ACCPAY_PAYMENT"
            gl_lines = [
                {"account_id": bank["id"], "contact_id": inv["contact_id"], "description": f"Supplier Refund: {inv['invoice_number']}", "debit_cents": amount_cents, "credit_cents": 0},
                {"account_id": ap_acc["id"], "contact_id": inv["contact_id"], "description": f"Supplier Refund: {inv['invoice_number']}", "debit_cents": 0, "credit_cents": amount_cents},
            ]

        action_label = "Cash Refund" if inv_type in CREDIT_NOTE_TYPES else "Payment"
        jid, jnum = post_journal(
            conn,
            org_id=org_id,
            journal_date=payment_date,
            source_type=source_type,
            source_id=pay_id,
            reference=reference or inv["invoice_number"],
            narration=f"{action_label} for {inv['invoice_number']}",
            lines=gl_lines,
            actor_user_id=actor_user_id,
        )
        conn.execute(
            """
            INSERT INTO payments (id, org_id, invoice_id, bank_account_id, payment_date, amount_cents, reference, is_reconciled, status, journal_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'AUTHORISED', ?, ?)
            """,
            (pay_id, org_id, invoice_id, bank_account_id, payment_date, amount_cents, reference, 1 if is_reconciled else 0, jid, now),
        )
        new_paid = int(inv["amount_paid_cents"]) + amount_cents
        new_status = "PAID" if (int(inv["total_cents"]) - new_paid - int(inv["amount_credited_cents"])) == 0 else "AUTHORISED"
        conn.execute(
            "UPDATE invoices SET amount_paid_cents=?, status=?, version=version+1, updated_at=? WHERE id=?",
            (new_paid, new_status, now, invoice_id),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "PAYMENT", pay_id, "RECORDED", f"{action_label} {decimal_str_from_cents(amount_cents)} recorded on {inv['invoice_number']} (Journal #{jnum}).")

    return {"id": pay_id, "journalId": jid, "journalNumber": jnum, "amount": decimal_str_from_cents(amount_cents), "invoice": get_invoice(conn, org_id, invoice_id)}


def delete_payment(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    payment_id: str,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    assert_can_write(actor_role)
    with atomic_tx(conn):
        pay = conn.execute("SELECT * FROM payments WHERE id = ? AND org_id = ?", (payment_id, org_id)).fetchone()
        if pay is None or pay["status"] == "DELETED":
            raise ApiError(404, "PAYMENT_NOT_FOUND", "Active payment not found.")
        assert_period_unlocked(conn, org_id, pay["payment_date"], actor_role)
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (pay["invoice_id"],)).fetchone()

        rev_jid, _ = reverse_journal(
            conn,
            org_id=org_id,
            original_journal_id=pay["journal_id"],
            reversal_date=pay["payment_date"],
            source_type=f"{'ACCREC_PAYMENT' if inv['invoice_type'] in RECEIVABLE_TYPES else 'ACCPAY_PAYMENT'}_REVERSAL",
            source_id=payment_id,
            narration=f"Delete payment on {inv['invoice_number']}",
            actor_user_id=actor_user_id,
        )
        conn.execute(
            "UPDATE payments SET status='DELETED', is_reconciled=0, reversal_journal_id=? WHERE id=?",
            (rev_jid, payment_id),
        )
        new_paid = max(0, int(inv["amount_paid_cents"]) - int(pay["amount_cents"]))
        conn.execute(
            "UPDATE invoices SET amount_paid_cents=?, status='AUTHORISED', version=version+1, updated_at=? WHERE id=?",
            (new_paid, utc_now_iso(), inv["id"]),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "PAYMENT", payment_id, "DELETED", f"Payment deleted and reversed on {inv['invoice_number']}.")
    return get_invoice(conn, org_id, inv["id"])


# --- Quotes & Purchase Orders (Pre-GL commercial documents) ---
def _get_commercial_doc(conn: sqlite3.Connection, org_id: str, table: str, lines_table: str, fk_col: str, doc_id: str) -> dict[str, Any]:
    doc = conn.execute(
        f"SELECT d.*, c.name AS contact_name FROM {table} d JOIN contacts c ON c.id = d.contact_id WHERE d.id = ? AND d.org_id = ?",
        (doc_id, org_id),
    ).fetchone()
    if doc is None:
        raise ApiError(404, "NOT_FOUND", "Commercial document not found.")
    lines = conn.execute(
        f"""
        SELECT l.*, a.code AS account_code, a.name AS account_name, tr.name AS tax_name
        FROM {lines_table} l JOIN accounts a ON a.id = l.account_id JOIN tax_rates tr ON tr.id = l.tax_rate_id
        WHERE l.{fk_col} = ? ORDER BY l.line_no
        """,
        (doc_id,),
    ).fetchall()
    d = dict(doc)
    if "quote_number" in d:
        d["quoteNumber"] = d["quote_number"]
        d["expiryDate"] = d.get("expiry_date")
    if "po_number" in d:
        d["poNumber"] = d["po_number"]
        d["deliveryDate"] = d.get("delivery_date")
    d["contactName"] = d.get("contact_name")
    d["issueDate"] = d.get("issue_date")
    d["taxMode"] = d.get("tax_mode")
    d["subTotal"] = decimal_str_from_cents(d["sub_total_cents"])
    d["totalTax"] = decimal_str_from_cents(d["total_tax_cents"])
    d["total"] = decimal_str_from_cents(d["total_cents"])
    d["lines"] = [
        {
            "id": l["id"],
            "lineNo": l["line_no"],
            "productId": l["product_id"],
            "description": l["description"],
            "quantity": l["quantity_decimal"],
            "unitAmount": l["unit_amount_decimal"],
            "discountPct": l["discount_pct_decimal"],
            "accountId": l["account_id"],
            "accountCode": l["account_code"],
            "accountName": l["account_name"],
            "taxRateId": l["tax_rate_id"],
            "taxName": l["tax_name"],
            "netAmount": decimal_str_from_cents(l["net_cents"]),
            "taxAmount": decimal_str_from_cents(l["tax_cents"]),
            "grossAmount": decimal_str_from_cents(l["gross_cents"]),
        }
        for l in lines
    ]
    return d


def _insert_commercial_lines(conn: sqlite3.Connection, table: str, fk_col: str, doc_id: str, prepared: list[dict[str, Any]]) -> None:
    for p in prepared:
        conn.execute(
            f"""
            INSERT INTO {table} (id, {fk_col}, line_no, product_id, description, quantity_decimal, unit_amount_decimal, discount_pct_decimal, account_id, tax_rate_id, net_cents, tax_cents, gross_cents, tracking_1_option_id, tracking_2_option_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id(), doc_id, p["line_no"], p["product_id"], p["description"], p["quantity_decimal"], p["unit_amount_decimal"], p["discount_pct_decimal"], p["account_id"], p["tax_rate_id"], p["net_cents"], p["tax_cents"], p["gross_cents"], p["tracking_1_option_id"], p["tracking_2_option_id"]),
        )


def create_quote(conn: sqlite3.Connection, *, org_id: str, payload: dict[str, Any], actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    assert_can_write(actor_role)
    contact_id = payload.get("contactId")
    if not contact_id or conn.execute("SELECT 1 FROM contacts WHERE id = ? AND org_id = ?", (contact_id, org_id)).fetchone() is None:
        raise ApiError(422, "CONTACT_NOT_FOUND", "Contact is required.")
    tax_mode = (payload.get("taxMode") or "EXCLUSIVE").upper()
    prepared, sub_t, tax_t, tot = _prepare_commercial_lines(conn, org_id, tax_mode, payload.get("lines", []))
    qid = new_id()
    now = utc_now_iso()
    status = (payload.get("status") or "DRAFT").upper()
    if status not in ("DRAFT", "SENT", "DECLINED", "ACCEPTED", "EXPIRED"):
        raise ApiError(422, "INVALID_QUOTE_STATUS", f"Invalid quote status '{status}'.")
    with atomic_tx(conn):
        qnum = payload.get("quoteNumber") or _next_doc_number(conn, org_id, "QUOTE")
        conn.execute(
            """
            INSERT INTO quotes (id, org_id, contact_id, quote_number, reference, issue_date, expiry_date, tax_mode, status, title, summary, terms, sub_total_cents, total_tax_cents, total_cents, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                qid, org_id, contact_id, qnum, payload.get("reference"),
                payload.get("issueDate") or date.today().isoformat(), payload.get("expiryDate"),
                tax_mode, status, payload.get("title"),
                payload.get("summary"), payload.get("terms"), sub_t, tax_t, tot, now, now,
            ),
        )
        _insert_commercial_lines(conn, "quote_lines", "quote_id", qid, prepared)
        write_audit(conn, org_id, actor_user_id, actor_name, "QUOTE", qid, "CREATED", f"Quote {qnum} created (zero GL impact).")
    return _get_commercial_doc(conn, org_id, "quotes", "quote_lines", "quote_id", qid)


def update_quote(conn: sqlite3.Connection, *, org_id: str, quote_id: str, payload: dict[str, Any], actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    assert_can_write(actor_role)
    with atomic_tx(conn):
        q = conn.execute("SELECT * FROM quotes WHERE id = ? AND org_id = ?", (quote_id, org_id)).fetchone()
        if q is None:
            raise ApiError(404, "QUOTE_NOT_FOUND", "Quote not found.")
        if q["status"] == "INVOICED":
            raise ApiError(422, "QUOTE_INVOICED", "Invoiced quotes cannot be edited.")
        new_status = (payload.get("status") or q["status"]).upper()
        if new_status not in ("DRAFT", "SENT", "DECLINED", "ACCEPTED", "EXPIRED"):
            raise ApiError(422, "INVALID_QUOTE_STATUS", f"Invalid quote status '{new_status}'.")
        contact_id = payload.get("contactId") or q["contact_id"]
        issue_date = payload.get("issueDate") or q["issue_date"]
        expiry_date = payload.get("expiryDate", q["expiry_date"])
        tax_mode = (payload.get("taxMode") or q["tax_mode"]).upper()
        reference = payload.get("reference", q["reference"])
        title = payload.get("title", q["title"])
        summary = payload.get("summary", q["summary"])
        terms = payload.get("terms", q["terms"])
        now = utc_now_iso()
        if "lines" in payload and payload["lines"] is not None:
            prepared, sub_t, tax_t, tot = _prepare_commercial_lines(conn, org_id, tax_mode, payload["lines"])
            conn.execute("DELETE FROM quote_lines WHERE quote_id = ?", (quote_id,))
            _insert_commercial_lines(conn, "quote_lines", "quote_id", quote_id, prepared)
        else:
            sub_t, tax_t, tot = int(q["sub_total_cents"]), int(q["total_tax_cents"]), int(q["total_cents"])
        conn.execute(
            """
            UPDATE quotes SET contact_id=?, reference=?, issue_date=?, expiry_date=?, tax_mode=?, status=?,
            title=?, summary=?, terms=?, sub_total_cents=?, total_tax_cents=?, total_cents=?, version=version+1, updated_at=?
            WHERE id=? AND org_id=?
            """,
            (contact_id, reference, issue_date, expiry_date, tax_mode, new_status, title, summary, terms, sub_t, tax_t, tot, now, quote_id, org_id),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "QUOTE", quote_id, "UPDATED", f"Quote {q['quote_number']} updated ({new_status}).")
    return _get_commercial_doc(conn, org_id, "quotes", "quote_lines", "quote_id", quote_id)


def delete_quote(conn: sqlite3.Connection, *, org_id: str, quote_id: str, actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    assert_can_write(actor_role)
    with atomic_tx(conn):
        q = conn.execute("SELECT * FROM quotes WHERE id = ? AND org_id = ?", (quote_id, org_id)).fetchone()
        if q is None:
            raise ApiError(404, "QUOTE_NOT_FOUND", "Quote not found.")
        if q["status"] == "INVOICED" or conn.execute("SELECT 1 FROM invoices WHERE source_quote_id = ?", (quote_id,)).fetchone():
            raise ApiError(422, "QUOTE_INVOICED", "Cannot delete a quote linked to an invoice.")
        conn.execute("DELETE FROM quote_lines WHERE quote_id = ?", (quote_id,))
        conn.execute("DELETE FROM quotes WHERE id = ? AND org_id = ?", (quote_id, org_id))
        write_audit(conn, org_id, actor_user_id, actor_name, "QUOTE", quote_id, "DELETED", f"Quote {q['quote_number']} deleted.")
    return {"deleted": True, "id": quote_id}


def convert_quote_to_invoice(conn: sqlite3.Connection, *, org_id: str, quote_id: str, approve: bool, actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    quote = _get_commercial_doc(conn, org_id, "quotes", "quote_lines", "quote_id", quote_id)
    if quote["status"] == "INVOICED" and quote["converted_invoice_id"]:
        return get_invoice(conn, org_id, quote["converted_invoice_id"])
    inv = create_invoice(
        conn,
        org_id=org_id,
        payload={
            "invoiceType": "ACCREC",
            "contactId": quote["contact_id"],
            "issueDate": date.today().isoformat(),
            "dueDate": date.today().isoformat(),
            "reference": quote["reference"] or quote["quote_number"],
            "taxMode": quote["tax_mode"],
            "sourceQuoteId": quote_id,
            "approveImmediately": approve,
            "lines": quote["lines"],
        },
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        actor_role=actor_role,
    )
    with atomic_tx(conn):
        conn.execute(
            "UPDATE quotes SET status='INVOICED', converted_invoice_id=?, updated_at=? WHERE id=?",
            (inv["id"], utc_now_iso(), quote_id),
        )
    return inv


def create_purchase_order(conn: sqlite3.Connection, *, org_id: str, payload: dict[str, Any], actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    assert_can_write(actor_role)
    contact_id = payload.get("contactId")
    if not contact_id or conn.execute("SELECT 1 FROM contacts WHERE id = ? AND org_id = ?", (contact_id, org_id)).fetchone() is None:
        raise ApiError(422, "CONTACT_NOT_FOUND", "Supplier contact is required.")
    tax_mode = (payload.get("taxMode") or "INCLUSIVE").upper()
    prepared, sub_t, tax_t, tot = _prepare_commercial_lines(conn, org_id, tax_mode, payload.get("lines", []))
    po_id = new_id()
    now = utc_now_iso()
    status = (payload.get("status") or "DRAFT").upper()
    if status not in ("DRAFT", "AWAITING_APPROVAL", "APPROVED"):
        raise ApiError(422, "INVALID_PO_STATUS", f"Invalid purchase order status '{status}'.")
    with atomic_tx(conn):
        ponum = payload.get("poNumber") or _next_doc_number(conn, org_id, "PO")
        conn.execute(
            """
            INSERT INTO purchase_orders (id, org_id, contact_id, po_number, reference, issue_date, delivery_date, tax_mode, status, delivery_instructions, sub_total_cents, total_tax_cents, total_cents, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                po_id, org_id, contact_id, ponum, payload.get("reference"),
                payload.get("issueDate") or date.today().isoformat(), payload.get("deliveryDate"),
                tax_mode, status, payload.get("deliveryInstructions"),
                sub_t, tax_t, tot, now, now,
            ),
        )
        _insert_commercial_lines(conn, "purchase_order_lines", "purchase_order_id", po_id, prepared)
        write_audit(conn, org_id, actor_user_id, actor_name, "PURCHASE_ORDER", po_id, "CREATED", f"Purchase order {ponum} created.")
    return _get_commercial_doc(conn, org_id, "purchase_orders", "purchase_order_lines", "purchase_order_id", po_id)


def update_purchase_order(conn: sqlite3.Connection, *, org_id: str, po_id: str, payload: dict[str, Any], actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    assert_can_write(actor_role)
    with atomic_tx(conn):
        po = conn.execute("SELECT * FROM purchase_orders WHERE id = ? AND org_id = ?", (po_id, org_id)).fetchone()
        if po is None or po["status"] == "DELETED":
            raise ApiError(404, "PO_NOT_FOUND", "Purchase order not found.")
        if po["status"] == "BILLED":
            raise ApiError(422, "PO_BILLED", "Billed purchase orders cannot be edited.")
        new_status = (payload.get("status") or po["status"]).upper()
        if new_status not in ("DRAFT", "AWAITING_APPROVAL", "APPROVED"):
            raise ApiError(422, "INVALID_PO_STATUS", f"Invalid purchase order status '{new_status}'.")
        contact_id = payload.get("contactId") or po["contact_id"]
        issue_date = payload.get("issueDate") or po["issue_date"]
        delivery_date = payload.get("deliveryDate", po["delivery_date"])
        tax_mode = (payload.get("taxMode") or po["tax_mode"]).upper()
        reference = payload.get("reference", po["reference"])
        instructions = payload.get("deliveryInstructions", po["delivery_instructions"])
        now = utc_now_iso()
        if "lines" in payload and payload["lines"] is not None:
            prepared, sub_t, tax_t, tot = _prepare_commercial_lines(conn, org_id, tax_mode, payload["lines"])
            conn.execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = ?", (po_id,))
            _insert_commercial_lines(conn, "purchase_order_lines", "purchase_order_id", po_id, prepared)
        else:
            sub_t, tax_t, tot = int(po["sub_total_cents"]), int(po["total_tax_cents"]), int(po["total_cents"])
        conn.execute(
            """
            UPDATE purchase_orders SET contact_id=?, reference=?, issue_date=?, delivery_date=?, tax_mode=?, status=?,
            delivery_instructions=?, sub_total_cents=?, total_tax_cents=?, total_cents=?, version=version+1, updated_at=?
            WHERE id=? AND org_id=?
            """,
            (contact_id, reference, issue_date, delivery_date, tax_mode, new_status, instructions, sub_t, tax_t, tot, now, po_id, org_id),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "PURCHASE_ORDER", po_id, "UPDATED", f"Purchase order {po['po_number']} updated ({new_status}).")
    return _get_commercial_doc(conn, org_id, "purchase_orders", "purchase_order_lines", "purchase_order_id", po_id)


def delete_purchase_order(conn: sqlite3.Connection, *, org_id: str, po_id: str, actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    assert_can_write(actor_role)
    with atomic_tx(conn):
        po = conn.execute("SELECT * FROM purchase_orders WHERE id = ? AND org_id = ?", (po_id, org_id)).fetchone()
        if po is None or po["status"] == "DELETED":
            raise ApiError(404, "PO_NOT_FOUND", "Purchase order not found.")
        if po["status"] == "BILLED" or conn.execute("SELECT 1 FROM invoices WHERE source_po_id = ?", (po_id,)).fetchone():
            raise ApiError(422, "PO_BILLED", "Cannot delete a purchase order linked to a bill.")
        conn.execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = ?", (po_id,))
        conn.execute("DELETE FROM purchase_orders WHERE id = ? AND org_id = ?", (po_id, org_id))
        write_audit(conn, org_id, actor_user_id, actor_name, "PURCHASE_ORDER", po_id, "DELETED", f"Purchase order {po['po_number']} deleted.")
    return {"deleted": True, "id": po_id}


def convert_po_to_bill(conn: sqlite3.Connection, *, org_id: str, po_id: str, approve: bool, actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    po = _get_commercial_doc(conn, org_id, "purchase_orders", "purchase_order_lines", "purchase_order_id", po_id)
    if po["status"] == "BILLED" and po["converted_bill_id"]:
        return get_invoice(conn, org_id, po["converted_bill_id"])
    bill = create_invoice(
        conn,
        org_id=org_id,
        payload={
            "invoiceType": "ACCPAY",
            "contactId": po["contact_id"],
            "invoiceNumber": f"BILL-{po['po_number']}",
            "issueDate": date.today().isoformat(),
            "dueDate": date.today().isoformat(),
            "reference": po["reference"] or po["po_number"],
            "taxMode": po["tax_mode"],
            "sourcePoId": po_id,
            "approveImmediately": approve,
            "lines": po["lines"],
        },
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        actor_role=actor_role,
    )
    with atomic_tx(conn):
        conn.execute(
            "UPDATE purchase_orders SET status='BILLED', converted_bill_id=?, updated_at=? WHERE id=?",
            (bill["id"], utc_now_iso(), po_id),
        )
    return bill
