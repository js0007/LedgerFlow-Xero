"""Banking, Reconciliation, Cash Coding & Bank Rules Service."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from collections import Counter
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..db import ApiError, atomic_tx, new_id, utc_now_iso
from ..money import cents_from_value, compute_line_amounts, decimal_str_from_cents, round_cents_decimal, to_decimal
from .documents import record_payment
from .ledger import (
    assert_can_write,
    assert_period_unlocked,
    get_system_account,
    get_tax_rate_by_code,
    parse_iso_date,
    post_journal,
    reverse_journal,
    signed_tax_line_amounts,
    write_audit,
)


def list_bank_accounts(conn: sqlite3.Connection, org_id: str) -> list[dict[str, Any]]:
    banks = conn.execute(
        "SELECT * FROM accounts WHERE org_id = ? AND account_type = 'BANK' AND status = 'ACTIVE' ORDER BY code, name",
        (org_id,),
    ).fetchall()
    result = []
    for b in banks:
        # Statement balance = sum of all active statement lines (CSV/Manual)
        stmt_row = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS bal, COUNT(CASE WHEN reconcile_status='UNRECONCILED' THEN 1 END) AS unrec FROM bank_statement_lines WHERE bank_account_id = ? AND reconcile_status != 'DELETED'",
            (b["id"],),
        ).fetchone()
        # Book balance = sum of immutable GL journal lines (Debit - Credit)
        gl_row = conn.execute(
            "SELECT COALESCE(SUM(debit_cents - credit_cents), 0) AS bal FROM journal_lines WHERE org_id = ? AND account_id = ?",
            (org_id, b["id"]),
        ).fetchone()
        stmt_cents = int(stmt_row["bal"])
        book_cents = int(gl_row["bal"])
        result.append(
            {
                "id": b["id"],
                "code": b["code"],
                "name": b["name"],
                "bankAccountNumber": b["bank_account_number"],
                "currency": b["bank_currency"] or "AUD",
                "statementBalance": decimal_str_from_cents(stmt_cents),
                "bookBalance": decimal_str_from_cents(book_cents),
                "difference": decimal_str_from_cents(stmt_cents - book_cents),
                "unreconciledCount": int(stmt_row["unrec"]),
            }
        )
    return result


def import_statement_lines(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    bank_account_id: str,
    csv_text: str | None = None,
    rows: list[dict[str, Any]] | None = None,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Import bank statement rows or CSV text with per-batch occurrence_idx deduplication."""
    assert_can_write(actor_role)
    bank = conn.execute(
        "SELECT * FROM accounts WHERE id = ? AND org_id = ? AND account_type = 'BANK'",
        (bank_account_id, org_id),
    ).fetchone()
    if bank is None:
        raise ApiError(404, "BANK_NOT_FOUND", "Bank account not found.")

    parsed_rows: list[dict[str, Any]] = []
    if csv_text is not None:
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        for r in reader:
            norm = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            tx_date = norm.get("date") or norm.get("txdate")
            amount = norm.get("amount")
            if not tx_date or amount is None or amount == "":
                continue
            parsed_rows.append(
                {
                    "txDate": tx_date,
                    "amount": amount,
                    "payee": norm.get("payee") or norm.get("merchant") or "",
                    "description": norm.get("description") or norm.get("memo") or "",
                    "reference": norm.get("reference") or "",
                    "chequeNumber": norm.get("chequenumber") or norm.get("cheque") or "",
                }
            )
    elif rows is not None:
        parsed_rows = rows
    else:
        raise ApiError(400, "NO_STATEMENT_DATA", "Provide either csvText or rows.")

    occ_counter: Counter[tuple[str, int, str, str]] = Counter()
    imported = 0
    skipped = 0
    created_ids: list[str] = []
    now = utc_now_iso()

    with atomic_tx(conn):
        for r in parsed_rows:
            tx_date = r["txDate"]
            parse_iso_date(tx_date)
            amt_c = cents_from_value(r["amount"])
            if amt_c == 0:
                continue
            payee = (r.get("payee") or "").strip()
            desc = (r.get("description") or "").strip()
            ref = (r.get("reference") or "").strip()
            cheque = (r.get("chequeNumber") or "").strip()

            occ_key = (tx_date, amt_c, payee.lower(), desc.lower())
            occ_counter[occ_key] += 1
            occ_idx = occ_counter[occ_key]

            raw_sig = f"{bank_account_id}|{tx_date}|{amt_c}|{payee}|{desc}|{ref}|{occ_idx}"
            imp_hash = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()

            exists = conn.execute(
                "SELECT id FROM bank_statement_lines WHERE bank_account_id = ? AND import_hash = ?",
                (bank_account_id, imp_hash),
            ).fetchone()
            if exists:
                skipped += 1
                continue

            lid = new_id()
            conn.execute(
                """
                INSERT INTO bank_statement_lines (
                    id, org_id, bank_account_id, tx_date, amount_cents, payee, description,
                    reference, cheque_number, occurrence_idx, import_hash, import_source,
                    reconcile_status, version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CSV', 'UNRECONCILED', 1, ?)
                """,
                (lid, org_id, bank_account_id, tx_date, amt_c, payee, desc, ref, cheque, occ_idx, imp_hash, now),
            )
            imported += 1
            created_ids.append(lid)

        write_audit(
            conn,
            org_id,
            actor_user_id,
            actor_name,
            "BANK_STATEMENT_IMPORT",
            bank_account_id,
            "IMPORTED",
            f"Imported {imported} statement line(s) into {bank['name']} ({skipped} duplicate(s) skipped).",
        )
    return {"importedCount": imported, "skippedDuplicates": skipped, "lineIds": created_ids}


def _evaluate_rule_conditions(rule: sqlite3.Row, line: sqlite3.Row) -> bool:
    conditions = json.loads(rule["conditions_json"] or "[]")
    if not conditions:
        return False
    strategy = (rule["match_strategy"] or "ALL").upper()

    def _matches_one(cond: dict[str, Any]) -> bool:
        field = (cond.get("field") or "PAYEE").upper()
        op = (cond.get("operator") or "CONTAINS").upper()
        val = str(cond.get("value") or "").strip()
        if field == "PAYEE":
            target = line["payee"] or ""
        elif field == "DESCRIPTION":
            target = line["description"] or ""
        elif field == "REFERENCE":
            target = line["reference"] or ""
        elif field == "ANY_TEXT":
            target = f"{line['payee'] or ''} {line['description'] or ''} {line['reference'] or ''}"
        elif field == "AMOUNT":
            try:
                return abs(int(line["amount_cents"])) == abs(cents_from_value(val))
            except Exception:
                return False
        else:
            target = line["payee"] or ""

        tl = target.lower()
        vl = val.lower()
        if op == "CONTAINS":
            return vl in tl
        if op == "EQUALS":
            return tl == vl
        if op == "STARTS_WITH":
            return tl.startswith(vl)
        return False

    results = [_matches_one(c) for c in conditions]
    return all(results) if strategy == "ALL" else any(results)


