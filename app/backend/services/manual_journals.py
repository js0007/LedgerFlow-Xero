"""Manual Journals service: 47-account filter, Draft/Posted/Void/Edit, Tax Exclusive/Inclusive & Auto-Reverse."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from ..db import ApiError, atomic_tx, new_id, utc_now_iso
from ..money import cents_from_value, decimal_str_from_cents, round_cents_decimal, to_decimal
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


def _compute_mj_line_amounts(
    debit_cents: int,
    credit_cents: int,
    rate_decimal: str,
    tax_mode: str,
) -> tuple[int, int, int]:
    """Compute (net_cents, tax_cents, gross_cents) for a single manual journal line."""
    raw_cents = debit_cents if debit_cents > 0 else credit_cents
    rate_d = to_decimal(rate_decimal)
    mode = tax_mode.upper()

    if mode == "NO_TAX" or rate_d == 0:
        return raw_cents, 0, raw_cents

    raw_dollars = to_decimal(raw_cents) / to_decimal(100)
    if mode == "EXCLUSIVE":
        tax_cents = round_cents_decimal(raw_dollars * rate_d)
        return raw_cents, tax_cents, raw_cents + tax_cents

    if mode == "INCLUSIVE":
        tax_cents = round_cents_decimal(raw_dollars * rate_d / (to_decimal(1) + rate_d))
        return raw_cents - tax_cents, tax_cents, raw_cents

    raise ApiError(400, "INVALID_TAX_MODE", f"Unsupported taxMode '{tax_mode}'")


def _prepare_mj_lines(
    conn: sqlite3.Connection,
    org_id: str,
    tax_mode: str,
    raw_lines: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Validate 47-account eligibility, calculate net/tax/gross per line, return (prepared, total_dr_gross, total_cr_gross)."""
    if not raw_lines:
        raise ApiError(422, "MJ_NO_LINES", "At least one line is required.")

    base_excluded_tax = get_tax_rate_by_code(conn, org_id, "BASEXCLUDED")
    prepared: list[dict[str, Any]] = []
    total_debit_gross = 0
    total_credit_gross = 0

    for idx, line in enumerate(raw_lines, start=1):
        account_id = line.get("accountId")
        acc = conn.execute(
            "SELECT * FROM accounts WHERE id = ? AND org_id = ? AND status = 'ACTIVE'",
            (account_id, org_id),
        ).fetchone()
        if acc is None:
            raise ApiError(422, "INVALID_ACCOUNT", f"Line {idx}: active account not found in organisation.")
        if acc["account_type"] == "BANK" or int(acc["manual_journal_excluded"]) == 1:
            raise ApiError(
                422,
                "RESTRICTED_SYSTEM_ACCOUNT",
                f"Line {idx}: Account '{acc['code'] or ''} {acc['name']}' is system-controlled or a bank account and cannot be selected in Manual Journals.",
            )

        debit_cents = cents_from_value(line.get("debit", 0))
        credit_cents = cents_from_value(line.get("credit", 0))
        if debit_cents < 0 or credit_cents < 0 or (debit_cents > 0 and credit_cents > 0):
            raise ApiError(422, "INVALID_LINE_AMOUNTS", f"Line {idx}: specify either Debit or Credit >= 0.")

        if tax_mode == "NO_TAX":
            tax_rate = base_excluded_tax
        else:
            tr_id = line.get("taxRateId") or acc["default_tax_rate_id"] or base_excluded_tax["id"]
            tax_rate = conn.execute(
                "SELECT * FROM tax_rates WHERE id = ? AND org_id = ?",
                (tr_id, org_id),
            ).fetchone()
            if tax_rate is None:
                raise ApiError(422, "INVALID_TAX_RATE", f"Line {idx}: tax rate not found.")

        net_c, tax_c, gross_c = _compute_mj_line_amounts(debit_cents, credit_cents, tax_rate["rate_decimal"], tax_mode)
        if debit_cents > 0:
            total_debit_gross += gross_c
        elif credit_cents > 0:
            total_credit_gross += gross_c

        prepared.append(
            {
                "line_no": idx,
                "description": line.get("description") or "",
                "account_id": acc["id"],
                "tax_rate_id": tax_rate["id"],
                "tax_type_code": tax_rate["code"],
                "debit_cents": debit_cents,
                "credit_cents": credit_cents,
                "net_cents": net_c,
                "tax_cents": tax_c,
                "gross_cents": gross_c,
                "tracking_1_option_id": line.get("tracking1OptionId"),
                "tracking_2_option_id": line.get("tracking2OptionId"),
            }
        )

    return prepared, total_debit_gross, total_credit_gross


