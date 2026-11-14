"""Append-Only General Ledger kernel, Lock Dates guard, FY date math & Audit logging."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any, Iterable

from ..db import ApiError, new_id, utc_now_iso


def parse_iso_date(date_str: str) -> date:
    try:
        return date.fromisoformat(date_str)
    except Exception as exc:
        raise ApiError(400, "INVALID_DATE", f"Invalid ISO date '{date_str}', expected YYYY-MM-DD") from exc


def fiscal_year_start(as_of: date, fy_end_month: int, fy_end_day: int) -> date:
    """Compute the inclusive start date of the AU/configured fiscal year containing `as_of`."""
    # Example AU default: fy_end_month=6, fy_end_day=30.
    # For 2026-06-30 -> FY ends 2026-06-30 -> FY started 2025-07-01.
    # For 2026-07-01 -> FY ends 2027-06-30 -> FY started 2026-07-01.
    try:
        fy_end_this_year = date(as_of.year, fy_end_month, fy_end_day)
    except ValueError:
        # Handle Feb 29 on non-leap years cleanly by falling back to Feb 28
        fy_end_this_year = date(as_of.year, fy_end_month, 28)

    if as_of <= fy_end_this_year:
        prev_year = as_of.year - 1
        try:
            prev_fy_end = date(prev_year, fy_end_month, fy_end_day)
        except ValueError:
            prev_fy_end = date(prev_year, fy_end_month, 28)
        return prev_fy_end + timedelta(days=1)

    return fy_end_this_year + timedelta(days=1)


def assert_period_unlocked(
    conn: sqlite3.Connection,
    org_id: str,
    tx_date_str: str,
    actor_role: str,
) -> None:
    """Enforce Two-Tier Lock Dates (Soft Lock vs Hard Lock)."""
    tx_date = parse_iso_date(tx_date_str)
    settings = conn.execute(
        "SELECT soft_lock_date, hard_lock_date FROM org_settings WHERE org_id = ?",
        (org_id,),
    ).fetchone()
    if settings is None:
        return

    hard_lock = settings["hard_lock_date"]
    soft_lock = settings["soft_lock_date"]
    if hard_lock and tx_date <= parse_iso_date(hard_lock):
        raise ApiError(
            422,
            "PERIOD_HARD_LOCKED",
            f"The document date cannot be on or before the hard lock date ({hard_lock}).",
            {"lockType": "HARD", "lockDate": hard_lock, "txDate": tx_date_str},
        )

    if soft_lock and tx_date <= parse_iso_date(soft_lock) and actor_role.upper() != "ADVISER":
        raise ApiError(
            422,
            "PERIOD_SOFT_LOCKED",
            f"The document date is on or before the adviser lock date ({soft_lock}). Only Advisers can post in this period.",
            {"lockType": "SOFT", "lockDate": soft_lock, "txDate": tx_date_str, "role": actor_role},
        )


def assert_can_write(actor_role: str) -> None:
    if actor_role.upper() == "READONLY":
        raise ApiError(403, "FORBIDDEN_READONLY", "Read-only users cannot create or modify accounting records.")


def write_audit(
    conn: sqlite3.Connection,
    org_id: str,
    actor_user_id: str,
    actor_name: str,
    entity_type: str,
    entity_id: str,
    action: str,
    summary: str,
    diff: Any = None,
    correlation_id: str | None = None,
) -> str:
    audit_id = new_id()
    conn.execute(
        """
        INSERT INTO audit_logs (id, org_id, actor_user_id, actor_name, entity_type, entity_id, action, summary, diff_json, correlation_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            org_id,
            actor_user_id,
            actor_name,
            entity_type,
            entity_id,
            action,
            summary,
            json.dumps(diff, ensure_ascii=False) if diff is not None else None,
            correlation_id or new_id(),
            utc_now_iso(),
        ),
    )
    return audit_id


def get_system_account(conn: sqlite3.Connection, org_id: str, system_code: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM accounts WHERE org_id = ? AND system_account = ? LIMIT 1",
        (org_id, system_code),
    ).fetchone()
    if row is None:
        raise ApiError(500, "MISSING_SYSTEM_ACCOUNT", f"System account '{system_code}' not configured for org.")
    return row


def get_tax_rate_by_code(conn: sqlite3.Connection, org_id: str, code: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM tax_rates WHERE org_id = ? AND code = ? LIMIT 1",
        (org_id, code),
    ).fetchone()
    if row is None:
        raise ApiError(400, "INVALID_TAX_RATE", f"Tax rate '{code}' not found for org.")
    return row


def next_journal_number(conn: sqlite3.Connection, org_id: str) -> int:
    row = conn.execute(
        "SELECT next_journal_number FROM org_counters WHERE org_id = ?",
        (org_id,),
    ).fetchone()
    if row is None:
        raise ApiError(500, "COUNTER_MISSING", "Journal counter missing for organisation.")
    num = int(row["next_journal_number"])
    conn.execute(
        "UPDATE org_counters SET next_journal_number = ? WHERE org_id = ?",
        (num + 1, org_id),
    )
    return num


