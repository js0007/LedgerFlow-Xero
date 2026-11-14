"""Financial Reports, Aged AR/AP, Cash Flow Analytics, Conversion Balances, Find & Recode & Assurance."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..db import ApiError, atomic_tx, new_id, utc_now_iso
from ..money import cents_from_value, decimal_str_from_cents
from .ledger import (
    assert_can_write,
    assert_period_unlocked,
    fiscal_year_start,
    get_system_account,
    parse_iso_date,
    post_journal,
    reverse_journal,
    write_audit,
)

PNL_CLASSES = {"REVENUE", "EXPENSE"}


def _account_natural_debit(acc_class: str) -> bool:
    return acc_class in ("ASSET", "EXPENSE")


def _signed_balance_for_class(acc_class: str, net_debit_cents: int) -> int:
    """Return natural positive balance: Assets/Expenses = Dr - Cr; Liabilities/Equity/Revenue = Cr - Dr."""
    return net_debit_cents if _account_natural_debit(acc_class) else -net_debit_cents


# -----------------------------------------------------------------------------
# 1. Profit & Loss (Accrual & Cash)
# -----------------------------------------------------------------------------
def _pnl_cash_movements(conn: sqlite3.Connection, org_id: str, from_date: str, to_date: str, tracking_option_id: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def _prorate_invoice_doc(inv_id: str, cash_cents: int, sign: int) -> None:
        inv = conn.execute("SELECT total_cents, invoice_type FROM invoices WHERE id = ?", (inv_id,)).fetchone()
        if inv is None or int(inv["total_cents"]) == 0:
            return
        lines = conn.execute(
            """
            SELECT l.*, a.account_class, a.account_type, a.code AS acc_code, a.name AS acc_name
            FROM invoice_lines l JOIN accounts a ON a.id = l.account_id
            WHERE l.invoice_id = ?
            """,
            (inv_id,),
        ).fetchall()
        ratio = Decimal(cash_cents) / Decimal(int(inv["total_cents"]))
        doc_dir = -1 if inv["invoice_type"] in ("ACCPAY", "ACCRECCREDIT") else 1
        for l in lines:
            if tracking_option_id and l["tracking_1_option_id"] != tracking_option_id and l["tracking_2_option_id"] != tracking_option_id:
                continue
            if l["account_class"] not in PNL_CLASSES:
                continue
            net_c = int((Decimal(int(l["net_cents"])) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            # Positive contribution in Revenue/Expense: Credit revenue (+) / Debit expense (+)
            signed_natural = net_c * sign
            # In ACCREC: revenue credit (+) -> signed_natural is positive; ACCRECCREDIT: doc_dir=-1 reverses it
            # For ACCPAY (expense): Debit expense (+) -> natural balance is positive Expense
            if inv["invoice_type"] in ("ACCRECCREDIT", "ACCPAYCREDIT"):
                signed_natural = -signed_natural
            rows.append(
                {
                    "account_id": l["account_id"],
                    "code": l["acc_code"],
                    "name": l["acc_name"],
                    "account_class": l["account_class"],
                    "account_type": l["account_type"],
                    "amount_cents": signed_natural,
                }
            )

    # Payments in period
    for p in conn.execute(
        "SELECT invoice_id, amount_cents FROM payments WHERE org_id = ? AND status = 'AUTHORISED' AND payment_date BETWEEN ? AND ?",
        (org_id, from_date, to_date),
    ).fetchall():
        _prorate_invoice_doc(p["invoice_id"], int(p["amount_cents"]), sign=1)

    # Credit Note Allocations in period (settle both the Credit Note and the Target Invoice/Bill on Cash basis)
    for a in conn.execute(
        "SELECT credit_note_id, target_invoice_id, amount_cents FROM credit_note_allocations WHERE org_id = ? AND status = 'ACTIVE' AND allocation_date BETWEEN ? AND ?",
        (org_id, from_date, to_date),
    ).fetchall():
        _prorate_invoice_doc(a["credit_note_id"], int(a["amount_cents"]), sign=1)
        _prorate_invoice_doc(a["target_invoice_id"], int(a["amount_cents"]), sign=1)

    # Direct BankTransactions & Cash-Basis Manual Journals
    sql = """
        SELECT jl.account_id, a.code, a.name, a.account_class, a.account_type,
               SUM(jl.credit_cents - jl.debit_cents) AS cr_minus_dr,
               SUM(jl.debit_cents - jl.credit_cents) AS dr_minus_cr
        FROM journal_lines jl
        JOIN journals j ON j.id = jl.journal_id
        JOIN accounts a ON a.id = jl.account_id
        WHERE j.org_id = ? AND a.account_class IN ('REVENUE', 'EXPENSE')
          AND j.journal_date BETWEEN ? AND ?
          AND j.source_type IN ('CASHREC', 'CASHREC_REVERSAL', 'CASHPAID', 'CASHPAID_REVERSAL', 'MANJOURNAL', 'MANJOURNAL_REVERSAL', 'RECODE', 'RECODE_REVERSAL')
          AND j.show_on_cash_basis = 1
    """
    params: list[Any] = [org_id, from_date, to_date]
    if tracking_option_id:
        sql += " AND (jl.tracking_1_option_id = ? OR jl.tracking_2_option_id = ?)"
        params.extend([tracking_option_id, tracking_option_id])
    sql += " GROUP BY jl.account_id"

    for r in conn.execute(sql, params).fetchall():
        amt = int(r["cr_minus_dr"]) if r["account_class"] == "REVENUE" else int(r["dr_minus_cr"])
        rows.append(
            {
                "account_id": r["account_id"],
                "code": r["code"],
                "name": r["name"],
                "account_class": r["account_class"],
                "account_type": r["account_type"],
                "amount_cents": amt,
            }
        )
    return rows


def get_profit_and_loss(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    from_date: str,
    to_date: str,
    basis: str = "ACCRUAL",
    tracking_option_id: str | None = None,
) -> dict[str, Any]:
    parse_iso_date(from_date)
    parse_iso_date(to_date)
    basis_up = (basis or "ACCRUAL").upper()

    by_acc: dict[str, dict[str, Any]] = {}
    if basis_up == "ACCRUAL":
        sql = """
            SELECT a.id AS account_id, a.code, a.name, a.account_class, a.account_type,
                   COALESCE(SUM(jl.debit_cents), 0) AS dr, COALESCE(SUM(jl.credit_cents), 0) AS cr
            FROM journal_lines jl
            JOIN journals j ON j.id = jl.journal_id
            JOIN accounts a ON a.id = jl.account_id
            WHERE j.org_id = ? AND a.account_class IN ('REVENUE', 'EXPENSE')
              AND j.journal_date BETWEEN ? AND ?
        """
        params: list[Any] = [org_id, from_date, to_date]
        if tracking_option_id:
            sql += " AND (jl.tracking_1_option_id = ? OR jl.tracking_2_option_id = ?)"
            params.extend([tracking_option_id, tracking_option_id])
        sql += " GROUP BY a.id ORDER BY a.code, a.name"
        for r in conn.execute(sql, params).fetchall():
            net_dr = int(r["dr"]) - int(r["cr"])
            amt = _signed_balance_for_class(r["account_class"], net_dr)
            if amt != 0:
                by_acc[r["account_id"]] = {
                    "accountId": r["account_id"], "code": r["code"], "name": r["name"],
                    "accountClass": r["account_class"], "accountType": r["account_type"], "cents": amt,
                }
    elif basis_up == "CASH":
        for mv in _pnl_cash_movements(conn, org_id, from_date, to_date, tracking_option_id):
            eid = mv["account_id"]
            if eid not in by_acc:
                by_acc[eid] = {
                    "accountId": eid, "code": mv["code"], "name": mv["name"],
                    "accountClass": mv["account_class"], "accountType": mv["account_type"], "cents": 0,
                }
            by_acc[eid]["cents"] += mv["amount_cents"]
    else:
        raise ApiError(400, "INVALID_BASIS", "Basis must be ACCRUAL or CASH.")

    trading_income = []
    cost_of_sales = []
    other_income = []
    operating_expenses = []

    for item in sorted(by_acc.values(), key=lambda x: (x["code"] or "", x["name"])):
        if item["cents"] == 0:
            continue
        formatted = {
            "accountId": item["accountId"],
            "code": item["code"],
            "name": item["name"],
            "amount": decimal_str_from_cents(item["cents"]),
            "_cents": item["cents"],
        }
        t = item["accountType"]
        if t == "REVENUE":
            trading_income.append(formatted)
        elif t == "DIRECTCOSTS":
            cost_of_sales.append(formatted)
        elif t == "OTHERINCOME":
            other_income.append(formatted)
        else:
            operating_expenses.append(formatted)

    tot_trading = sum(x["_cents"] for x in trading_income)
    tot_cogs = sum(x["_cents"] for x in cost_of_sales)
    gross_profit = tot_trading - tot_cogs
    tot_other = sum(x["_cents"] for x in other_income)
    tot_opex = sum(x["_cents"] for x in operating_expenses)
    net_profit = gross_profit + tot_other - tot_opex

    def _strip(lst):
        return [{k: v for k, v in x.items() if k != "_cents"} for x in lst]

    return {
        "orgId": org_id,
        "fromDate": from_date,
        "toDate": to_date,
        "basis": basis_up,
        "sections": {
            "tradingIncome": _strip(trading_income),
            "costOfSales": _strip(cost_of_sales),
            "otherIncome": _strip(other_income),
            "operatingExpenses": _strip(operating_expenses),
        },
        "totals": {
            "tradingIncome": decimal_str_from_cents(tot_trading),
            "costOfSales": decimal_str_from_cents(tot_cogs),
            "grossProfit": decimal_str_from_cents(gross_profit),
            "otherIncome": decimal_str_from_cents(tot_other),
            "operatingExpenses": decimal_str_from_cents(tot_opex),
            "netProfit": decimal_str_from_cents(net_profit),
        },
    }


# -----------------------------------------------------------------------------
# 2. Dynamic Balance Sheet (Virtual Year-End Close + Bank Overdraft Reclass)
# -----------------------------------------------------------------------------
def get_balance_sheet(conn: sqlite3.Connection, *, org_id: str, as_of_date: str) -> dict[str, Any]:
    as_of = parse_iso_date(as_of_date)
    settings = conn.execute("SELECT fy_end_month, fy_end_day FROM org_settings WHERE org_id = ?", (org_id,)).fetchone()
    fy_start = fiscal_year_start(as_of, int(settings["fy_end_month"]), int(settings["fy_end_day"]))
    fy_start_str = fy_start.isoformat()

    # Cumulative balance-sheet accounts up to as_of_date
    cum_map = {
        r["id"]: int(r["net_dr_cents"])
        for r in conn.execute(
            """
            SELECT jl.account_id AS id, COALESCE(SUM(jl.debit_cents - jl.credit_cents), 0) AS net_dr_cents
            FROM journal_lines jl
            JOIN journals j ON j.id = jl.journal_id
            WHERE j.org_id = ? AND j.journal_date <= ?
            GROUP BY jl.account_id
            """,
            (org_id, as_of_date),
        ).fetchall()
    }

    all_accounts = conn.execute(
        "SELECT * FROM accounts WHERE org_id = ? ORDER BY code, name", (org_id,)
    ).fetchall()

    # Dynamic FY split for P&L accounts:
    # Prior FY net profit (< fy_start_str) -> Retained Earnings (960)
    # Current FY net profit (>= fy_start_str AND <= as_of_date) -> Current Year Earnings
    prior_pnl = conn.execute(
        """
        SELECT COALESCE(SUM(
            CASE WHEN a.account_class = 'REVENUE' THEN jl.credit_cents - jl.debit_cents
                 ELSE -(jl.debit_cents - jl.credit_cents) END
        ), 0) AS net_cents
        FROM journal_lines jl
        JOIN journals j ON j.id = jl.journal_id
        JOIN accounts a ON a.id = jl.account_id
        WHERE j.org_id = ? AND j.journal_date < ? AND a.account_class IN ('REVENUE', 'EXPENSE')
        """,
        (org_id, fy_start_str),
    ).fetchone()[0]

    curr_pnl = conn.execute(
        """
        SELECT COALESCE(SUM(
            CASE WHEN a.account_class = 'REVENUE' THEN jl.credit_cents - jl.debit_cents
                 ELSE -(jl.debit_cents - jl.credit_cents) END
        ), 0) AS net_cents
        FROM journal_lines jl
        JOIN journals j ON j.id = jl.journal_id
        JOIN accounts a ON a.id = jl.account_id
        WHERE j.org_id = ? AND j.journal_date >= ? AND j.journal_date <= ? AND a.account_class IN ('REVENUE', 'EXPENSE')
        """,
        (org_id, fy_start_str, as_of_date),
    ).fetchone()[0]

    bank_assets = []
    current_assets = []
    fixed_assets = []
    current_liabilities = []
    non_current_liabilities = []
    equity_rows = []
    retained_found = False

    for acc in all_accounts:
        if acc["account_class"] in PNL_CLASSES:
            continue
        net_dr = cum_map.get(acc["id"], 0)
        natural = _signed_balance_for_class(acc["account_class"], net_dr)

        # Roll prior FY P&L dynamically into Retained Earnings (960)!
        if acc["system_account"] == "RETAINEDEARNINGS":
            natural += int(prior_pnl)
            retained_found = True
            if natural != 0:
                equity_rows.append({"accountId": acc["id"], "code": acc["code"], "name": acc["name"], "amount": decimal_str_from_cents(natural), "_cents": natural})
            continue

        if natural == 0:
            continue

        t = acc["account_type"]
        # E18 Observed Rule: Negative Bank balance reclassifies dynamically to Current Liabilities as positive Overdraft!
        if t == "BANK":
            if natural < 0:
                current_liabilities.append({"accountId": acc["id"], "code": acc["code"], "name": f"{acc['name']} (Overdraft)", "reclassifiedOverdraft": True, "amount": decimal_str_from_cents(-natural), "_cents": -natural})
            else:
                bank_assets.append({"accountId": acc["id"], "code": acc["code"], "name": acc["name"], "amount": decimal_str_from_cents(natural), "_cents": natural})
        elif t in ("CURRENT", "INVENTORY"):
            current_assets.append({"accountId": acc["id"], "code": acc["code"], "name": acc["name"], "amount": decimal_str_from_cents(natural), "_cents": natural})
        elif t == "FIXED":
            fixed_assets.append({"accountId": acc["id"], "code": acc["code"], "name": acc["name"], "amount": decimal_str_from_cents(natural), "_cents": natural})
        elif t == "CURRLIAB":
            current_liabilities.append({"accountId": acc["id"], "code": acc["code"], "name": acc["name"], "amount": decimal_str_from_cents(natural), "_cents": natural})
        elif t == "TERMLIAB":
            non_current_liabilities.append({"accountId": acc["id"], "code": acc["code"], "name": acc["name"], "amount": decimal_str_from_cents(natural), "_cents": natural})
        elif t == "EQUITY":
            equity_rows.append({"accountId": acc["id"], "code": acc["code"], "name": acc["name"], "amount": decimal_str_from_cents(natural), "_cents": natural})

    if not retained_found and int(prior_pnl) != 0:
        equity_rows.append({"accountId": None, "code": "960", "name": "Retained Earnings", "amount": decimal_str_from_cents(int(prior_pnl)), "_cents": int(prior_pnl)})

    equity_rows.insert(0, {
        "accountId": None, "code": "CYE", "name": "Current Year Earnings",
        "amount": decimal_str_from_cents(int(curr_pnl)), "_cents": int(curr_pnl),
    })

    tot_assets = sum(x["_cents"] for x in bank_assets + current_assets + fixed_assets)
    tot_liabilities = sum(x["_cents"] for x in current_liabilities + non_current_liabilities)
    net_assets = tot_assets - tot_liabilities
    tot_equity = sum(x["_cents"] for x in equity_rows)

    def _strip(lst):
        return [{k: v for k, v in x.items() if k != "_cents"} for x in lst]

    return {
        "orgId": org_id,
        "asOfDate": as_of_date,
        "currentFyStart": fy_start_str,
        "sections": {
            "bank": _strip(bank_assets),
            "currentAssets": _strip(current_assets),
            "fixedAssets": _strip(fixed_assets),
            "currentLiabilities": _strip(current_liabilities),
            "nonCurrentLiabilities": _strip(non_current_liabilities),
            "equity": _strip(equity_rows),
        },
        "totals": {
            "totalBank": decimal_str_from_cents(sum(x["_cents"] for x in bank_assets)),
            "totalCurrentAssets": decimal_str_from_cents(sum(x["_cents"] for x in current_assets)),
            "totalFixedAssets": decimal_str_from_cents(sum(x["_cents"] for x in fixed_assets)),
            "totalAssets": decimal_str_from_cents(tot_assets),
            "totalCurrentLiabilities": decimal_str_from_cents(sum(x["_cents"] for x in current_liabilities)),
            "totalNonCurrentLiabilities": decimal_str_from_cents(sum(x["_cents"] for x in non_current_liabilities)),
            "totalLiabilities": decimal_str_from_cents(tot_liabilities),
            "netAssets": decimal_str_from_cents(net_assets),
            "totalEquity": decimal_str_from_cents(tot_equity),
            "isBalanced": net_assets == tot_equity,
        },
    }


# -----------------------------------------------------------------------------
# 3. Dynamic Trial Balance
# -----------------------------------------------------------------------------
def get_trial_balance(conn: sqlite3.Connection, *, org_id: str, as_of_date: str, include_zero_net: bool = False) -> dict[str, Any]:
    as_of = parse_iso_date(as_of_date)
    settings = conn.execute("SELECT fy_end_month, fy_end_day FROM org_settings WHERE org_id = ?", (org_id,)).fetchone()
    fy_start_str = fiscal_year_start(as_of, int(settings["fy_end_month"]), int(settings["fy_end_day"])).isoformat()

    # Roll prior-FY P&L into Retained Earnings; show BS cumulative and P&L current FY only!
    cum_bs = {
        r["id"]: int(r["net_dr_cents"])
        for r in conn.execute(
            """
            SELECT jl.account_id AS id, COALESCE(SUM(jl.debit_cents - jl.credit_cents), 0) AS net_dr_cents
            FROM journal_lines jl JOIN journals j ON j.id = jl.journal_id
            WHERE j.org_id = ? AND j.journal_date <= ?
            GROUP BY jl.account_id
            """,
            (org_id, as_of_date),
        ).fetchall()
    }
    curr_fy_tx = {
        r["id"]: (int(r["dr"]), int(r["cr"]))
        for r in conn.execute(
            """
            SELECT jl.account_id AS id, COALESCE(SUM(jl.debit_cents), 0) AS dr, COALESCE(SUM(jl.credit_cents), 0) AS cr
            FROM journal_lines jl JOIN journals j ON j.id = jl.journal_id
            WHERE j.org_id = ? AND j.journal_date >= ? AND j.journal_date <= ?
            GROUP BY jl.account_id
            """,
            (org_id, fy_start_str, as_of_date),
        ).fetchall()
    }
    prior_pnl_net_dr = conn.execute(
        """
        SELECT COALESCE(SUM(jl.debit_cents - jl.credit_cents), 0)
        FROM journal_lines jl JOIN journals j ON j.id = jl.journal_id JOIN accounts a ON a.id = jl.account_id
        WHERE j.org_id = ? AND j.journal_date < ? AND a.account_class IN ('REVENUE', 'EXPENSE')
        """,
        (org_id, fy_start_str),
    ).fetchone()[0]

    rows = []
    tot_dr = 0
    tot_cr = 0
    for acc in conn.execute("SELECT * FROM accounts WHERE org_id = ? ORDER BY code, name", (org_id,)).fetchall():
        ytd_dr, ytd_cr = curr_fy_tx.get(acc["id"], (0, 0))
        if acc["account_class"] in PNL_CLASSES:
            net_dr = ytd_dr - ytd_cr
        else:
            net_dr = cum_bs.get(acc["id"], 0)
            if acc["system_account"] == "RETAINEDEARNINGS":
                net_dr += int(prior_pnl_net_dr)

        if net_dr == 0 and not include_zero_net:
            continue
        dr_col = net_dr if net_dr > 0 else 0
        cr_col = -net_dr if net_dr < 0 else 0
        tot_dr += dr_col
        tot_cr += cr_col
        rows.append(
            {
                "accountId": acc["id"],
                "code": acc["code"],
                "name": acc["name"],
                "accountClass": acc["account_class"],
                "accountType": acc["account_type"],
                "ytdDebit": decimal_str_from_cents(ytd_dr),
                "ytdCredit": decimal_str_from_cents(ytd_cr),
                "debit": decimal_str_from_cents(dr_col),
                "credit": decimal_str_from_cents(cr_col),
            }
        )

    return {
        "orgId": org_id,
        "asOfDate": as_of_date,
        "currentFyStart": fy_start_str,
        "rows": rows,
        "totalDebit": decimal_str_from_cents(tot_dr),
        "totalCredit": decimal_str_from_cents(tot_cr),
        "isBalanced": tot_dr == tot_cr,
    }


# -----------------------------------------------------------------------------
# 4. Journal Report, Account Transactions & General Ledger Detail
# -----------------------------------------------------------------------------
def get_journal_report(conn: sqlite3.Connection, *, org_id: str, from_date: str | None = None, to_date: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM journals WHERE org_id = ?"
    params: list[Any] = [org_id]
    if from_date and to_date:
        sql += " AND journal_date BETWEEN ? AND ?"
        params.extend([from_date, to_date])
    sql += " ORDER BY journal_number ASC"
    journals = conn.execute(sql, params).fetchall()
    out = []
    for j in journals:
        lines = conn.execute(
            """
            SELECT jl.*, a.code AS account_code, a.name AS account_name
            FROM journal_lines jl JOIN accounts a ON a.id = jl.account_id
            WHERE jl.journal_id = ? ORDER BY jl.line_no
            """,
            (j["id"],),
        ).fetchall()
        out.append(
            {
                "id": j["id"],
                "journalNumber": j["journal_number"],
                "journalDate": j["journal_date"],
                "sourceType": j["source_type"],
                "sourceId": j["source_id"],
                "reference": j["reference"],
                "narration": j["narration"],
                "reversalOfJournalId": j["reversal_of_journal_id"],
                "postedAt": j["posted_at"],
                "lines": [
                    {
                        "lineNo": l["line_no"],
                        "accountId": l["account_id"],
                        "accountCode": l["account_code"],
                        "accountName": l["account_name"],
                        "description": l["description"],
                        "debit": decimal_str_from_cents(l["debit_cents"]),
                        "credit": decimal_str_from_cents(l["credit_cents"]),
                        "taxTypeCode": l["tax_type_code"],
                    }
                    for l in lines
                ],
            }
        )
    return out


def get_account_transactions(
    conn: sqlite3.Connection, *, org_id: str, account_id: str | None = None, from_date: str | None = None, to_date: str | None = None
) -> dict[str, Any]:
    sql = """
        SELECT jl.*, j.journal_number, j.journal_date, j.source_type, j.source_id, j.reference, j.narration,
               a.code AS account_code, a.name AS account_name, a.account_class, c.name AS contact_name
        FROM journal_lines jl
        JOIN journals j ON j.id = jl.journal_id
        JOIN accounts a ON a.id = jl.account_id
        LEFT JOIN contacts c ON c.id = jl.contact_id
        WHERE j.org_id = ?
    """
    params: list[Any] = [org_id]
    if account_id:
        sql += " AND jl.account_id = ?"
        params.append(account_id)
    if from_date and to_date:
        sql += " AND j.journal_date BETWEEN ? AND ?"
        params.extend([from_date, to_date])
    sql += " ORDER BY a.code, j.journal_date, j.journal_number, jl.line_no"

    grouped: dict[str, dict[str, Any]] = {}
    for r in conn.execute(sql, params).fetchall():
        aid = r["account_id"]
        if aid not in grouped:
            grouped[aid] = {
                "accountId": aid,
                "accountCode": r["account_code"],
                "accountName": r["account_name"],
                "accountClass": r["account_class"],
                "totalDebitCents": 0,
                "totalCreditCents": 0,
                "transactions": [],
            }
        dr = int(r["debit_cents"])
        cr = int(r["credit_cents"])
        grouped[aid]["totalDebitCents"] += dr
        grouped[aid]["totalCreditCents"] += cr
        grouped[aid]["transactions"].append(
            {
                "journalId": r["journal_id"],
                "journalNumber": r["journal_number"],
                "date": r["journal_date"],
                "sourceType": r["source_type"],
                "sourceId": r["source_id"],
                "contactName": r["contact_name"],
                "reference": r["reference"],
                "description": r["description"] or r["narration"],
                "taxTypeCode": r["tax_type_code"],
                "debit": decimal_str_from_cents(dr),
                "credit": decimal_str_from_cents(cr),
            }
        )

    groups_list = []
    for g in grouped.values():
        net_dr = g["totalDebitCents"] - g["totalCreditCents"]
        nat = _signed_balance_for_class(g["accountClass"], net_dr)
        g["totalDebit"] = decimal_str_from_cents(g.pop("totalDebitCents"))
        g["totalCredit"] = decimal_str_from_cents(g.pop("totalCreditCents"))
        g["netMovement"] = decimal_str_from_cents(nat)
        groups_list.append(g)
    return {"orgId": org_id, "accounts": groups_list}


# -----------------------------------------------------------------------------
# 5. Aged Receivables & Aged Payables (Summary & Detail)
# -----------------------------------------------------------------------------
def get_aged_report(
    conn: sqlite3.Connection, *, org_id: str, report_kind: str, as_of_date: str, aging_by: str = "DUE_DATE"
) -> dict[str, Any]:
    """Compute Xero AU 6-bucket Aged Receivables/Payables (Current, <1M, 1M, 2M, 3M, Older)."""
    as_of = parse_iso_date(as_of_date)
    if report_kind.upper() == "RECEIVABLES":
        inv_types = ("ACCREC", "ACCRECCREDIT")
        cn_type = "ACCRECCREDIT"
    else:
        inv_types = ("ACCPAY", "ACCPAYCREDIT")
        cn_type = "ACCPAYCREDIT"

    docs = conn.execute(
        """
        SELECT i.*, c.name AS contact_name
        FROM invoices i JOIN contacts c ON c.id = i.contact_id
        WHERE i.org_id = ? AND i.invoice_type IN (?, ?) AND i.status = 'AUTHORISED' AND i.issue_date <= ?
        ORDER BY c.name, i.due_date
        """,
        (org_id, inv_types[0], inv_types[1], as_of_date),
    ).fetchall()

    # Exact buckets matching Xero: current, lt1m (1..30), m1 (31..60), m2 (61..90), m3 (91..120), older (>120)
    buckets = ("current", "lt1m", "m1", "m2", "m3", "older")
    contacts_map: dict[str, dict[str, Any]] = {}

    for d in docs:
        rem = int(d["total_cents"]) - int(d["amount_paid_cents"]) - int(d["amount_credited_cents"])
        if rem <= 0:
            continue
        signed_rem = -rem if d["invoice_type"] == cn_type else rem
        ref_date = parse_iso_date(d["due_date"] if aging_by.upper() == "DUE_DATE" else d["issue_date"])
        days = (as_of - ref_date).days
        if days <= 0:
            bkey = "current"
        elif days <= 30:
            bkey = "lt1m"
        elif days <= 60:
            bkey = "m1"
        elif days <= 90:
            bkey = "m2"
        elif days <= 120:
            bkey = "m3"
        else:
            bkey = "older"

        cid = d["contact_id"]
        if cid not in contacts_map:
            contacts_map[cid] = {
                "contactId": cid, "contactName": d["contact_name"],
                **{k: 0 for k in buckets}, "totalCents": 0, "items": [],
            }
        contacts_map[cid][bkey] += signed_rem
        contacts_map[cid]["totalCents"] += signed_rem
        contacts_map[cid]["items"].append(
            {
                "invoiceId": d["id"], "invoiceNumber": d["invoice_number"], "invoiceType": d["invoice_type"],
                "issueDate": d["issue_date"], "dueDate": d["due_date"], "bucket": bkey,
                "outstanding": decimal_str_from_cents(signed_rem),
            }
        )

    grand = {k: 0 for k in buckets}
    grand_total = 0
    rows = []
    for c in sorted(contacts_map.values(), key=lambda x: x["contactName"]):
        row = {"contactId": c["contactId"], "contactName": c["contactName"], "items": c["items"]}
        for k in buckets:
            grand[k] += c[k]
            row[k] = decimal_str_from_cents(c[k])
        grand_total += c["totalCents"]
        row["total"] = decimal_str_from_cents(c["totalCents"])
        rows.append(row)

    return {
        "orgId": org_id,
        "reportKind": report_kind.upper(),
        "asOfDate": as_of_date,
        "agingBy": aging_by.upper(),
        "rows": rows,
        "totals": {**{k: decimal_str_from_cents(grand[k]) for k in buckets}, "total": decimal_str_from_cents(grand_total)},
    }


# -----------------------------------------------------------------------------
# 6. Short-Term Cash Flow Analytics
# -----------------------------------------------------------------------------
def get_cash_flow_projection(conn: sqlite3.Connection, *, org_id: str, days: int = 30) -> dict[str, Any]:
    today = date.today()
    horizon = today + timedelta(days=days)
    bank_bal_cents = int(
        conn.execute(
            """
            SELECT COALESCE(SUM(jl.debit_cents - jl.credit_cents), 0)
            FROM journal_lines jl JOIN accounts a ON a.id = jl.account_id
            WHERE jl.org_id = ? AND a.account_type = 'BANK'
            """,
            (org_id,),
        ).fetchone()[0]
    )
    open_docs = conn.execute(
        """
        SELECT i.*, c.name AS contact_name FROM invoices i JOIN contacts c ON c.id = i.contact_id
        WHERE i.org_id = ? AND i.status = 'AUTHORISED' AND i.invoice_type IN ('ACCREC', 'ACCPAY')
        ORDER BY i.due_date
        """,
        (org_id,),
    ).fetchall()

    inflows = 0
    outflows = 0
    upcoming = []
    for d in open_docs:
        rem = int(d["total_cents"]) - int(d["amount_paid_cents"]) - int(d["amount_credited_cents"])
        if rem <= 0:
            continue
        due = parse_iso_date(d["due_date"])
        if due <= horizon:
            is_in = d["invoice_type"] == "ACCREC"
            if is_in:
                inflows += rem
            else:
                outflows += rem
            upcoming.append(
                {
                    "invoiceId": d["id"], "invoiceNumber": d["invoice_number"], "contactName": d["contact_name"],
                    "dueDate": d["due_date"], "direction": "INFLOW" if is_in else "OUTFLOW",
                    "amount": decimal_str_from_cents(rem if is_in else -rem), "isOverdue": due < today,
                }
            )

    projected = bank_bal_cents + inflows - outflows
    return {
        "orgId": org_id,
        "days": days,
        "currentCash": decimal_str_from_cents(bank_bal_cents),
        "expectedInflows": decimal_str_from_cents(inflows),
        "expectedOutflows": decimal_str_from_cents(-outflows),
        "projectedEndBalance": decimal_str_from_cents(projected),
        "upcomingTransactions": upcoming,
    }


# -----------------------------------------------------------------------------
# 7. Conversion Balances Save & Post
# -----------------------------------------------------------------------------
def get_conversion_balances(conn: sqlite3.Connection, org_id: str) -> dict[str, Any]:
    settings = conn.execute("SELECT conversion_date, conversion_locked_at FROM org_settings WHERE org_id = ?", (org_id,)).fetchone()
    rows = conn.execute(
        """
        SELECT cb.*, a.code, a.name, a.account_class, a.account_type, a.system_account
        FROM conversion_balance_entries cb JOIN accounts a ON a.id = cb.account_id
        WHERE cb.org_id = ? ORDER BY a.code, a.name
        """,
        (org_id,),
    ).fetchall()
    tot_dr = sum(int(r["debit_cents"]) for r in rows)
    tot_cr = sum(int(r["credit_cents"]) for r in rows)
    return {
        "orgId": org_id,
        "conversionDate": settings["conversion_date"],
        "conversionLockedAt": settings["conversion_locked_at"],
        "entries": [
            {
                "accountId": r["account_id"], "code": r["code"], "name": r["name"],
                "accountType": r["account_type"], "debit": decimal_str_from_cents(r["debit_cents"]),
                "credit": decimal_str_from_cents(r["credit_cents"]),
            }
            for r in rows
        ],
        "totalDebit": decimal_str_from_cents(tot_dr),
        "totalCredit": decimal_str_from_cents(tot_cr),
        "historicalAdjustmentDiff": decimal_str_from_cents(tot_dr - tot_cr),
    }


def post_conversion_balances(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    conversion_date: str,
    entries: list[dict[str, Any]],
    lock_balances: bool,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Save conversion balances and post balanced CONVERSION journal (balancing diff via 840 Historical Adjustment)."""
    assert_can_write(actor_role)
    if actor_role.upper() != "ADVISER":
        raise ApiError(403, "ADVISER_REQUIRED", "Only Advisers can post conversion balances.")
    parse_iso_date(conversion_date)

    # Reverse any prior CONVERSION journal cleanly before posting new opening balances
    with atomic_tx(conn):
        prior = conn.execute("SELECT id FROM journals WHERE org_id = ? AND source_type = 'CONVERSION' ORDER BY journal_number DESC LIMIT 1", (org_id,)).fetchone()
        if prior:
            reverse_journal(
                conn, org_id=org_id, original_journal_id=prior["id"], reversal_date=conversion_date,
                source_type="CONVERSION_REVERSAL", source_id=org_id, narration="Replace Conversion Balances", actor_user_id=actor_user_id,
            )
        conn.execute("DELETE FROM conversion_balance_entries WHERE org_id = ?", (org_id,))

        gl_lines = []
        tot_dr = 0
        tot_cr = 0
        for e in entries:
            dr_c = cents_from_value(e.get("debit", 0))
            cr_c = cents_from_value(e.get("credit", 0))
            if dr_c == 0 and cr_c == 0:
                continue
            acc = conn.execute("SELECT * FROM accounts WHERE id = ? AND org_id = ?", (e["accountId"], org_id)).fetchone()
            if acc is None:
                raise ApiError(422, "INVALID_ACCOUNT", "Conversion balance account not found.")
            conn.execute(
                "INSERT INTO conversion_balance_entries (id, org_id, account_id, debit_cents, credit_cents) VALUES (?, ?, ?, ?, ?)",
                (new_id(), org_id, acc["id"], dr_c, cr_c),
            )
            tot_dr += dr_c
            tot_cr += cr_c
            gl_lines.append({"account_id": acc["id"], "description": "Conversion Balance", "debit_cents": dr_c, "credit_cents": cr_c})

        diff = tot_dr - tot_cr
        if diff != 0:
            hist_acc = get_system_account(conn, org_id, "HISTORICAL_ADJ")
            gl_lines.append(
                {
                    "account_id": hist_acc["id"],
                    "description": "Historical Adjustment (Out-of-balance conversion diff)",
                    "debit_cents": -diff if diff < 0 else 0,
                    "credit_cents": diff if diff > 0 else 0,
                }
            )

        if gl_lines:
            post_journal(
                conn, org_id=org_id, journal_date=conversion_date, source_type="CONVERSION",
                source_id=org_id, reference="CONVERSION", narration=f"Conversion Balances as at {conversion_date}",
                lines=gl_lines, actor_user_id=actor_user_id,
            )

        conn.execute(
            "UPDATE org_settings SET conversion_date = ?, conversion_locked_at = ?, updated_at = ? WHERE org_id = ?",
            (conversion_date, utc_now_iso() if lock_balances else None, utc_now_iso(), org_id),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "CONVERSION_BALANCES", org_id, "POSTED", f"Conversion balances posted as at {conversion_date} (840 adj diff={decimal_str_from_cents(diff)}).")

    return get_conversion_balances(conn, org_id)