def _build_gl_lines_from_mj(
    conn: sqlite3.Connection,
    org_id: str,
    narration: str,
    tax_mode: str,
    prepared: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expand prepared MJ lines into balanced double-entry GL lines including 820 GST when tax_mode != NO_TAX."""
    gl_lines: list[dict[str, Any]] = []
    gst_debit_total = 0
    gst_credit_total = 0

    for p in prepared:
        if p["debit_cents"] == 0 and p["credit_cents"] == 0:
            continue
        is_debit = p["debit_cents"] > 0
        net_val = p["net_cents"]
        s_gross, s_net, s_tax = signed_tax_line_amounts(
            p["tax_type_code"],
            is_credit=not is_debit,
            gross_cents=p["gross_cents"],
            net_cents=net_val,
            tax_cents=p["tax_cents"],
        )

        gl_lines.append(
            {
                "account_id": p["account_id"],
                "description": p["description"] or narration,
                "debit_cents": net_val if is_debit else 0,
                "credit_cents": net_val if not is_debit else 0,
                "tax_rate_id": p["tax_rate_id"],
                "tax_type_code": p["tax_type_code"],
                "gross_cents": s_gross,
                "net_cents": s_net,
                "tax_cents": s_tax,
                "tracking_1_option_id": p["tracking_1_option_id"],
                "tracking_2_option_id": p["tracking_2_option_id"],
            }
        )
        if tax_mode != "NO_TAX" and p["tax_cents"] > 0:
            if is_debit:
                gst_debit_total += p["tax_cents"]
            else:
                gst_credit_total += p["tax_cents"]

    if gst_debit_total > 0 or gst_credit_total > 0:
        gst_acc = get_system_account(conn, org_id, "GST")
        if gst_debit_total > 0:
            gl_lines.append(
                {
                    "account_id": gst_acc["id"],
                    "description": f"GST on Manual Journal: {narration}",
                    "debit_cents": gst_debit_total,
                    "credit_cents": 0,
                }
            )
        if gst_credit_total > 0:
            gl_lines.append(
                {
                    "account_id": gst_acc["id"],
                    "description": f"GST on Manual Journal: {narration}",
                    "debit_cents": 0,
                    "credit_cents": gst_credit_total,
                }
            )
    return gl_lines


def get_manual_journal(conn: sqlite3.Connection, org_id: str, mj_id: str) -> dict[str, Any]:
    mj = conn.execute("SELECT * FROM manual_journals WHERE id = ? AND org_id = ?", (mj_id, org_id)).fetchone()
    if mj is None:
        raise ApiError(404, "MJ_NOT_FOUND", "Manual journal not found.")
    lines = conn.execute(
        """
        SELECT l.*, a.code AS account_code, a.name AS account_name, tr.code AS tax_code, tr.name AS tax_name
        FROM manual_journal_lines l
        JOIN accounts a ON a.id = l.account_id
        JOIN tax_rates tr ON tr.id = l.tax_rate_id
        WHERE l.manual_journal_id = ?
        ORDER BY l.line_no
        """,
        (mj_id,),
    ).fetchall()

    posted_j_num = None
    rev_j_num = None
    if mj["posted_journal_id"]:
        r = conn.execute("SELECT journal_number FROM journals WHERE id = ?", (mj["posted_journal_id"],)).fetchone()
        posted_j_num = r["journal_number"] if r else None
    if mj["reversal_journal_id"]:
        r = conn.execute("SELECT journal_number FROM journals WHERE id = ?", (mj["reversal_journal_id"],)).fetchone()
        rev_j_num = r["journal_number"] if r else None

    total_dr = sum(int(l["gross_cents"]) for l in lines if int(l["debit_cents"]) > 0)
    total_cr = sum(int(l["gross_cents"]) for l in lines if int(l["credit_cents"]) > 0)
    total_tax = sum(int(l["tax_cents"]) for l in lines)
    return {
        "id": mj["id"],
        "orgId": mj["org_id"],
        "narration": mj["narration"],
        "journalDate": mj["journal_date"],
        "autoReversingDate": mj["auto_reversing_date"],
        "taxMode": mj["tax_mode"],
        "showOnCashBasis": bool(mj["show_on_cash_basis"]),
        "status": mj["status"],
        "postedJournalId": mj["posted_journal_id"],
        "postedJournalNumber": posted_j_num,
        "reversalJournalId": mj["reversal_journal_id"],
        "reversalJournalNumber": rev_j_num,
        "totalDebit": decimal_str_from_cents(total_dr),
        "totalCredit": decimal_str_from_cents(total_cr),
        "taxTotal": decimal_str_from_cents(total_tax),
        "version": mj["version"],
        "createdAt": mj["created_at"],
        "updatedAt": mj["updated_at"],
        "lines": [
            {
                "id": l["id"],
                "lineNo": l["line_no"],
                "description": l["description"],
                "accountId": l["account_id"],
                "accountCode": l["account_code"],
                "accountName": l["account_name"],
                "taxRateId": l["tax_rate_id"],
                "taxCode": l["tax_code"],
                "taxName": l["tax_name"],
                "debit": decimal_str_from_cents(l["debit_cents"]),
                "credit": decimal_str_from_cents(l["credit_cents"]),
                "netAmount": decimal_str_from_cents(l["net_cents"]),
                "taxAmount": decimal_str_from_cents(l["tax_cents"]),
                "grossAmount": decimal_str_from_cents(l["gross_cents"]),
                "tracking1OptionId": l["tracking_1_option_id"],
                "tracking2OptionId": l["tracking_2_option_id"],
            }
            for l in lines
        ],
    }


def list_manual_journals(conn: sqlite3.Connection, org_id: str, status: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT id FROM manual_journals WHERE org_id = ?"
    params: list[Any] = [org_id]
    if status and status.upper() != "ALL":
        sql += " AND status = ?"
        params.append(status.upper())
    sql += " ORDER BY journal_date DESC, created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return [get_manual_journal(conn, org_id, r["id"]) for r in rows]


def create_manual_journal(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    payload: dict[str, Any],
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    assert_can_write(actor_role)
    narration = (payload.get("narration") or "").strip()
    if not narration:
        raise ApiError(422, "NARRATION_REQUIRED", "Manual journal narration is required.")
    journal_date = payload.get("journalDate") or date.today().isoformat()
    parse_iso_date(journal_date)
    auto_rev = payload.get("autoReversingDate") or None
    if auto_rev:
        if parse_iso_date(auto_rev) <= parse_iso_date(journal_date):
            raise ApiError(422, "INVALID_REVERSAL_DATE", "Auto-reversing date must be after journal date.")

    tax_mode = (payload.get("taxMode") or payload.get("lineAmountTypes") or "NO_TAX").upper()
    show_on_cash = bool(payload.get("showOnCashBasis", True))
    post_now = bool(payload.get("postImmediately", False))

    prepared, tot_dr, tot_cr = _prepare_mj_lines(conn, org_id, tax_mode, payload.get("lines", []))

    mj_id = new_id()
    now = utc_now_iso()

    with atomic_tx(conn):
        conn.execute(
            """
            INSERT INTO manual_journals (
                id, org_id, narration, journal_date, auto_reversing_date,
                tax_mode, show_on_cash_basis, status, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'DRAFT', 1, ?, ?)
            """,
            (mj_id, org_id, narration, journal_date, auto_rev, tax_mode, 1 if show_on_cash else 0, now, now),
        )
        for p in prepared:
            conn.execute(
                """
                INSERT INTO manual_journal_lines (
                    id, manual_journal_id, line_no, description, account_id, tax_rate_id,
                    debit_cents, credit_cents, net_cents, tax_cents, gross_cents,
                    tracking_1_option_id, tracking_2_option_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    mj_id,
                    p["line_no"],
                    p["description"],
                    p["account_id"],
                    p["tax_rate_id"],
                    p["debit_cents"],
                    p["credit_cents"],
                    p["net_cents"],
                    p["tax_cents"],
                    p["gross_cents"],
                    p["tracking_1_option_id"],
                    p["tracking_2_option_id"],
                ),
            )
        write_audit(conn, org_id, actor_user_id, actor_name, "MANUAL_JOURNAL", mj_id, "CREATED", f"Manual journal '{narration}' saved as draft.")

    if post_now:
        return post_manual_journal(conn, org_id=org_id, mj_id=mj_id, actor_user_id=actor_user_id, actor_name=actor_name, actor_role=actor_role)
    return get_manual_journal(conn, org_id, mj_id)


