"""AU Organisation Seeder (54 COA + 11 TaxRates + Optional Clean/Demo Org bootstrap)."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import Any

from .db import AU_SEED_PATH, atomic_tx, new_id, utc_now_iso
from .services.ledger import write_audit

BAS_FIELD_MAP: dict[str, list[str]] = {
    "OUTPUT": ["G1", "1A"],
    "EXEMPTOUTPUT": ["G1"],
    "EXEMPTEXPORT": ["G1", "G2"],
    "INPUT": ["1B"],
    "EXEMPTEXPENSES": [],
    "BASEXCLUDED": [],
    "GSTONIMPORTS": ["1B"],
    "CAPEXINPUT": ["G10", "1B"],
    "GSTONCAPIMPORTS": ["1B"],
    "EXEMPTCAPITAL": [],
    "INPUTTAXED": [],
}

ACCOUNT_CLASS_MAP = {
    "Asset": "ASSET",
    "Liability": "LIABILITY",
    "Equity": "EQUITY",
    "Revenue": "REVENUE",
    "Expense": "EXPENSE",
}

ACCOUNT_TYPE_MAP = {
    "Current Asset": "CURRENT",
    "Fixed Asset": "FIXED",
    "Inventory": "INVENTORY",
    "Current Liability": "CURRLIAB",
    "Non-current Liability": "TERMLIAB",
    "Equity": "EQUITY",
    "Revenue": "REVENUE",
    "Direct Costs": "DIRECTCOSTS",
    "Expense": "EXPENSE",
}

SYSTEM_CODE_MAP = {
    "610": "DEBTORS",
    "800": "CREDITORS",
    "820": "GST",
    "960": "RETAINEDEARNINGS",
    "840": "HISTORICAL_ADJ",
    "860": "ROUNDING",
    "801": "UNPAID_EXPENSE_CLAIMS",
    "804": "WAGES_PAYABLE",
    "877": "TRACKING_TRANSFERS",
    "497": "BANK_REVALUATIONS",
    "498": "UNREALISED_FX",
}

ENABLE_PAYMENTS_CODES = {"880", "881", "970", "850"}


def ensure_default_user(conn: sqlite3.Connection) -> sqlite3.Row:
    user = conn.execute("SELECT * FROM users WHERE email = 'adviser@accounting.local'").fetchone()
    if user is None:
        uid = new_id()
        conn.execute(
            """
            INSERT INTO users (id, email, display_name, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (uid, "adviser@accounting.local", "Alex Morgan (Principal)", "demo-hash", utc_now_iso()),
        )
        user = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return user