# -----------------------------------------------------------------------------
# 8. Find & Recode (Adviser Bulk Reclassification via Append-Only Ledger)
# -----------------------------------------------------------------------------
def search_recodable_lines(conn: sqlite3.Connection, *, org_id: str, account_id: str | None = None, tax_rate_id: str | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT jl.*, j.journal_number, j.journal_date, j.source_type, j.source_id, j.reference,
               a.code AS account_code, a.name AS account_name, tr.name AS tax_name, c.name AS contact_name
        FROM journal_lines jl
        JOIN journals j ON j.id = jl.journal_id
        JOIN accounts a ON a.id = jl.account_id
        LEFT JOIN tax_rates tr ON tr.id = jl.tax_rate_id
        LEFT JOIN contacts c ON c.id = jl.contact_id
        WHERE j.org_id = ? AND a.is_system_locked = 0 AND a.account_type != 'BANK'
          AND j.source_type IN ('ACCREC', 'ACCPAY', 'CASHREC', 'CASHPAID', 'MANJOURNAL')
    """
    params: list[Any] = [org_id]
    if account_id:
        sql += " AND jl.account_id = ?"
        params.append(account_id)
    if tax_rate_id:
        sql += " AND jl.tax_rate_id = ?"
        params.append(tax_rate_id)
    sql += " ORDER BY j.journal_date DESC, j.journal_number DESC LIMIT 200"
    return [
        {
            "journalLineId": r["id"], "journalId": r["journal_id"], "journalNumber": r["journal_number"],
            "date": r["journal_date"], "sourceType": r["source_type"], "contactName": r["contact_name"],
            "description": r["description"], "accountId": r["account_id"], "accountCode": r["account_code"],
            "accountName": r["account_name"], "taxRateId": r["tax_rate_id"], "taxName": r["tax_name"],
            "debit": decimal_str_from_cents(r["debit_cents"]), "credit": decimal_str_from_cents(r["credit_cents"]),
        }
        for r in conn.execute(sql, params).fetchall()
    ]


def apply_find_and_recode(
    conn: sqlite3.Connection,
    *,
    org_id: str,
    journal_line_ids: list[str],
    new_account_id: str | None,
    new_tracking1_id: str | None,
    actor_user_id: str,
    actor_name: str,
    actor_role: str,
) -> dict[str, Any]:
    """Adviser-only: reclassify selected journal lines by posting append-only Transfer Reversal+Repost in GL."""
    if actor_role.upper() != "ADVISER":
        raise ApiError(403, "ADVISER_REQUIRED", "Only Advisers can run Find and Recode.")
    if not journal_line_ids or (not new_account_id and not new_tracking1_id):
        raise ApiError(422, "RECODE_PARAMS_MISSING", "Select journal lines and a target account or tracking option.")

    target_acc = None
    if new_account_id:
        target_acc = conn.execute("SELECT * FROM accounts WHERE id = ? AND org_id = ? AND status = 'ACTIVE'", (new_account_id, org_id)).fetchone()
        if target_acc is None or target_acc["account_type"] == "BANK" or int(target_acc["is_system_locked"]) == 1:
            raise ApiError(422, "INVALID_RECODE_ACCOUNT", "Target recode account must be an active non-bank non-locked account.")

    batch_id = new_id()
    affected = 0
    dates = []

    with atomic_tx(conn):
        for jlid in journal_line_ids:
            jl = conn.execute(
                "SELECT jl.*, j.journal_date, j.source_id FROM journal_lines jl JOIN journals j ON j.id = jl.journal_id WHERE jl.id = ? AND jl.org_id = ?",
                (jlid, org_id),
            ).fetchone()
            if jl is None:
                continue
            assert_period_unlocked(conn, org_id, jl["journal_date"], actor_role)
            dr = int(jl["debit_cents"])
            cr = int(jl["credit_cents"])
            amt = dr if dr > 0 else cr
            if amt == 0:
                continue

            dest_acc = new_account_id or jl["account_id"]
            # Reverse old classification line & post new classification line cleanly in one balanced RECODE journal
            lines = [
                {
                    "account_id": jl["account_id"], "contact_id": jl["contact_id"],
                    "description": f"Recode out: {jl['description'] or ''}",
                    "debit_cents": cr, "credit_cents": dr,
                    "tax_rate_id": jl["tax_rate_id"], "tax_type_code": jl["tax_type_code"],
                    "gross_cents": -int(jl["gross_cents"]), "net_cents": -int(jl["net_cents"]), "tax_cents": -int(jl["tax_cents"]),
                    "tracking_1_option_id": jl["tracking_1_option_id"],
                },
                {
                    "account_id": dest_acc, "contact_id": jl["contact_id"],
                    "description": f"Recode in: {jl['description'] or ''}",
                    "debit_cents": dr, "credit_cents": cr,
                    "tax_rate_id": jl["tax_rate_id"], "tax_type_code": jl["tax_type_code"],
                    "gross_cents": int(jl["gross_cents"]), "net_cents": int(jl["net_cents"]), "tax_cents": int(jl["tax_cents"]),
                    "tracking_1_option_id": new_tracking1_id if new_tracking1_id is not None else jl["tracking_1_option_id"],
                },
            ]
            post_journal(
                conn, org_id=org_id, journal_date=jl["journal_date"], source_type="RECODE",
                source_id=batch_id, reference=f"RECODE-{batch_id[:6].upper()}",
                narration="Find & Recode reclassification", lines=lines, actor_user_id=actor_user_id,
            )
            affected += 1
            dates.append(jl["journal_date"])

        if affected == 0:
            raise ApiError(422, "NOTHING_RECODED", "No eligible journal lines were recoded.")

        dr_label = f"{min(dates)} to {max(dates)}"
        conn.execute(
            """
            INSERT INTO find_recode_batches (id, org_id, approved_by, transactions_affected, date_range_label, changes_summary_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', ?)
            """,
            (batch_id, org_id, actor_name, affected, dr_label, json.dumps({"newAccountId": new_account_id, "newTracking1Id": new_tracking1_id}), utc_now_iso()),
        )
        write_audit(conn, org_id, actor_user_id, actor_name, "FIND_AND_RECODE", batch_id, "COMPLETED", f"Recoded {affected} line(s) across {dr_label}.")

    return {"batchId": batch_id, "transactionsAffected": affected, "dateRange": dr_label}


# -----------------------------------------------------------------------------
# 9. Assurance Dashboard Anomalies
# -----------------------------------------------------------------------------
def get_assurance_summary(conn: sqlite3.Connection, org_id: str) -> dict[str, Any]:
    dup_banks = conn.execute(
        """
        SELECT bank_bsb_account, COUNT(*) AS cnt, GROUP_CONCAT(name, ', ') AS names
        FROM contacts WHERE org_id = ? AND bank_bsb_account IS NOT NULL AND TRIM(bank_bsb_account) != ''
        GROUP BY bank_bsb_account HAVING cnt > 1
        """,
        (org_id,),
    ).fetchall()
    voided_docs = conn.execute(
        """
        SELECT id, invoice_type, invoice_number, issue_date, total_cents
        FROM invoices WHERE org_id = ? AND status = 'VOIDED' ORDER BY updated_at DESC LIMIT 20
        """,
        (org_id,),
    ).fetchall()
    manual_stmts = conn.execute(
        "SELECT id, tx_date, amount_cents, payee, description FROM bank_statement_lines WHERE org_id = ? AND import_source = 'MANUAL'",
        (org_id,),
    ).fetchall()
    user_activity = conn.execute(
        "SELECT actor_name, COUNT(*) AS actions, MAX(created_at) AS last_active FROM audit_logs WHERE org_id = ? GROUP BY actor_name",
        (org_id,),
    ).fetchall()
    return {
        "duplicateBankContacts": [dict(r) for r in dup_banks],
        "voidedDocuments": [{"id": r["id"], "type": r["invoice_type"], "number": r["invoice_number"], "date": r["issue_date"], "total": decimal_str_from_cents(r["total_cents"])} for r in voided_docs],
        "manualBankLines": [dict(r) for r in manual_stmts],
        "userActivity": [dict(r) for r in user_activity],
    }
