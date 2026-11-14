"""AU Simpler BAS Service: Accrual & Cash BAS (G1/1A/1B/8A/8B/9), Finalise Watermark & Unfiled Amounts."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..db import ApiError, atomic_tx, new_id, utc_now_iso
from ..money import decimal_str_from_cents, whole_dollars_from_cents
from .ledger import assert_can_write, parse_iso_date, write_audit

OUTPUT_TYPES = {"OUTPUT", "EXEMPTOUTPUT", "EXEMPTEXPORT"}
GST_SALES_TYPES = {"OUTPUT"}
GST_PURCHASE_TYPES = {"INPUT", "GSTONIMPORTS", "CAPEXINPUT", "GSTONCAPIMPORTS"}
CAPITAL_PURCHASE_TYPES = {"CAPEXINPUT", "EXEMPTCAPITAL", "GSTONCAPIMPORTS"}
NON_CAPITAL_PURCHASE_TYPES = {"INPUT", "EXEMPTEXPENSES", "GSTONIMPORTS"}


def _allocate_cash_invoice_bas(
    conn: sqlite3.Connection,
    invoice_id: str,
    cash_amount_cents: int,
    sign: int,
) -> list[dict[str, Any]]:
    """Pro-rate an Invoice/Bill/CreditNote's lines by (cash_amount / total) cleanly preserving exact cents."""
    inv = conn.execute("SELECT id, total_cents, invoice_type, invoice_number FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if inv is None or int(inv["total_cents"]) == 0:
        return []
    lines = conn.execute(
        "SELECT l.*, tr.code AS tax_type_code, tr.name AS tax_name FROM invoice_lines l JOIN tax_rates tr ON tr.id = l.tax_rate_id WHERE l.invoice_id = ? ORDER BY l.line_no",
        (invoice_id,),
    ).fetchall()
    ratio = Decimal(cash_amount_cents) / Decimal(int(inv["total_cents"]))
    contributions = []
    for l in lines:
        net_c = int((Decimal(int(l["net_cents"])) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * sign
        tax_c = int((Decimal(int(l["tax_cents"])) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * sign
        gross_c = int((Decimal(int(l["gross_cents"])) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) * sign
        contributions.append(
            {
                "taxTypeCode": l["tax_type_code"],
                "taxName": l["tax_name"],
                "description": f"{inv['invoice_number']} — {l['description']}",
                "netCents": net_c,
                "taxCents": tax_c,
                "grossCents": gross_c,
                "sourceType": inv["invoice_type"],
            }
        )
    return contributions


def _gather_period_tax_rows(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    period_start: str,
    period_end: str,
    method: str,
    min_journal_number: int | None = None,
    prior_filed_alloc_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Gather tax contributions for [period_start, period_end] (or unfiled backdated rows if min_journal_number is set)."""
    max_j_row = conn.execute("SELECT COALESCE(MAX(journal_number), 0) FROM journals WHERE org_id = ?", (org_id,)).fetchone()
    max_jnum = int(max_j_row[0])

    rows: list[dict[str, Any]] = []
    alloc_ids: list[str] = []
    if method == "ACCRUAL":
        sql = """
            SELECT jl.*, j.journal_number, j.journal_date, j.source_type, j.reference, tr.name AS tax_name
            FROM journal_lines jl
            JOIN journals j ON j.id = jl.journal_id
            LEFT JOIN tax_rates tr ON tr.id = jl.tax_rate_id
            WHERE j.org_id = ? AND jl.tax_type_code IS NOT NULL
        """
        params: list[Any] = [org_id]
        if min_journal_number is not None:
            sql += " AND j.journal_date < ? AND j.journal_number > ?"
            params.extend([period_start, min_journal_number])
        else:
            sql += " AND j.journal_date BETWEEN ? AND ?"
            params.extend([period_start, period_end])

        for r in conn.execute(sql, params).fetchall():
            rows.append(
                {
                    "date": r["journal_date"],
                    "journalNumber": r["journal_number"],
                    "sourceType": r["source_type"],
                    "reference": r["reference"],
                    "description": r["description"],
                    "taxTypeCode": r["tax_type_code"],
                    "taxName": r["tax_name"] or r["tax_type_code"],
                    "netCents": int(r["net_cents"]),
                    "taxCents": int(r["tax_cents"]),
                    "grossCents": int(r["gross_cents"]),
                }
            )
    else:
        # CASH BASIS (E35/E36 empirically verified):
        # 1. Authorised Payments within date window (excludes deleted & pre-allocations; reversals negate naturally)
        pay_sql = """
            SELECT p.*, i.invoice_type, i.invoice_number, j.journal_number
            FROM payments p
            JOIN invoices i ON i.id = p.invoice_id
            JOIN journals j ON j.id = p.journal_id
            WHERE p.org_id = ? AND p.status = 'AUTHORISED'
        """
        pay_params: list[Any] = [org_id]
        if min_journal_number is not None:
            pay_sql += " AND p.payment_date < ? AND j.journal_number > ?"
            pay_params.extend([period_start, min_journal_number])
        else:
            pay_sql += " AND p.payment_date BETWEEN ? AND ?"
            pay_params.extend([period_start, period_end])

        for p in conn.execute(pay_sql, pay_params).fetchall():
            # Credit Note cash refunds reduce GST sales/credits on Cash BAS (sign=-1)
            pay_sign = -1 if p["invoice_type"] in ("ACCRECCREDIT", "ACCPAYCREDIT") else 1
            for c in _allocate_cash_invoice_bas(conn, p["invoice_id"], int(p["amount_cents"]), sign=pay_sign):
                c["date"] = p["payment_date"]
                c["journalNumber"] = p["journal_number"]
                c["reference"] = p["reference"] or p["invoice_number"]
                rows.append(c)

        # 2. Credit Note Allocations within date window (or unfiled backdated allocations since last finalised BAS)
        alloc_sql = """
            SELECT ca.*, cn.invoice_number AS cn_number, tgt.invoice_number AS tgt_number
            FROM credit_note_allocations ca
            JOIN invoices cn ON cn.id = ca.credit_note_id
            JOIN invoices tgt ON tgt.id = ca.target_invoice_id
            WHERE ca.org_id = ? AND ca.status = 'ACTIVE'
        """
        alloc_params: list[Any] = [org_id]
        if min_journal_number is not None:
            alloc_sql += " AND ca.allocation_date < ?"
            alloc_params.append(period_start)
        else:
            alloc_sql += " AND ca.allocation_date BETWEEN ? AND ?"
            alloc_params.extend([period_start, period_end])

        filed_set = prior_filed_alloc_ids or set()
        for a in conn.execute(alloc_sql, alloc_params).fetchall():
            if min_journal_number is not None and a["id"] in filed_set:
                continue
            alloc_ids.append(a["id"])
            for c in _allocate_cash_invoice_bas(conn, a["credit_note_id"], int(a["amount_cents"]), sign=-1):
                c["date"] = a["allocation_date"]
                c["reference"] = a["cn_number"]
                rows.append(c)
            for c in _allocate_cash_invoice_bas(conn, a["target_invoice_id"], int(a["amount_cents"]), sign=1):
                c["date"] = a["allocation_date"]
                c["reference"] = a["tgt_number"]
                rows.append(c)

        # 3. Direct BankTransactions (CASHREC / CASHPAID) + Taxed Manual Journals with show_on_cash_basis=1
        direct_sql = """
            SELECT jl.*, j.journal_number, j.journal_date, j.source_type, j.reference, tr.name AS tax_name
            FROM journal_lines jl
            JOIN journals j ON j.id = jl.journal_id
            LEFT JOIN tax_rates tr ON tr.id = jl.tax_rate_id
            WHERE j.org_id = ? AND jl.tax_type_code IS NOT NULL
              AND j.source_type IN ('CASHREC', 'CASHREC_REVERSAL', 'CASHPAID', 'CASHPAID_REVERSAL', 'MANJOURNAL', 'MANJOURNAL_REVERSAL')
              AND j.show_on_cash_basis = 1
        """
        direct_params: list[Any] = [org_id]
        if min_journal_number is not None:
            direct_sql += " AND j.journal_date < ? AND j.journal_number > ?"
            direct_params.extend([period_start, min_journal_number])
        else:
            direct_sql += " AND j.journal_date BETWEEN ? AND ?"
            direct_params.extend([period_start, period_end])

        for r in conn.execute(direct_sql, direct_params).fetchall():
            rows.append(
                {
                    "date": r["journal_date"],
                    "journalNumber": r["journal_number"],
                    "sourceType": r["source_type"],
                    "reference": r["reference"],
                    "description": r["description"],
                    "taxTypeCode": r["tax_type_code"],
                    "taxName": r["tax_name"] or r["tax_type_code"],
                    "netCents": int(r["net_cents"]),
                    "taxCents": int(r["tax_cents"]),
                    "grossCents": int(r["gross_cents"]),
                }
            )

    return rows, max_jnum, alloc_ids


def _aggregate_bas_boxes(rows: list[dict[str, Any]], g1_mode: str) -> dict[str, Any]:
    g1_cents = 0
    g10_cents = 0
    g11_cents = 0
    box_1a_cents = 0
    box_1b_cents = 0
    by_tax_rate: dict[str, dict[str, Any]] = defaultdict(lambda: {"taxCode": "", "taxName": "", "netCents": 0, "taxCents": 0, "grossCents": 0, "count": 0})

    for r in rows:
        code = r["taxTypeCode"]
        if code in OUTPUT_TYPES:
            g1_cents += r["grossCents"] if g1_mode == "INCLUSIVE" else r["netCents"]
        if code in CAPITAL_PURCHASE_TYPES:
            g10_cents += r["grossCents"] if g1_mode == "INCLUSIVE" else r["netCents"]
        if code in NON_CAPITAL_PURCHASE_TYPES:
            g11_cents += r["grossCents"] if g1_mode == "INCLUSIVE" else r["netCents"]
        if code in GST_SALES_TYPES:
            box_1a_cents += r["taxCents"]
        if code in GST_PURCHASE_TYPES:
            box_1b_cents += r["taxCents"]

        grp = by_tax_rate[code]
        grp["taxCode"] = code
        grp["taxName"] = r["taxName"]
        grp["netCents"] += r["netCents"]
        grp["taxCents"] += r["taxCents"]
        grp["grossCents"] += r["grossCents"]
        grp["count"] += 1

    g1_d = whole_dollars_from_cents(g1_cents)
    g10_d = whole_dollars_from_cents(g10_cents)
    g11_d = whole_dollars_from_cents(g11_cents)
    a1_d = whole_dollars_from_cents(box_1a_cents)
    b1_d = whole_dollars_from_cents(box_1b_cents)
    pay9_d = a1_d - b1_d
    return {
        "exactCents": {"G1": g1_cents, "G10": g10_cents, "G11": g11_cents, "1A": box_1a_cents, "1B": box_1b_cents},
        "labels": {
            "G1": str(g1_d),
            "G10": str(g10_d),
            "G11": str(g11_d),
            "1A": str(a1_d),
            "1B": str(b1_d),
            "8A": str(a1_d),
            "8B": str(b1_d),
            "Payment9": str(pay9_d),
        },
        "byTaxRate": [
            {
                "taxCode": v["taxCode"],
                "taxName": v["taxName"],
                "netAmount": decimal_str_from_cents(v["netCents"]),
                "taxAmount": decimal_str_from_cents(v["taxCents"]),
                "grossAmount": decimal_str_from_cents(v["grossCents"]),
                "count": v["count"],
            }
            for v in by_tax_rate.values()
        ],
    }


def compute_bas_statement(conn: sqlite3.Connection, *, org_id: str, period_start: str, period_end: str) -> dict[str, Any]:
    parse_iso_date(period_start)
    parse_iso_date(period_end)
    settings = conn.execute("SELECT gst_accounting_method, bas_g1_mode FROM org_settings WHERE org_id = ?", (org_id,)).fetchone()
    method = settings["gst_accounting_method"]
    g1_mode = settings["bas_g1_mode"]

    existing = conn.execute(
        "SELECT * FROM bas_statements WHERE org_id = ? AND period_start = ? AND period_end = ? AND status = 'FINALISED'",
        (org_id, period_start, period_end),
    ).fetchone()
    if existing:
        snap = json.loads(existing["snapshot_json"])
        snap["status"] = "FINALISED"
        snap["finalisedAt"] = existing["finalised_at"]
        return snap

    # Find highest finalised max_journal_number & already-filed Cash CN allocation IDs prior to period_start
    prior_rows = conn.execute(
        "SELECT max_journal_number, snapshot_json FROM bas_statements WHERE org_id = ? AND status = 'FINALISED' AND period_end < ?",
        (org_id, period_start),
    ).fetchall()
    prev_watermarks = [int(r["max_journal_number"]) for r in prior_rows if r["max_journal_number"] is not None]
    prev_watermark = max(prev_watermarks) if prev_watermarks else None
    prior_filed_alloc_ids: set[str] = set()
    for pr in prior_rows:
        try:
            psnap = json.loads(pr["snapshot_json"] or "{}")
            prior_filed_alloc_ids.update(psnap.get("filedAllocationIds") or [])
        except Exception:
            pass

    period_rows, max_jnum, period_alloc_ids = _gather_period_tax_rows(
        conn, org_id=org_id, period_start=period_start, period_end=period_end, method=method
    )
    unfiled_rows: list[dict[str, Any]] = []
    unfiled_alloc_ids: list[str] = []
    if prev_watermark is not None or prior_rows:
        unfiled_rows, _, unfiled_alloc_ids = _gather_period_tax_rows(
            conn,
            org_id=org_id,
            period_start=period_start,
            period_end=period_end,
            method=method,
            min_journal_number=prev_watermark if prev_watermark is not None else 0,
            prior_filed_alloc_ids=prior_filed_alloc_ids,
        )

    combined = _aggregate_bas_boxes(period_rows + unfiled_rows, g1_mode)
    jnums = [r["journalNumber"] for r in period_rows + unfiled_rows if r.get("journalNumber")]

    return {
        "orgId": org_id,
        "periodStart": period_start,
        "periodEnd": period_end,
        "accountingMethod": method,
        "g1Mode": g1_mode,
        "status": "DRAFT",
        "minJournalNumber": min(jnums) if jnums else None,
        "maxJournalNumber": max_jnum,
        "previousWatermark": prev_watermark,
        "unfiledIncludedCount": len(unfiled_rows),
        "filedAllocationIds": sorted(set(period_alloc_ids + unfiled_alloc_ids + list(prior_filed_alloc_ids))),
        "labels": combined["labels"],
        "byTaxRate": combined["byTaxRate"],
        "transactions": [
            {
                "date": r["date"],
                "journalNumber": r.get("journalNumber"),
                "sourceType": r["sourceType"],
                "reference": r.get("reference"),
                "description": r.get("description"),
                "taxCode": r["taxTypeCode"],
                "taxName": r["taxName"],
                "netAmount": decimal_str_from_cents(r["netCents"]),
                "taxAmount": decimal_str_from_cents(r["taxCents"]),
                "grossAmount": decimal_str_from_cents(r["grossCents"]),
                "isUnfiledPriorPeriod": r in unfiled_rows,
            }
            for r in (period_rows + unfiled_rows)
        ],
    }


def finalise_bas_statement(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    period_start: str,
    period_end: str,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    assert_can_write(actor_role)
    bas_data = compute_bas_statement(conn, org_id=org_id, period_start=period_start, period_end=period_end)
    if bas_data["status"] == "FINALISED":
        return bas_data

    now = utc_now_iso()
    labels = bas_data["labels"]
    bas_id = new_id()
    bas_data["status"] = "FINALISED"
    bas_data["finalisedAt"] = now

    with atomic_tx(conn):
        conn.execute(
            """
            INSERT INTO bas_statements (
                id, org_id, period_start, period_end, accounting_method, g1_mode,
                min_journal_number, max_journal_number,
                g1_total_sales_dollars, gst_1a_sales_dollars, gst_1b_purchases_dollars,
                adjustment_1a_dollars, adjustment_1b_dollars, net_payment_9_dollars,
                unfiled_included_count, status, snapshot_json, finalised_by, finalised_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, 'FINALISED', ?, ?, ?)
            """,
            (
                bas_id, org_id, period_start, period_end, bas_data["accountingMethod"], bas_data["g1Mode"],
                bas_data["minJournalNumber"], bas_data["maxJournalNumber"],
                int(labels["G1"]), int(labels["1A"]), int(labels["1B"]),
                int(labels["Payment9"]), bas_data["unfiledIncludedCount"],
                json.dumps(bas_data, ensure_ascii=False), actor_user_id, now,
            ),
        )
        write_audit(
            conn, org_id, actor_user_id, actor_name, "BAS_STATEMENT", bas_id, "FINALISED",
            f"Finalised AU Simpler BAS {period_start}..{period_end} (Payment 9=${labels['Payment9']}, Watermark J#{bas_data['maxJournalNumber']}).",
        )
    return bas_data


def list_bas_history(conn: sqlite3.Connection, org_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, period_start, period_end, accounting_method, g1_mode, max_journal_number, g1_total_sales_dollars, gst_1a_sales_dollars, gst_1b_purchases_dollars, net_payment_9_dollars, unfiled_included_count, status, finalised_at FROM bas_statements WHERE org_id = ? ORDER BY period_start DESC",
        (org_id,),
    ).fetchall()
    return [dict(r) for r in rows]