def create_organisation_with_au_seed(
    conn: sqlite3.Connection,
    *,
    display_name: str,
    short_code: str,
    owner_user_id: str,
    owner_name: str = "Alex Morgan (Principal)",
    legal_name: str | None = None,
    abn: str | None = None,
    industry: str | None = "Professional Services",
    role: str = "ADVISER",
) -> dict[str, Any]:
    """Create a fresh AU organisation seeded with exact 54 COA + 11 TaxRates + Default Settings."""
    seed_data = json.loads(AU_SEED_PATH.read_text(encoding="utf-8"))
    now = utc_now_iso()
    org_id = new_id()

    with atomic_tx(conn):
        conn.execute(
            """
            INSERT INTO organisations (id, short_code, display_name, legal_name, country_code, base_currency, abn, industry, postal_address, created_at)
            VALUES (?, ?, ?, ?, 'AU', 'AUD', ?, ?, ?, ?)
            """,
            (
                org_id,
                short_code,
                display_name,
                legal_name or display_name,
                abn or "12 345 678 901",
                industry,
                "Level 12, 180 Flinders Street, Melbourne VIC 3000",
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO org_settings (org_id, fy_end_month, fy_end_day, gst_accounting_method, bas_reporting_type, bas_calculation_period, bas_g1_mode, sales_tax_default, purchases_tax_default, updated_at)
            VALUES (?, 6, 30, 'ACCRUAL', 'SIMPLER_BAS', 'QUARTERLY', 'INCLUSIVE', 'EXCLUSIVE', 'INCLUSIVE', ?)
            """,
            (org_id, now),
        )
        conn.execute(
            "INSERT INTO org_counters (org_id, next_journal_number) VALUES (?, 1)",
            (org_id,),
        )
        conn.execute(
            "INSERT INTO org_memberships (id, org_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (new_id(), org_id, owner_user_id, role.upper(), now),
        )

        # Seed all 11 AU TaxRates (6 Active + 5 Archived)
        tax_id_by_code: dict[str, str] = {}
        for tr in seed_data["taxRates"]:
            tr_id = new_id()
            code = tr["taxType"]
            tax_id_by_code[code] = tr_id
            rate_dec = f"{(Decimal(str(tr['effectiveRatePercent'])) / Decimal('100')):.4f}"
            status = "ACTIVE" if tr["status"].upper() == "ACTIVE" else "ARCHIVED"
            conn.execute(
                """
                INSERT INTO tax_rates (
                    id, org_id, code, name, rate_decimal, bas_field_names_json,
                    can_apply_to_assets, can_apply_to_equity, can_apply_to_expenses,
                    can_apply_to_liabilities, can_apply_to_revenue, is_system, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    tr_id,
                    org_id,
                    code,
                    tr["name"],
                    rate_dec,
                    json.dumps(BAS_FIELD_MAP.get(code, [])),
                    1 if tr.get("canApplyToAssets", True) else 0,
                    1 if tr.get("canApplyToEquity", True) else 0,
                    1 if tr.get("canApplyToExpenses", True) else 0,
                    1 if tr.get("canApplyToLiabilities", True) else 0,
                    1 if tr.get("canApplyToRevenue", True) else 0,
                    status,
                ),
            )

        # Seed all 54 AU Chart of Accounts
        for acc in seed_data["chartOfAccounts"]:
            code = str(acc["code"])
            acc_class = ACCOUNT_CLASS_MAP[acc["class"]]
            acc_type = ACCOUNT_TYPE_MAP[acc["type"]]
            sys_code = SYSTEM_CODE_MAP.get(code)
            def_tax_code = acc.get("defaultTaxType")
            def_tax_id = tax_id_by_code.get(def_tax_code) if def_tax_code else None
            conn.execute(
                """
                INSERT INTO accounts (
                    id, org_id, code, name, account_class, account_type, system_account,
                    is_system_locked, manual_journal_excluded, enable_payments_to_account,
                    show_on_watchlist, default_tax_rate_id, description, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
                """,
                (
                    new_id(),
                    org_id,
                    code,
                    acc["name"],
                    acc_class,
                    acc_type,
                    sys_code,
                    1 if acc.get("isSystemLocked") else 0,
                    1 if acc.get("manualJournalExcluded") else 0,
                    1 if code in ENABLE_PAYMENTS_CODES else 0,
                    1 if code in {"400", "420", "453"} else 0,
                    def_tax_id,
                    acc.get("description"),
                    now,
                ),
            )

        write_audit(
            conn,
            org_id,
            owner_user_id,
            owner_name,
            "ORGANISATION",
            org_id,
            "CREATED",
            f"Organisation '{display_name}' created with AU 54 COA & 11 TaxRates.",
        )

    return {"id": org_id, "shortCode": short_code, "displayName": display_name}


def bootstrap_initial_orgs(conn: sqlite3.Connection) -> dict[str, Any]:
    """Ensure baseline Southern Cross org exists if DB is brand new."""
    user = ensure_default_user(conn)
    existing = conn.execute("SELECT id, short_code, display_name FROM organisations ORDER BY created_at").fetchall()
    if existing:
        return {"userId": user["id"], "orgs": [dict(r) for r in existing]}

    # Create 1 clean org matching Xero test org + 1 populated Demo Company (AU)
    clean = create_organisation_with_au_seed(
        conn,
        display_name="Southern Cross Office Supplies Pty Ltd",
        short_code="!W5gW!",
        owner_user_id=user["id"],
        abn="53 004 085 616",
        industry="Office Supplies & Consulting",
    )
    return {"userId": user["id"], "orgs": [clean]}