def post_manual_journal(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    mj_id: str,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    assert_can_write(actor_role)
    mj = conn.execute("SELECT * FROM manual_journals WHERE id = ? AND org_id = ?", (mj_id, org_id)).fetchone()
    if mj is None:
        raise ApiError(404, "MJ_NOT_FOUND", "Manual journal not found.")
    if mj["status"] != "DRAFT":
        raise ApiError(422, "INVALID_STATE", "Only DRAFT manual journals can be posted.")

    assert_period_unlocked(conn, org_id, mj["journal_date"], actor_role)
    if mj["auto_reversing_date"]:
        assert_period_unlocked(conn, org_id, mj["auto_reversing_date"], actor_role)

    lines = conn.execute(
        """
        SELECT l.*, tr.code AS tax_type_code
        FROM manual_journal_lines l
        JOIN tax_rates tr ON tr.id = l.tax_rate_id
        WHERE l.manual_journal_id = ?
        ORDER BY l.line_no
        """,
        (mj_id,),
    ).fetchall()
    prepared = [dict(r) for r in lines]

    gl_lines = _build_gl_lines_from_mj(conn, org_id, mj["narration"], mj["tax_mode"], prepared)
    total_dr = sum(int(l["debit_cents"]) for l in gl_lines)
    total_cr = sum(int(l["credit_cents"]) for l in gl_lines)
    if total_dr != total_cr or total_dr <= 0:
        raise ApiError(
            422,
            "UNBALANCED_JOURNAL",
            f"Total Debits ({decimal_str_from_cents(total_dr)}) must equal Total Credits ({decimal_str_from_cents(total_cr)}) before posting.",
        )

    with atomic_tx(conn):
        posted_jid, posted_jnum = post_journal(
            conn,
            org_id=org_id,
            journal_date=mj["journal_date"],
            source_type="MANJOURNAL",
            source_id=mj_id,
            narration=mj["narration"],
            show_on_cash_basis=bool(mj["show_on_cash_basis"]),
            lines=gl_lines,
            actor_user_id=actor_user_id,
        )

        rev_jid = None
        if mj["auto_reversing_date"]:
            rev_jid, rev_jnum = reverse_journal(
                conn,
                org_id=org_id,
                original_journal_id=posted_jid,
                reversal_date=mj["auto_reversing_date"],
                source_type="MANJOURNAL_REVERSAL",
                source_id=mj_id,
                narration=f"Auto-reversal of: {mj['narration']}",
                show_on_cash_basis=bool(mj["show_on_cash_basis"]),
                actor_user_id=actor_user_id,
            )

        conn.execute(
            """
            UPDATE manual_journals
            SET status = 'POSTED', posted_journal_id = ?, reversal_journal_id = ?, version = version + 1, updated_at = ?
            WHERE id = ?
            """,
            (posted_jid, rev_jid, utc_now_iso(), mj_id),
        )
        msg = f"Manual journal '{mj['narration']}' posted (Journal #{posted_jnum})"
        if rev_jid:
            msg += f" with auto-reversal on {mj['auto_reversing_date']}."
        write_audit(conn, org_id, actor_user_id, actor_name, "MANUAL_JOURNAL", mj_id, "POSTED", msg)

    return get_manual_journal(conn, org_id, mj_id)


def update_manual_journal(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    mj_id: str,
    payload: dict[str, Any],
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Edit Draft directly, OR edit Posted MJ safely via Append-Only Reversal + Repost (matching Xero Actions->Edit)."""
    assert_can_write(actor_role)
    mj = conn.execute("SELECT * FROM manual_journals WHERE id = ? AND org_id = ?", (mj_id, org_id)).fetchone()
    if mj is None:
        raise ApiError(404, "MJ_NOT_FOUND", "Manual journal not found.")
    if mj["status"] not in ("DRAFT", "POSTED"):
        raise ApiError(422, "INVALID_STATE", f"Cannot edit manual journal in status {mj['status']}.")

    narration = (payload.get("narration") or mj["narration"]).strip()
    journal_date = payload.get("journalDate") or mj["journal_date"]
    auto_rev = payload.get("autoReversingDate", mj["auto_reversing_date"])
    tax_mode = (payload.get("taxMode") or mj["tax_mode"]).upper()
    show_on_cash = bool(payload.get("showOnCashBasis", bool(mj["show_on_cash_basis"])))

    if mj["status"] == "POSTED":
        assert_period_unlocked(conn, org_id, mj["journal_date"], actor_role)
        assert_period_unlocked(conn, org_id, journal_date, actor_role)

    prepared, _, _ = _prepare_mj_lines(conn, org_id, tax_mode, payload.get("lines", []))
    now = utc_now_iso()

    with atomic_tx(conn):
        # If editing a Posted manual journal, append reversals for existing immutable journal(s) first!
        new_posted_jid = None
        new_rev_jid = None
        if mj["status"] == "POSTED":
            if mj["reversal_journal_id"]:
                reverse_journal(
                    conn,
                    org_id=org_id,
                    original_journal_id=mj["reversal_journal_id"],
                    reversal_date=mj["auto_reversing_date"] or journal_date,
                    source_type="MANJOURNAL_REVERSAL",
                    source_id=mj_id,
                    narration=f"Edit undo auto-reversal: {mj['narration']}",
                    actor_user_id=actor_user_id,
                )
            reverse_journal(
                conn,
                org_id=org_id,
                original_journal_id=mj["posted_journal_id"],
                reversal_date=mj["journal_date"],
                source_type="MANJOURNAL_REVERSAL",
                source_id=mj_id,
                narration=f"Edit reversal of: {mj['narration']}",
                actor_user_id=actor_user_id,
            )

        conn.execute("DELETE FROM manual_journal_lines WHERE manual_journal_id = ?", (mj_id,))
        for p in prepared:
            conn.execute(
                """
                INSERT INTO manual_journal_lines (
                    id, manual_journal_id, line_no, description, account_id, tax_rate_id,
                    debit_cents, credit_cents, net_cents, tax_cents, gross_cents,
                    tracking_1_option_id, tracking_2_option_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    mj_id,
                    p["line_no"],
                    p["description"],
                    p["account_id"],
                    p["tax_rate_id"],
                    p["debit_cents"],
                    p["credit_cents"],
                    p["net_cents"],
                    p["tax_cents"],
                    p["gross_cents"],
                    p["tracking_1_option_id"],
                    p["tracking_2_option_id"],
                ),
            )

        if mj["status"] == "POSTED":
            gl_lines = _build_gl_lines_from_mj(conn, org_id, narration, tax_mode, prepared)
            new_posted_jid, new_jnum = post_journal(
                conn,
                org_id=org_id,
                journal_date=journal_date,
                source_type="MANJOURNAL",
                source_id=mj_id,
                narration=narration,
                show_on_cash_basis=show_on_cash,
                lines=gl_lines,
                actor_user_id=actor_user_id,
            )
            if auto_rev:
                new_rev_jid, _ = reverse_journal(
                    conn,
                    org_id=org_id,
                    original_journal_id=new_posted_jid,
                    reversal_date=auto_rev,
                    source_type="MANJOURNAL_REVERSAL",
                    source_id=mj_id,
                    narration=f"Auto-reversal of: {narration}",
                    show_on_cash_basis=show_on_cash,
                    actor_user_id=actor_user_id,
                )

        conn.execute(
            """
            UPDATE manual_journals
            SET narration = ?, journal_date = ?, auto_reversing_date = ?, tax_mode = ?,
                show_on_cash_basis = ?, posted_journal_id = COALESCE(?, posted_journal_id),
                reversal_journal_id = ?, version = version + 1, updated_at = ?
            WHERE id = ?
            """,
            (
                narration,
                journal_date,
                auto_rev,
                tax_mode,
                1 if show_on_cash else 0,
                new_posted_jid,
                new_rev_jid if mj["status"] == "POSTED" else None,
                now,
                mj_id,
            ),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "MANUAL_JOURNAL", mj_id, "EDITED", f"Manual journal '{narration}' updated.")

    return get_manual_journal(conn, org_id, mj_id)


def void_manual_journal(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    mj_id: str,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Void a Posted or Draft Manual Journal safely via Append-Only Reversal."""
    assert_can_write(actor_role)
    mj = conn.execute("SELECT * FROM manual_journals WHERE id = ? AND org_id = ?", (mj_id, org_id)).fetchone()
    if mj is None:
        raise ApiError(404, "MJ_NOT_FOUND", "Manual journal not found.")
    if mj["status"] == "VOIDED":
        return get_manual_journal(conn, org_id, mj_id)

    with atomic_tx(conn):
        rev_jid = mj["reversal_journal_id"]
        if mj["status"] == "POSTED":
            assert_period_unlocked(conn, org_id, mj["journal_date"], actor_role)
            if mj["reversal_journal_id"]:
                # Undo the scheduled auto-reversal first so net across both dates becomes 0
                assert_period_unlocked(conn, org_id, mj["auto_reversing_date"], actor_role)
                reverse_journal(
                    conn,
                    org_id=org_id,
                    original_journal_id=mj["reversal_journal_id"],
                    reversal_date=mj["auto_reversing_date"],
                    source_type="MANJOURNAL_REVERSAL",
                    source_id=mj_id,
                    narration=f"Void auto-reversal of: {mj['narration']}",
                    actor_user_id=actor_user_id,
                )
            rev_jid, _ = reverse_journal(
                conn,
                org_id=org_id,
                original_journal_id=mj["posted_journal_id"],
                reversal_date=mj["journal_date"],
                source_type="MANJOURNAL_REVERSAL",
                source_id=mj_id,
                narration=f"Void manual journal: {mj['narration']}",
                actor_user_id=actor_user_id,
            )

        conn.execute(
            "UPDATE manual_journals SET status = 'VOIDED', reversal_journal_id = ?, version = version + 1, updated_at = ? WHERE id = ?",
            (rev_jid, utc_now_iso(), mj_id),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "MANUAL_JOURNAL", mj_id, "VOIDED", f"Manual journal '{mj['narration']}' voided.")
    return get_manual_journal(conn, org_id, mj_id)