def post_journal(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    journal_date: str,
    source_type: str,
    source_id: str,
    lines: Iterable[dict[str, Any]],
    actor_user_id: str,
    reference: str | None = None,
    narration: str | None = None,
    reversal_of_journal_id: str | None = None,
    show_on_cash_basis: bool = True,
    correlation_id: str | None = None,
) -> tuple[str, int]:
    """Validate double-entry balance and append an immutable journal + lines."""
    parse_iso_date(journal_date)
    line_list = [l for l in lines if int(l.get("debit_cents", 0)) > 0 or int(l.get("credit_cents", 0)) > 0]
    if len(line_list) < 2:
        raise ApiError(422, "JOURNAL_TOO_FEW_LINES", "A journal entry requires at least two non-zero lines.")

    total_debit = 0
    total_credit = 0
    for idx, line in enumerate(line_list, start=1):
        d = int(line.get("debit_cents", 0))
        c = int(line.get("credit_cents", 0))
        if d < 0 or c < 0 or (d > 0 and c > 0) or (d == 0 and c == 0):
            raise ApiError(422, "INVALID_JOURNAL_LINE", f"Line {idx} must have strictly positive debit OR credit.")
        total_debit += d
        total_credit += c

    if total_debit != total_credit or total_debit <= 0:
        raise ApiError(
            422,
            "UNBALANCED_JOURNAL",
            f"Total Debits ({total_debit}) must equal Total Credits ({total_credit}) and be positive.",
        )

    journal_id = new_id()
    j_num = next_journal_number(conn, org_id)
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO journals (
            id, org_id, journal_number, journal_date, source_type, source_id,
            reference, narration, reversal_of_journal_id, show_on_cash_basis,
            correlation_id, posted_by, posted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            journal_id,
            org_id,
            j_num,
            journal_date,
            source_type,
            source_id,
            reference,
            narration,
            reversal_of_journal_id,
            1 if show_on_cash_basis else 0,
            correlation_id or new_id(),
            actor_user_id,
            now,
        ),
    )

    for idx, line in enumerate(line_list, start=1):
        conn.execute(
            """
            INSERT INTO journal_lines (
                id, org_id, journal_id, line_no, account_id, contact_id, description,
                debit_cents, credit_cents, tax_rate_id, tax_type_code,
                gross_cents, net_cents, tax_cents, tracking_1_option_id, tracking_2_option_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                org_id,
                journal_id,
                idx,
                line["account_id"],
                line.get("contact_id"),
                line.get("description"),
                int(line.get("debit_cents", 0)),
                int(line.get("credit_cents", 0)),
                line.get("tax_rate_id"),
                line.get("tax_type_code"),
                int(line.get("gross_cents", 0)),
                int(line.get("net_cents", 0)),
                int(line.get("tax_cents", 0)),
                line.get("tracking_1_option_id"),
                line.get("tracking_2_option_id"),
            ),
        )
    return journal_id, j_num


def reverse_journal(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    original_journal_id: str,
    reversal_date: str,
    source_type: str,
    source_id: str,
    actor_user_id: str,
    narration: str | None = None,
    reference: str | None = None,
    show_on_cash_basis: bool | None = None,
) -> tuple[str, int]:
    """Create an exact opposing immutable reversal journal for `original_journal_id`."""
    orig_j = conn.execute(
        "SELECT * FROM journals WHERE id = ? AND org_id = ?",
        (original_journal_id, org_id),
    ).fetchone()
    if orig_j is None:
        raise ApiError(404, "JOURNAL_NOT_FOUND", "Original journal not found for reversal.")

    orig_lines = conn.execute(
        "SELECT * FROM journal_lines WHERE journal_id = ? AND org_id = ? ORDER BY line_no",
        (original_journal_id, org_id),
    ).fetchall()

    rev_lines = []
    for ol in orig_lines:
        rev_lines.append(
            {
                "account_id": ol["account_id"],
                "contact_id": ol["contact_id"],
                "description": ol["description"],
                "debit_cents": int(ol["credit_cents"]),
                "credit_cents": int(ol["debit_cents"]),
                "tax_rate_id": ol["tax_rate_id"],
                "tax_type_code": ol["tax_type_code"],
                "gross_cents": -int(ol["gross_cents"]),
                "net_cents": -int(ol["net_cents"]),
                "tax_cents": -int(ol["tax_cents"]),
                "tracking_1_option_id": ol["tracking_1_option_id"],
                "tracking_2_option_id": ol["tracking_2_option_id"],
            }
        )

    cash_flag = bool(orig_j["show_on_cash_basis"]) if show_on_cash_basis is None else show_on_cash_basis
    return post_journal(
        conn,
        org_id=org_id,
        journal_date=reversal_date,
        source_type=source_type,
        source_id=source_id,
        reference=reference if reference is not None else orig_j["reference"],
        narration=narration or f"Reversal of Journal #{orig_j['journal_number']}: {orig_j['narration'] or ''}",
        reversal_of_journal_id=original_journal_id,
        show_on_cash_basis=cash_flag,
        lines=rev_lines,
        actor_user_id=actor_user_id,
    )