def _expand_rule_lines(rule: sqlite3.Row, total_abs_cents: int) -> list[dict[str, Any]]:
    """Compute fixed-amount + remainder-percent split lines for a matched Bank Rule."""
    fixed = json.loads(rule["fixed_lines_json"] or "[]")
    pcts = json.loads(rule["percent_lines_json"] or "[]")
    out: list[dict[str, Any]] = []
    allocated = 0

    for fx in fixed:
        amt = min(abs(cents_from_value(fx.get("amount", 0))), max(0, total_abs_cents - allocated))
        if amt > 0:
            allocated += amt
            out.append(
                {
                    "description": fx.get("description") or rule["name"],
                    "accountId": fx["accountId"],
                    "taxRateId": fx["taxRateId"],
                    "tracking1OptionId": fx.get("tracking1OptionId"),
                    "amount": decimal_str_from_cents(amt),
                    "amountCents": amt,
                }
            )

    remainder = max(0, total_abs_cents - allocated)
    if pcts and remainder > 0:
        pct_allocated = 0
        for idx, pl in enumerate(pcts):
            if idx == len(pcts) - 1:
                amt = remainder - pct_allocated
            else:
                pct = to_decimal(pl.get("percent", "100"))
                amt = int((to_decimal(remainder) * pct / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                pct_allocated += amt
            if amt > 0:
                out.append(
                    {
                        "description": pl.get("description") or rule["name"],
                        "accountId": pl["accountId"],
                        "taxRateId": pl["taxRateId"],
                        "tracking1OptionId": pl.get("tracking1OptionId"),
                        "amount": decimal_str_from_cents(amt),
                        "amountCents": amt,
                    }
                )
    return out


def get_reconciliation_suggestions(conn: sqlite3.Connection, org_id: str, bank_account_id: str) -> dict[str, Any]:
    bank_summary = next((b for b in list_bank_accounts(conn, org_id) if b["id"] == bank_account_id), None)
    if bank_summary is None:
        raise ApiError(404, "BANK_NOT_FOUND", "Bank account not found.")

    lines = conn.execute(
        "SELECT * FROM bank_statement_lines WHERE org_id = ? AND bank_account_id = ? AND reconcile_status = 'UNRECONCILED' ORDER BY tx_date, created_at",
        (org_id, bank_account_id),
    ).fetchall()

    rules = conn.execute(
        "SELECT * FROM bank_rules WHERE org_id = ? AND status = 'ACTIVE' AND (bank_account_scope IS NULL OR bank_account_scope = ?) ORDER BY priority_order, created_at",
        (org_id, bank_account_id),
    ).fetchall()

    open_docs = conn.execute(
        """
        SELECT i.*, c.name AS contact_name
        FROM invoices i JOIN contacts c ON c.id = i.contact_id
        WHERE i.org_id = ? AND i.status = 'AUTHORISED' AND i.invoice_type IN ('ACCREC', 'ACCPAY')
        ORDER BY i.due_date
        """,
        (org_id,),
    ).fetchall()

    unrec_payments = conn.execute(
        """
        SELECT p.*, i.invoice_number, i.invoice_type, c.name AS contact_name
        FROM payments p
        JOIN invoices i ON i.id = p.invoice_id
        JOIN contacts c ON c.id = i.contact_id
        WHERE p.org_id = ? AND p.bank_account_id = ? AND p.status = 'AUTHORISED' AND p.is_reconciled = 0
        """,
        (org_id, bank_account_id),
    ).fetchall()

    # Sibling bank accounts & open unlinked inter-bank transfers for transfer suggestions
    other_banks = conn.execute(
        "SELECT id, name FROM accounts WHERE org_id = ? AND account_type = 'BANK' AND id != ? AND status = 'ACTIVE'",
        (org_id, bank_account_id),
    ).fetchall()
    open_transfers = conn.execute(
        """
        SELECT bt.*, fa.name AS from_bank_name, ta.name AS to_bank_name
        FROM bank_transactions bt
        JOIN accounts fa ON fa.id = bt.bank_account_id
        JOIN accounts ta ON ta.id = bt.transfer_account_id
        WHERE bt.org_id = ? AND bt.tx_type = 'TRANSFER' AND bt.status = 'AUTHORISED'
          AND (bt.bank_account_id = ? OR bt.transfer_account_id = ?)
          AND NOT EXISTS (
              SELECT 1 FROM bank_statement_lines s
              WHERE s.org_id = bt.org_id AND s.bank_account_id = ?
                AND s.reconcile_status = 'RECONCILED'
                AND s.matched_entity_type = 'BANK_TRANSACTION'
                AND s.matched_entity_id = bt.id
          )
        """,
        (org_id, bank_account_id, bank_account_id, bank_account_id),
    ).fetchall()

    stmt_items = []
    for l in lines:
        amt = int(l["amount_cents"])
        abs_amt = abs(amt)
        is_deposit = amt > 0
        expected_doc_type = "ACCREC" if is_deposit else "ACCPAY"
        expected_rule_type = "RECEIVE" if is_deposit else "SPEND"

        # 1. Existing un-reconciled Payment match
        matched_payment = None
        for p in unrec_payments:
            p_signed = int(p["amount_cents"]) if p["invoice_type"] in ("ACCREC", "ACCPAYCREDIT") else -int(p["amount_cents"])
            if p_signed == amt:
                matched_payment = {
                    "paymentId": p["id"],
                    "invoiceId": p["invoice_id"],
                    "invoiceNumber": p["invoice_number"],
                    "contactName": p["contact_name"],
                    "paymentDate": p["payment_date"],
                    "amount": decimal_str_from_cents(p["amount_cents"]),
                }
                break

        # 1b. Existing open Inter-Bank Transfer match
        matched_transfer = None
        if matched_payment is None:
            for trf in open_transfers:
                expected_signed = int(trf["total_cents"]) if trf["transfer_account_id"] == bank_account_id else -int(trf["total_cents"])
                if expected_signed == amt:
                    matched_transfer = {
                        "bankTxId": trf["id"],
                        "fromBankAccountId": trf["bank_account_id"],
                        "fromBankName": trf["from_bank_name"],
                        "toBankAccountId": trf["transfer_account_id"],
                        "toBankName": trf["to_bank_name"],
                        "txDate": trf["tx_date"],
                        "amount": decimal_str_from_cents(trf["total_cents"]),
                        "reference": trf["reference"],
                    }
                    break

        # 2. Open Invoice/Bill match
        matched_doc = None
        if matched_payment is None and matched_transfer is None:
            for d in open_docs:
                if d["invoice_type"] != expected_doc_type:
                    continue
                due_c = int(d["total_cents"]) - int(d["amount_paid_cents"]) - int(d["amount_credited_cents"])
                if due_c == abs_amt:
                    matched_doc = {
                        "invoiceId": d["id"],
                        "invoiceNumber": d["invoice_number"],
                        "invoiceType": d["invoice_type"],
                        "contactId": d["contact_id"],
                        "contactName": d["contact_name"],
                        "dueDate": d["due_date"],
                        "amountDue": decimal_str_from_cents(due_c),
                    }
                    break

        # 3. Bank Rule evaluation
        matched_rule = None
        for rule in rules:
            if not _evaluate_rule_conditions(rule, l):
                continue
            if rule["rule_type"] == "TRANSFER" and rule["target_bank_id"]:
                matched_rule = {
                    "ruleId": rule["id"],
                    "ruleName": rule["name"],
                    "ruleType": "TRANSFER",
                    "targetBankId": rule["target_bank_id"],
                }
                break
            elif rule["rule_type"] == expected_rule_type:
                rule_lines = _expand_rule_lines(rule, abs_amt)
                if rule_lines:
                    matched_rule = {
                        "ruleId": rule["id"],
                        "ruleName": rule["name"],
                        "ruleType": rule["rule_type"],
                        "contactId": rule["contact_id"],
                        "lines": rule_lines,
                    }
                    break

        suggestion_type = "NONE"
        if matched_payment:
            suggestion_type = "MATCH_EXISTING_PAYMENT"
        elif matched_transfer:
            suggestion_type = "MATCH_EXISTING_TRANSFER"
        elif matched_doc:
            suggestion_type = "MATCH_INVOICE"
        elif matched_rule:
            suggestion_type = "BANK_RULE"

        stmt_items.append(
            {
                "id": l["id"],
                "txDate": l["tx_date"],
                "amount": decimal_str_from_cents(amt),
                "spent": decimal_str_from_cents(abs_amt) if amt < 0 else None,
                "received": decimal_str_from_cents(abs_amt) if amt > 0 else None,
                "payee": l["payee"],
                "description": l["description"],
                "reference": l["reference"],
                "chequeNumber": l["cheque_number"],
                "discussNote": l["discuss_note"],
                "version": l["version"],
                "suggestionType": suggestion_type,
                "matchedPayment": matched_payment,
                "matchedTransfer": matched_transfer,
                "matchedDocument": matched_doc,
                "matchedRule": matched_rule,
            }
        )

    open_docs_formatted = [
        {
            "id": d["id"],
            "invoiceNumber": d["invoice_number"],
            "invoiceType": d["invoice_type"],
            "contactId": d["contact_id"],
            "contactName": d["contact_name"],
            "issueDate": d["issue_date"],
            "dueDate": d["due_date"],
            "total": decimal_str_from_cents(d["total_cents"]),
            "amountDue": decimal_str_from_cents(int(d["total_cents"]) - int(d["amount_paid_cents"]) - int(d["amount_credited_cents"])),
        }
        for d in open_docs
    ]

    return {
        "bankAccount": bank_summary,
        "statementLines": stmt_items,
        "openDocuments": open_docs_formatted,
        "otherBankAccounts": [dict(ob) for ob in other_banks],
    }


def _create_bank_tx_core(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    bank_account_id: str,
    tx_date: str,
    signed_amount_cents: int,
    payload: dict[str, Any],
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
    is_reconciled: bool,
) -> tuple[str, str, int]:
    """Post a Receive/Spend Money transaction and its immutable CASHREC/CASHPAID GL journal."""
    assert_can_write(actor_role)
    assert_period_unlocked(conn, org_id, tx_date, actor_role)
    raw_lines = payload.get("lines") or []
    if not raw_lines:
        raise ApiError(422, "NO_BANK_TX_LINES", "Bank transaction requires at least one allocation line.")

    tax_mode = (payload.get("taxMode") or "INCLUSIVE").upper()
    tx_type = "RECEIVE" if signed_amount_cents > 0 else "SPEND"
    source_type = "CASHREC" if tx_type == "RECEIVE" else "CASHPAID"
    abs_target = abs(signed_amount_cents)
    gst_acc = get_system_account(conn, org_id, "GST")
    no_tax_tr = get_tax_rate_by_code(conn, org_id, "BASEXCLUDED")

    prepared_lines = []
    sub_total = 0
    total_tax = 0
    total_gross = 0

    for idx, line in enumerate(raw_lines, start=1):
        acc = conn.execute("SELECT * FROM accounts WHERE id = ? AND org_id = ?", (line.get("accountId"), org_id)).fetchone()
        if acc is None:
            raise ApiError(422, "INVALID_ACCOUNT", f"Line {idx}: account not found.")
        tr = no_tax_tr if tax_mode == "NO_TAX" else conn.execute(
            "SELECT * FROM tax_rates WHERE id = ? AND org_id = ?",
            (line.get("taxRateId") or acc["default_tax_rate_id"] or no_tax_tr["id"], org_id),
        ).fetchone()
        if tr is None:
            raise ApiError(422, "INVALID_TAX_RATE", f"Line {idx}: tax rate not found.")

        line_amt_val = line.get("amount") if line.get("amount") is not None else line.get("unitAmount")
        line_amt_str = str(line_amt_val if line_amt_val is not None else decimal_str_from_cents(abs_target if len(raw_lines) == 1 else 0))
        net_c, tax_c, gross_c = compute_line_amounts("1", line_amt_str, "0", tr["rate_decimal"], tax_mode)
        sub_total += net_c
        total_tax += tax_c
        total_gross += gross_c
        prepared_lines.append(
            {
                "line_no": idx,
                "description": line.get("description") or payload.get("description") or payload.get("reference") or tx_type,
                "account_id": acc["id"],
                "tax_rate_id": tr["id"],
                "tax_type_code": tr["code"],
                "net_cents": net_c,
                "tax_cents": tax_c,
                "gross_cents": gross_c,
                "tracking_1_option_id": line.get("tracking1OptionId"),
                "tracking_2_option_id": line.get("tracking2OptionId"),
            }
        )

    if total_gross != abs_target:
        raise ApiError(
            422,
            "AMOUNT_MISMATCH",
            f"Allocated lines total ({decimal_str_from_cents(total_gross)}) must equal statement amount ({decimal_str_from_cents(abs_target)}).",
        )

    tx_id = new_id()
    gl_lines: list[dict[str, Any]] = []
    if tx_type == "RECEIVE":
        gl_lines.append({"account_id": bank_account_id, "contact_id": payload.get("contactId"), "description": payload.get("reference") or "Receive Money", "debit_cents": total_gross, "credit_cents": 0})
        for p in prepared_lines:
            s_gross, s_net, s_tax = signed_tax_line_amounts(
                p["tax_type_code"], is_credit=True, gross_cents=p["gross_cents"], net_cents=p["net_cents"], tax_cents=p["tax_cents"]
            )
            gl_lines.append({
                "account_id": p["account_id"], "contact_id": payload.get("contactId"), "description": p["description"],
                "debit_cents": 0, "credit_cents": p["net_cents"], "tax_rate_id": p["tax_rate_id"], "tax_type_code": p["tax_type_code"],
                "gross_cents": s_gross, "net_cents": s_net, "tax_cents": s_tax,
                "tracking_1_option_id": p["tracking_1_option_id"], "tracking_2_option_id": p["tracking_2_option_id"],
            })
        if total_tax > 0:
            gl_lines.append({"account_id": gst_acc["id"], "description": "GST on Receive Money", "debit_cents": 0, "credit_cents": total_tax})
    else:
        for p in prepared_lines:
            s_gross, s_net, s_tax = signed_tax_line_amounts(
                p["tax_type_code"], is_credit=False, gross_cents=p["gross_cents"], net_cents=p["net_cents"], tax_cents=p["tax_cents"]
            )
            gl_lines.append({
                "account_id": p["account_id"], "contact_id": payload.get("contactId"), "description": p["description"],
                "debit_cents": p["net_cents"], "credit_cents": 0, "tax_rate_id": p["tax_rate_id"], "tax_type_code": p["tax_type_code"],
                "gross_cents": s_gross, "net_cents": s_net, "tax_cents": s_tax,
                "tracking_1_option_id": p["tracking_1_option_id"], "tracking_2_option_id": p["tracking_2_option_id"],
            })
        if total_tax > 0:
            gl_lines.append({"account_id": gst_acc["id"], "description": "GST on Spend Money", "debit_cents": total_tax, "credit_cents": 0})
        gl_lines.append({"account_id": bank_account_id, "contact_id": payload.get("contactId"), "description": payload.get("reference") or "Spend Money", "debit_cents": 0, "credit_cents": total_gross})

    jid, jnum = post_journal(
        conn, org_id=org_id, journal_date=tx_date, source_type=source_type, source_id=tx_id,
        reference=payload.get("reference"), narration=f"{tx_type} Money", lines=gl_lines, actor_user_id=actor_user_id,
    )
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO bank_transactions (id, org_id, tx_type, bank_account_id, contact_id, tx_date, reference, tax_mode, sub_total_cents, total_tax_cents, total_cents, is_reconciled, status, journal_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AUTHORISED', ?, ?)
        """,
        (tx_id, org_id, tx_type, bank_account_id, payload.get("contactId"), tx_date, payload.get("reference"), tax_mode, sub_total, total_tax, total_gross, 1 if is_reconciled else 0, jid, now),
    )
    for p in prepared_lines:
        conn.execute(
            """
            INSERT INTO bank_transaction_lines (id, bank_transaction_id, line_no, description, account_id, tax_rate_id, net_cents, tax_cents, gross_cents, tracking_1_option_id, tracking_2_option_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id(), tx_id, p["line_no"], p["description"], p["account_id"], p["tax_rate_id"], p["net_cents"], p["tax_cents"], p["gross_cents"], p["tracking_1_option_id"], p["tracking_2_option_id"]),
        )
    return tx_id, jid, jnum


def _parse_matched_ids(raw_json: str | None, fallback_id: str | None) -> tuple[list[str], str | None]:
    """Decode matched_entity_ids_json supporting legacy list[str] or dict{paymentIds, adjustmentBankTxId}."""
    if not raw_json:
        return ([fallback_id] if fallback_id else []), None
    parsed = json.loads(raw_json)
    if isinstance(parsed, dict):
        pids = list(parsed.get("paymentIds") or ([fallback_id] if fallback_id else []))
        return pids, parsed.get("adjustmentBankTxId")
    if isinstance(parsed, list):
        return (list(parsed) or ([fallback_id] if fallback_id else [])), None
    return ([fallback_id] if fallback_id else []), None


def _reverse_bank_tx_row(conn: sqlite3.Connection, org_id: str, btx: sqlite3.Row, actor_user_id: str, narration: str) -> None:
    """Append-only reverse one AUTHORISED bank_transaction and mark it DELETED."""
    src_rev = {"RECEIVE": "CASHREC_REVERSAL", "SPEND": "CASHPAID_REVERSAL", "TRANSFER": "TRANSFER_REVERSAL"}[btx["tx_type"]]
    rev_jid, _ = reverse_journal(
        conn,
        org_id=org_id,
        original_journal_id=btx["journal_id"],
        reversal_date=btx["tx_date"],
        source_type=src_rev,
        source_id=btx["id"],
        narration=narration,
        actor_user_id=actor_user_id,
    )
    conn.execute("UPDATE bank_transactions SET status='DELETED', is_reconciled=0, reversal_journal_id=? WHERE id=?", (rev_jid, btx["id"]))


def reconcile_statement_line(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    bank_account_id: str,
    payload: dict[str, Any],
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Atomically reconcile one statement line via MATCH_INVOICE, MATCH_EXISTING_PAYMENT, MATCH_TRANSFER, CREATE_BANK_TX, or TRANSFER."""
    assert_can_write(actor_role)
    stmt_id = payload.get("statementLineId")
    expected_version = payload.get("version")
    action = (payload.get("action") or "").upper()
    if not stmt_id or not action:
        raise ApiError(422, "MISSING_FIELDS", "statementLineId and action are required.")

    now = utc_now_iso()

    with atomic_tx(conn):
        stmt = conn.execute(
            "SELECT * FROM bank_statement_lines WHERE id = ? AND org_id = ? AND bank_account_id = ?",
            (stmt_id, org_id, bank_account_id),
        ).fetchone()
        if stmt is None:
            raise ApiError(404, "STATEMENT_LINE_NOT_FOUND", "Bank statement line not found.")
        if stmt["reconcile_status"] != "UNRECONCILED":
            raise ApiError(409, "ALREADY_RECONCILED", "This bank statement line has already been reconciled.")
        if expected_version is not None and int(stmt["version"]) != int(expected_version):
            raise ApiError(409, "VERSION_CONFLICT", "Statement line was modified by another request. Refresh and retry.")

        amt_cents = int(stmt["amount_cents"])
        abs_cents = abs(amt_cents)

        if action == "MATCH_EXISTING_PAYMENT":
            pay_id = payload.get("paymentId")
            pay = conn.execute(
                "SELECT * FROM payments WHERE id = ? AND org_id = ? AND bank_account_id = ? AND status = 'AUTHORISED'",
                (pay_id, org_id, bank_account_id),
            ).fetchone()
            if pay is None:
                raise ApiError(404, "PAYMENT_NOT_FOUND", "Existing payment not found.")
            if int(pay["amount_cents"]) != abs_cents:
                raise ApiError(422, "AMOUNT_MISMATCH", "Payment amount does not match statement line.")
            conn.execute("UPDATE payments SET is_reconciled = 1 WHERE id = ?", (pay_id,))
            conn.execute(
                """
                UPDATE bank_statement_lines
                SET reconcile_status='RECONCILED', matched_entity_type='PAYMENT', matched_entity_id=?, reconciled_at=?, version=version+1
                WHERE id=?
                """,
                (pay_id, now, stmt_id),
            )
            write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RECONCILIATION", stmt_id, "MATCHED_PAYMENT", f"Matched statement line to existing Payment {pay['id'][:8]}.")

        elif action == "MATCH_TRANSFER":
            btx_id = payload.get("matchedBankTransactionId") or payload.get("bankTransactionId")
            trf = conn.execute(
                "SELECT * FROM bank_transactions WHERE id = ? AND org_id = ? AND tx_type = 'TRANSFER' AND status = 'AUTHORISED'",
                (btx_id, org_id),
            ).fetchone()
            if trf is None:
                raise ApiError(404, "TRANSFER_NOT_FOUND", "Inter-bank transfer not found.")
            expected_signed = int(trf["total_cents"]) if trf["transfer_account_id"] == bank_account_id else (-int(trf["total_cents"]) if trf["bank_account_id"] == bank_account_id else None)
            if expected_signed is None or expected_signed != amt_cents:
                raise ApiError(422, "AMOUNT_MISMATCH", "Transfer direction or amount does not match statement line.")
            already_matched = conn.execute(
                "SELECT 1 FROM bank_statement_lines WHERE org_id = ? AND bank_account_id = ? AND reconcile_status = 'RECONCILED' AND matched_entity_type = 'BANK_TRANSACTION' AND matched_entity_id = ?",
                (org_id, bank_account_id, trf["id"]),
            ).fetchone()
            if already_matched:
                raise ApiError(409, "TRANSFER_ALREADY_MATCHED", "This transfer is already reconciled on this bank account.")
            conn.execute("UPDATE bank_transactions SET is_reconciled = 1 WHERE id = ?", (trf["id"],))
            conn.execute(
                """
                UPDATE bank_statement_lines
                SET reconcile_status='RECONCILED', matched_entity_type='BANK_TRANSACTION', matched_entity_id=?, reconciled_at=?, version=version+1
                WHERE id=?
                """,
                (trf["id"], now, stmt_id),
            )
            write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RECONCILIATION", stmt_id, "MATCHED_TRANSFER", f"Matched statement line to existing Transfer {trf['id'][:8]} (no duplicate journal).")

        elif action == "MATCH_INVOICE":
            allocs = payload.get("matchAllocations") or ([{"invoiceId": payload["invoiceId"], "amount": payload.get("amount")}] if payload.get("invoiceId") else [])
            if not allocs:
                raise ApiError(422, "MATCH_MISSING", "Select at least one invoice or bill to match.")
            ma = payload.get("minorAdjustment", 0)
            if isinstance(ma, dict):
                adj_cents = cents_from_value(ma.get("amount", 0))
                adj_account_id = ma.get("accountId") or payload.get("adjustmentAccountId")
            else:
                adj_cents = cents_from_value(ma)
                adj_account_id = payload.get("adjustmentAccountId")
            sum_allocs = sum(cents_from_value(a.get("amount", 0)) for a in allocs)

            # Deposit (+): bank receives less or more via minor adjustment (e.g. invoice 100.05, bank 100.00 -> adj -5c)
            if sum_allocs + adj_cents != abs_cents:
                raise ApiError(
                    422,
                    "MATCH_SUM_MISMATCH",
                    f"Matched invoice amounts ({decimal_str_from_cents(sum_allocs)}) + adjustment ({decimal_str_from_cents(adj_cents)}) must equal {decimal_str_from_cents(abs_cents)}.",
                )
            payment_ids = []
            for a in allocs:
                ac = cents_from_value(a.get("amount", 0))
                res = record_payment(
                    conn,
                    org_id=org_id,
                    invoice_id=a["invoiceId"],
                    bank_account_id=bank_account_id,
                    payment_date=stmt["tx_date"],
                    amount_cents=ac,
                    reference=stmt["reference"] or stmt["payee"],
                    actor_user_id=actor_user_id,
                    actor_name=actor_name,
                    actor_role=actor_role,
                    is_reconciled=True,
                )
                payment_ids.append(res["id"])

            adj_btx_id: str | None = None
            if adj_cents != 0:
                if not adj_account_id:
                    adj_account_id = get_system_account(conn, org_id, "ROUNDING")["id"]
                adj_tax = get_tax_rate_by_code(conn, org_id, "BASEXCLUDED")["id"]
                signed_adj = adj_cents if amt_cents > 0 else -adj_cents
                adj_btx_id, _, _ = _create_bank_tx_core(
                    conn, org_id=org_id, bank_account_id=bank_account_id, tx_date=stmt["tx_date"], signed_amount_cents=signed_adj,
                    payload={"reference": "Minor adjustment", "taxMode": "NO_TAX", "lines": [{"accountId": adj_account_id, "taxRateId": adj_tax, "amount": decimal_str_from_cents(abs(signed_adj)), "description": "Minor adjustment during reconciliation"}]},
                    actor_user_id=actor_user_id, actor_name=actor_name, actor_role=actor_role, is_reconciled=True,
                )

            matched_ids_blob = (
                json.dumps({"paymentIds": payment_ids, "adjustmentBankTxId": adj_btx_id})
                if adj_btx_id
                else json.dumps(payment_ids)
            )
            conn.execute(
                """
                UPDATE bank_statement_lines
                SET reconcile_status='RECONCILED', matched_entity_type=?, matched_entity_id=?, matched_entity_ids_json=?, reconciled_at=?, version=version+1
                WHERE id=?
                """,
                ("PAYMENT" if len(payment_ids) == 1 else "PAYMENT_GROUP", payment_ids[0], matched_ids_blob, now, stmt_id),
            )
            write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RECONCILIATION", stmt_id, "RECONCILED_MATCH", f"Reconciled statement line via {len(payment_ids)} invoice payment(s).")

        elif action == "CREATE_BANK_TX":
            cp = payload.get("createPayload")
            if not cp and payload.get("bankRuleId"):
                rule = conn.execute("SELECT * FROM bank_rules WHERE id = ? AND org_id = ?", (payload["bankRuleId"], org_id)).fetchone()
                if rule is None:
                    raise ApiError(404, "RULE_NOT_FOUND", "Bank rule not found.")
                cp = {"contactId": rule["contact_id"], "taxMode": "INCLUSIVE", "reference": stmt["reference"] or rule["name"], "lines": _expand_rule_lines(rule, abs_cents)}
            elif not cp:
                cp = payload
            tx_id, jid, jnum = _create_bank_tx_core(
                conn,
                org_id=org_id,
                bank_account_id=bank_account_id,
                tx_date=stmt["tx_date"],
                signed_amount_cents=amt_cents,
                payload=cp,
                actor_user_id=actor_user_id,
                actor_name=actor_name,
                actor_role=actor_role,
                is_reconciled=True,
            )
            conn.execute(
                """
                UPDATE bank_statement_lines
                SET reconcile_status='RECONCILED', matched_entity_type='BANK_TRANSACTION', matched_entity_id=?, reconciled_at=?, version=version+1
                WHERE id=?
                """,
                (tx_id, now, stmt_id),
            )
            write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RECONCILIATION", stmt_id, "RECONCILED_CREATE", f"Reconciled statement line by creating bank transaction (Journal #{jnum}).")

        elif action == "TRANSFER":
            assert_period_unlocked(conn, org_id, stmt["tx_date"], actor_role)
            target_bank_id = payload.get("transferBankAccountId") or payload.get("targetBankAccountId")
            if not target_bank_id or target_bank_id == bank_account_id:
                raise ApiError(422, "INVALID_TRANSFER_ACCOUNT", "Choose a different active bank account for Transfer.")
            tgt = conn.execute("SELECT * FROM accounts WHERE id = ? AND org_id = ? AND account_type = 'BANK'", (target_bank_id, org_id)).fetchone()
            if tgt is None:
                raise ApiError(404, "TARGET_BANK_NOT_FOUND", "Transfer destination bank account not found.")

            # Match existing open opposite-side inter-bank transfer (±7 days) to avoid duplicate posting
            stmt_d = parse_iso_date(stmt["tx_date"])
            sibling = None
            if not payload.get("forceCreateNew"):
                src_bank_expected = target_bank_id if amt_cents > 0 else bank_account_id
                dst_bank_expected = bank_account_id if amt_cents > 0 else target_bank_id
                candidates = conn.execute(
                    """
                    SELECT * FROM bank_transactions bt
                    WHERE bt.org_id = ? AND bt.tx_type = 'TRANSFER' AND bt.status = 'AUTHORISED' AND bt.total_cents = ?
                      AND bt.bank_account_id = ? AND bt.transfer_account_id = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM bank_statement_lines s
                          WHERE s.org_id = bt.org_id AND s.bank_account_id = ?
                            AND s.reconcile_status = 'RECONCILED'
                            AND s.matched_entity_type = 'BANK_TRANSACTION'
                            AND s.matched_entity_id = bt.id
                      )
                    ORDER BY bt.tx_date
                    """,
                    (org_id, abs_cents, src_bank_expected, dst_bank_expected, bank_account_id),
                ).fetchall()
                for cand in candidates:
                    if abs((stmt_d - parse_iso_date(cand["tx_date"])).days) <= 7:
                        sibling = cand
                        break

            if sibling is not None:
                conn.execute("UPDATE bank_transactions SET is_reconciled = 1 WHERE id = ?", (sibling["id"],))
                conn.execute(
                    """
                    UPDATE bank_statement_lines
                    SET reconcile_status='RECONCILED', matched_entity_type='BANK_TRANSACTION', matched_entity_id=?, reconciled_at=?, version=version+1
                    WHERE id=?
                    """,
                    (sibling["id"], now, stmt_id),
                )
                write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RECONCILIATION", stmt_id, "MATCHED_TRANSFER", f"Matched statement line to existing inter-bank transfer {sibling['id'][:8]}.")
            else:
                # If bank statement amt < 0: Money left bank_account_id -> Credit bank_account_id, Debit target_bank_id
                # If bank statement amt > 0: Money entered bank_account_id -> Debit bank_account_id, Credit target_bank_id
                dr_bank = target_bank_id if amt_cents < 0 else bank_account_id
                cr_bank = bank_account_id if amt_cents < 0 else target_bank_id
                tx_id = new_id()
                jid, jnum = post_journal(
                    conn,
                    org_id=org_id,
                    journal_date=stmt["tx_date"],
                    source_type="TRANSFER",
                    source_id=tx_id,
                    reference=payload.get("reference") or stmt["reference"] or "Bank Transfer",
                    narration="Bank Transfer",
                    lines=[
                        {"account_id": dr_bank, "description": "Bank Transfer In", "debit_cents": abs_cents, "credit_cents": 0},
                        {"account_id": cr_bank, "description": "Bank Transfer Out", "debit_cents": 0, "credit_cents": abs_cents},
                    ],
                    actor_user_id=actor_user_id,
                )
                conn.execute(
                    """
                    INSERT INTO bank_transactions (id, org_id, tx_type, bank_account_id, transfer_account_id, tx_date, reference, tax_mode, sub_total_cents, total_tax_cents, total_cents, is_reconciled, status, journal_id, created_at)
                    VALUES (?, ?, 'TRANSFER', ?, ?, ?, ?, 'NO_TAX', ?, 0, ?, 1, 'AUTHORISED', ?, ?)
                    """,
                    (tx_id, org_id, bank_account_id, target_bank_id, stmt["tx_date"], payload.get("reference") or "Transfer", abs_cents, abs_cents, jid, now),
                )
                conn.execute(
                    """
                    UPDATE bank_statement_lines
                    SET reconcile_status='RECONCILED', matched_entity_type='BANK_TRANSACTION', matched_entity_id=?, reconciled_at=?, version=version+1
                    WHERE id=?
                    """,
                    (tx_id, now, stmt_id),
                )
                write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RECONCILIATION", stmt_id, "RECONCILED_TRANSFER", f"Recorded bank transfer of {decimal_str_from_cents(abs_cents)} (Journal #{jnum}).")

        else:
            raise ApiError(400, "INVALID_RECONCILE_ACTION", f"Unknown action '{action}'.")

    return {"statementLineId": stmt_id, "status": "RECONCILED", "bankAccount": next(b for b in list_bank_accounts(conn, org_id) if b["id"] == bank_account_id)}


def cash_coding_batch_apply(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    bank_account_id: str,
    items: list[dict[str, Any]],
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Atomically apply Cash Coding grid selections (Account + TaxRate + Tracking) and reconcile all rows together."""
    assert_can_write(actor_role)
    if not items:
        raise ApiError(422, "EMPTY_BATCH", "Select at least one Cash Coding row.")
    reconciled = 0
    with atomic_tx(conn):
        for idx, it in enumerate(items, start=1):
            stmt_id = it.get("statementLineId")
            if not stmt_id:
                raise ApiError(422, "MISSING_STATEMENT_LINE_ID", f"Row {idx}: statementLineId is required.")
            stmt = conn.execute(
                "SELECT * FROM bank_statement_lines WHERE id = ? AND org_id = ? AND bank_account_id = ?",
                (stmt_id, org_id, bank_account_id),
            ).fetchone()
            if stmt is None:
                raise ApiError(404, "STATEMENT_LINE_NOT_FOUND", f"Row {idx}: statement line not found.")
            if stmt["reconcile_status"] != "UNRECONCILED":
                raise ApiError(409, "ALREADY_RECONCILED", f"Row {idx}: statement line was already reconciled.")
            if not it.get("lines") and (not it.get("accountId") or not it.get("taxRateId")):
                raise ApiError(422, "CASH_CODING_FIELDS_MISSING", f"Row {idx}: accountId and taxRateId are required.")
            abs_amt_str = decimal_str_from_cents(abs(int(stmt["amount_cents"])))
            reconcile_statement_line(
                conn,
                org_id=org_id,
                bank_account_id=bank_account_id,
                payload={
                    "statementLineId": stmt["id"],
                    "version": it["version"] if it.get("version") is not None else stmt["version"],
                    "action": "CREATE_BANK_TX",
                    "createPayload": {
                        "contactId": it.get("contactId"),
                        "taxMode": it.get("taxMode") or "INCLUSIVE",
                        "reference": it.get("reference") or stmt["reference"],
                        "lines": it.get("lines") or [
                            {
                                "description": it.get("description") or stmt["description"] or stmt["payee"] or "Cash Coding",
                                "accountId": it["accountId"],
                                "taxRateId": it["taxRateId"],
                                "tracking1OptionId": it.get("tracking1OptionId"),
                                "amount": abs_amt_str,
                            }
                        ],
                    },
                },
                actor_user_id=actor_user_id,
                actor_name=actor_name,
                actor_role=actor_role,
            )
            reconciled += 1
    return {"reconciledCount": reconciled}


def unreconcile_statement_line(conn: sqlite3.Connection, *, org_id: str, bank_account_id: str, stmt_id: str, actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    """Unlink statement line from Payment/BankTx without deleting the GL entry (matches Xero Unreconcile)."""
    assert_can_write(actor_role)
    with atomic_tx(conn):
        stmt = conn.execute("SELECT * FROM bank_statement_lines WHERE id = ? AND org_id = ? AND bank_account_id = ?", (stmt_id, org_id, bank_account_id)).fetchone()
        if stmt is None or stmt["reconcile_status"] != "RECONCILED":
            raise ApiError(404, "RECONCILED_LINE_NOT_FOUND", "Reconciled statement line not found.")
        if stmt["matched_entity_type"] == "BANK_TRANSACTION" and stmt["matched_entity_id"]:
            conn.execute("UPDATE bank_transactions SET is_reconciled = 0 WHERE id = ?", (stmt["matched_entity_id"],))
        elif stmt["matched_entity_type"] in ("PAYMENT", "PAYMENT_GROUP"):
            pids, adj_btx_id = _parse_matched_ids(stmt["matched_entity_ids_json"], stmt["matched_entity_id"])
            for pid in pids:
                conn.execute("UPDATE payments SET is_reconciled = 0 WHERE id = ?", (pid,))
            if adj_btx_id:
                conn.execute("UPDATE bank_transactions SET is_reconciled = 0 WHERE id = ?", (adj_btx_id,))
        conn.execute(
            "UPDATE bank_statement_lines SET reconcile_status='UNRECONCILED', matched_entity_type=NULL, matched_entity_id=NULL, matched_entity_ids_json=NULL, reconciled_at=NULL, version=version+1 WHERE id=?",
            (stmt_id,),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RECONCILIATION", stmt_id, "UNRECONCILED", "Unreconciled statement line while preserving underlying transaction.")
    return {"status": "UNRECONCILED"}


def remove_and_redo_statement_line(conn: sqlite3.Connection, *, org_id: str, bank_account_id: str, stmt_id: str, actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    """Reverse posted Payment or BankTransaction with append-only reversal journal & reopen statement line (Xero Remove & Redo)."""
    assert_can_write(actor_role)
    with atomic_tx(conn):
        stmt = conn.execute("SELECT * FROM bank_statement_lines WHERE id = ? AND org_id = ? AND bank_account_id = ?", (stmt_id, org_id, bank_account_id)).fetchone()
        if stmt is None or stmt["reconcile_status"] != "RECONCILED":
            raise ApiError(404, "RECONCILED_LINE_NOT_FOUND", "Reconciled statement line not found.")
        assert_period_unlocked(conn, org_id, stmt["tx_date"], actor_role)

        if stmt["matched_entity_type"] == "BANK_TRANSACTION" and stmt["matched_entity_id"]:
            btx = conn.execute("SELECT * FROM bank_transactions WHERE id = ? AND status = 'AUTHORISED'", (stmt["matched_entity_id"],)).fetchone()
            if btx:
                assert_period_unlocked(conn, org_id, btx["tx_date"], actor_role)
                _reverse_bank_tx_row(conn, org_id, btx, actor_user_id, f"Remove & Redo {btx['tx_type']}")
                conn.execute(
                    """
                    UPDATE bank_statement_lines
                    SET reconcile_status='UNRECONCILED', matched_entity_type=NULL, matched_entity_id=NULL, matched_entity_ids_json=NULL, reconciled_at=NULL, version=version+1
                    WHERE org_id = ? AND matched_entity_type = 'BANK_TRANSACTION' AND matched_entity_id = ? AND id != ?
                    """,
                    (org_id, btx["id"], stmt_id),
                )
        elif stmt["matched_entity_type"] in ("PAYMENT", "PAYMENT_GROUP"):
            from .documents import delete_payment
            pids, adj_btx_id = _parse_matched_ids(stmt["matched_entity_ids_json"], stmt["matched_entity_id"])
            for pid in pids:
                delete_payment(conn, org_id=org_id, payment_id=pid, actor_user_id=actor_user_id, actor_name=actor_name, actor_role=actor_role)
            if adj_btx_id:
                adj_btx = conn.execute("SELECT * FROM bank_transactions WHERE id = ? AND status = 'AUTHORISED'", (adj_btx_id,)).fetchone()
                if adj_btx:
                    assert_period_unlocked(conn, org_id, adj_btx["tx_date"], actor_role)
                    _reverse_bank_tx_row(conn, org_id, adj_btx, actor_user_id, "Remove & Redo Minor Adjustment")

        conn.execute(
            "UPDATE bank_statement_lines SET reconcile_status='UNRECONCILED', matched_entity_type=NULL, matched_entity_id=NULL, matched_entity_ids_json=NULL, reconciled_at=NULL, version=version+1 WHERE id=?",
            (stmt_id,),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RECONCILIATION", stmt_id, "REMOVE_AND_REDO", "Reversed transaction via append-only journal and reopened statement line.")
    return {"status": "UNRECONCILED"}


def list_bank_transactions(conn: sqlite3.Connection, org_id: str, bank_account_id: str | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT bt.*, c.name AS contact_name, a.name AS bank_account_name, j.journal_number
        FROM bank_transactions bt
        LEFT JOIN contacts c ON c.id = bt.contact_id
        JOIN accounts a ON a.id = bt.bank_account_id
        JOIN journals j ON j.id = bt.journal_id
        WHERE bt.org_id = ?
    """
    params: list[Any] = [org_id]
    if bank_account_id:
        sql += " AND bt.bank_account_id = ?"
        params.append(bank_account_id)
    sql += " ORDER BY bt.tx_date DESC, bt.created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": r["id"],
            "txType": r["tx_type"],
            "bankAccountId": r["bank_account_id"],
            "bankAccountName": r["bank_account_name"],
            "contactName": r["contact_name"],
            "txDate": r["tx_date"],
            "reference": r["reference"],
            "total": decimal_str_from_cents(r["total_cents"]),
            "isReconciled": bool(r["is_reconciled"]),
            "status": r["status"],
            "journalNumber": r["journal_number"],
        }
        for r in rows
    ]


# --- Bank Rules CRUD ---
def list_bank_rules(conn: sqlite3.Connection, org_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM bank_rules WHERE org_id = ? AND status = 'ACTIVE' ORDER BY priority_order, created_at",
        (org_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "ruleType": r["rule_type"],
            "matchStrategy": r["match_strategy"],
            "conditions": json.loads(r["conditions_json"]),
            "contactId": r["contact_id"],
            "targetBankId": r["target_bank_id"],
            "fixedLines": json.loads(r["fixed_lines_json"]),
            "percentLines": json.loads(r["percent_lines_json"]),
            "bankAccountScope": r["bank_account_scope"],
            "priorityOrder": r["priority_order"],
            "status": r["status"],
        }
        for r in rows
    ]


def save_bank_rule(conn: sqlite3.Connection, *, org_id: str, payload: dict[str, Any], rule_id: str | None, actor_user_id: str, actor_name: str, actor_role: str) -> dict[str, Any]:
    assert_can_write(actor_role)
    name = (payload.get("name") or "").strip()
    if not name:
        raise ApiError(422, "RULE_NAME_REQUIRED", "Rule name is required.")
    rule_type = (payload.get("ruleType") or "SPEND").upper()
    pcts = payload.get("percentLines") or []
    if rule_type != "TRANSFER" and pcts:
        total_pct = sum(to_decimal(p.get("percent", "0")) for p in pcts)
        if total_pct != Decimal("100") and total_pct != Decimal("100.00"):
            raise ApiError(422, "PERCENT_TOTAL_NOT_100", f"Remainder percent lines must sum to 100.00% (got {total_pct}%).")

    with atomic_tx(conn):
        rid = rule_id or new_id()
        if rule_id:
            conn.execute(
                """
                UPDATE bank_rules SET name=?, rule_type=?, match_strategy=?, conditions_json=?, contact_id=?, target_bank_id=?,
                fixed_lines_json=?, percent_lines_json=?, bank_account_scope=?, priority_order=? WHERE id=? AND org_id=?
                """,
                (
                    name, rule_type, (payload.get("matchStrategy") or "ALL").upper(),
                    json.dumps(payload.get("conditions", [])), payload.get("contactId"), payload.get("targetBankId"),
                    json.dumps(payload.get("fixedLines", [])), json.dumps(pcts),
                    payload.get("bankAccountScope"), int(payload.get("priorityOrder", 1)), rid, org_id,
                ),
            )
        else:
            next_prio = int(conn.execute("SELECT COALESCE(MAX(priority_order), 0) + 1 FROM bank_rules WHERE org_id=?", (org_id,)).fetchone()[0])
            conn.execute(
                """
                INSERT INTO bank_rules (id, org_id, name, rule_type, match_strategy, conditions_json, contact_id, target_bank_id, fixed_lines_json, percent_lines_json, bank_account_scope, priority_order, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
                """,
                (
                    rid, org_id, name, rule_type, (payload.get("matchStrategy") or "ALL").upper(),
                    json.dumps(payload.get("conditions", [])), payload.get("contactId"), payload.get("targetBankId"),
                    json.dumps(payload.get("fixedLines", [])), json.dumps(pcts),
                    payload.get("bankAccountScope"), int(payload.get("priorityOrder", next_prio)), utc_now_iso(),
                ),
            )
        write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RULE", rid, "SAVED", f"Bank rule '{name}' ({rule_type}) saved.")
    return next(r for r in list_bank_rules(conn, org_id) if r["id"] == rid)


def archive_bank_rule(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    rule_id: str,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> None:
    assert_can_write(actor_role)
    with atomic_tx(conn):
        conn.execute("UPDATE bank_rules SET status = 'ARCHIVED' WHERE id = ? AND org_id = ?", (rule_id, org_id))
        write_audit(conn, org_id, actor_user_id, actor_name, "BANK_RULE", rule_id, "ARCHIVED", "Bank rule archived.")
