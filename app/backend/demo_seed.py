"""Optional AU Demo Company ('!VD61z') Rich Sample Dataset Populator."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from .db import atomic_tx, new_id, utc_now_iso
from .money import cents_from_value
from .seed import create_organisation_with_au_seed, ensure_default_user
from .services.banking import import_statement_lines, reconcile_statement_line, save_bank_rule
from .services.documents import (
    allocate_credit_note,
    create_invoice,
    create_purchase_order,
    create_quote,
    record_payment,
)
from .services.manual_journals import create_manual_journal


def seed_demo_company_au(conn: sqlite3.Connection, *, replace_existing: bool = False) -> dict[str, Any]:
    """Create or reset a realistic AU Demo Company ('!VD61z') showcasing every accounting workflow."""
    user = ensure_default_user(conn)
    existing = conn.execute("SELECT id FROM organisations WHERE short_code = '!VD61z'").fetchone()
    if existing:
        if not replace_existing:
            return {"id": existing["id"], "shortCode": "!VD61z", "displayName": "Demo Company (AU)"}
        oid_old = existing["id"]
        with atomic_tx(conn):
            # Disable ledger immutability triggers momentarily ONLY for full Demo Sandbox Reset
            conn.execute("DROP TRIGGER IF EXISTS trg_journal_lines_immutable_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_journals_immutable_delete")
            conn.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable_delete")
            for tbl in (
                "idempotency_records",
                "connected_apps",
                "bas_statements",
                "find_recode_batches",
                "conversion_balance_entries",
                "bank_statement_lines",
                "bank_rules",
                "bank_transactions",
                "payments",
                "credit_note_allocations",
                "invoices",
                "quotes",
                "purchase_orders",
                "manual_journals",
                "journal_lines",
            ):
                conn.execute(f"DELETE FROM {tbl} WHERE org_id = ?", (oid_old,))
            conn.execute("DELETE FROM journals WHERE org_id = ? AND reversal_of_journal_id IS NOT NULL", (oid_old,))
            conn.execute("DELETE FROM journals WHERE org_id = ?", (oid_old,))
            for tbl in (
                "products",
                "contacts",
                "tracking_options",
                "tracking_categories",
                "accounts",
                "tax_rates",
                "audit_logs",
            ):
                conn.execute(f"DELETE FROM {tbl} WHERE org_id = ?", (oid_old,))
            conn.execute("DELETE FROM organisations WHERE id = ?", (oid_old,))
        from .db import SCHEMA_SQL_PATH
        ddl = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
        for stmt in ddl.split("CREATE TRIGGER IF NOT EXISTS")[1:]:
            if "BEFORE UPDATE" in stmt or "BEFORE DELETE" in stmt:
                conn.execute("CREATE TRIGGER IF NOT EXISTS" + stmt.split("END;")[0] + "END;")

    org = create_organisation_with_au_seed(
        conn,
        display_name="Demo Company (AU)",
        short_code="!VD61z",
        owner_user_id=user["id"],
        legal_name="Demo Company Australia Pty Ltd",
        abn="98 765 432 109",
        industry="Digital Consulting & Retail",
        role="ADVISER",
    )
    oid = org["id"]
    uid = user["id"]
    uname = user["display_name"]

    acc_by_code = {
        r["code"]: r["id"]
        for r in conn.execute("SELECT id, code FROM accounts WHERE org_id = ?", (oid,)).fetchall()
        if r["code"]
    }
    tax_by_code = {
        r["code"]: r["id"]
        for r in conn.execute("SELECT id, code FROM tax_rates WHERE org_id = ?", (oid,)).fetchall()
    }

    with atomic_tx(conn):
        now = utc_now_iso()
        # 1. Bank Accounts
        bank_main_id = new_id()
        bank_sav_id = new_id()
        conn.execute(
            """
            INSERT INTO accounts (id, org_id, code, name, account_class, account_type, is_system_locked, manual_journal_excluded, bank_account_number, bank_currency, status, created_at)
            VALUES (?, ?, '090', 'Business Bank Account', 'ASSET', 'BANK', 0, 1, '306-234-12345678', 'AUD', 'ACTIVE', ?)
            """,
            (bank_main_id, oid, now),
        )
        conn.execute(
            """
            INSERT INTO accounts (id, org_id, code, name, account_class, account_type, is_system_locked, manual_journal_excluded, bank_account_number, bank_currency, status, created_at)
            VALUES (?, ?, '091', 'Business Savings Account', 'ASSET', 'BANK', 0, 1, '306-234-12345679', 'AUD', 'ACTIVE', ?)
            """,
            (bank_sav_id, oid, now),
        )

        # 2. Tracking Category 'Region'
        tc_id = new_id()
        conn.execute("INSERT INTO tracking_categories (id, org_id, name, status) VALUES (?, ?, 'Region', 'ACTIVE')", (tc_id, oid))
        opt_ids = {}
        for opt in ("Eastside", "North", "South", "West Coast"):
            opt_id = new_id()
            opt_ids[opt] = opt_id
            conn.execute("INSERT INTO tracking_options (id, org_id, category_id, name, status) VALUES (?, ?, ?, ?, 'ACTIVE')", (opt_id, oid, tc_id, opt))

        # 3. Contacts
        contacts_spec = [
            ("Ridgeway University", "RU-01", "11 222 333 444", "accounts@ridgeway.example", 1, 0, "[]"),
            ("Bayside Club", "BC-02", "22 333 444 555", "finance@bayside.example", 1, 1, '["Support Clients (monthly)"]'),
            ("DIISR - Small Business Services", "DIISR", "33 444 555 666", "ap@diisr.example", 1, 0, "[]"),
            ("Truxton Property Management", "TPM", "44 555 666 777", "rent@truxton.example", 0, 1, "[]"),
            ("AusPost Office Supplies", "AUSP", "55 666 777 888", "billing@auspost.example", 0, 1, "[]"),
            ("7-Eleven", "7EL", "", "receipts@7eleven.example", 0, 1, "[]"),
        ]
        c_ids = {}
        for name, acc_no, abn, email, is_c, is_s, grps in contacts_spec:
            cid = new_id()
            c_ids[name] = cid
            conn.execute(
                """
                INSERT INTO contacts (id, org_id, name, account_number, abn, email, is_customer, is_supplier, default_sales_account_id, default_purchase_account_id, default_sales_tax_rate_id, default_purchase_tax_rate_id, contact_groups_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
                """,
                (cid, oid, name, acc_no, abn, email, is_c, is_s, acc_by_code["200"], acc_by_code["453"], tax_by_code["OUTPUT"], tax_by_code["INPUT"], grps, now),
            )

        # 4. Products & Services
        prods = [
            ("DevH", "Development work - per hour", 0, None, "90.00", acc_by_code["200"], tax_by_code["OUTPUT"], None, 0, 0),
            ("DevD", "Development work - onsite per day", 0, None, "650.00", acc_by_code["200"], tax_by_code["OUTPUT"], None, 0, 0),
            ("PMWe", "Project management - website", 0, None, "300.00", acc_by_code["200"], tax_by_code["OUTPUT"], None, 0, 0),
            ("TSL-Black", "T-Shirt Large Black", 1, "20.00", "40.00", acc_by_code["200"], tax_by_code["OUTPUT"], acc_by_code["630"], 50000, 2000),
        ]
        for code, name, tracked, cost, sale, s_acc, s_tax, inv_acc, qty_e4, avg_c in prods:
            conn.execute(
                """
                INSERT INTO products (id, org_id, code, name, is_tracked, cost_price_decimal, purchase_account_id, purchase_tax_rate_id, sale_price_decimal, sales_account_id, sales_tax_rate_id, inventory_account_id, quantity_on_hand_e4, avg_cost_cents, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
                """,
                (new_id(), oid, code, name, tracked, cost, acc_by_code["310"], tax_by_code["INPUT"], sale, s_acc, s_tax, inv_acc, qty_e4, avg_c, now),
            )

        # 5. Connected Apps sample
        conn.execute(
            """
            INSERT INTO connected_apps (id, org_id, app_slug, app_name, category, status, scopes_json, connected_at)
            VALUES (?, ?, 'stripe-payments', 'Stripe Online Payments', 'Payments', 'CONNECTED', '["invoices.read","payments.write"]', ?)
            """,
            (new_id(), oid, now),
        )

    # 6. Bank Rule: 7-Eleven -> 453 Office Expenses + GST on Expenses
    save_bank_rule(
        conn,
        org_id=oid,
        rule_id=None,
        actor_user_id=uid,
        actor_name=uname,
        actor_role="ADVISER",
        payload={
            "name": "7-Eleven",
            "ruleType": "SPEND",
            "matchStrategy": "ALL",
            "conditions": [{"field": "PAYEE", "operator": "CONTAINS", "value": "Eleven"}],
            "contactId": c_ids["7-Eleven"],
            "fixedLines": [],
            "percentLines": [{"description": "7-Eleven store supplies", "accountId": acc_by_code["453"], "taxRateId": tax_by_code["INPUT"], "tracking1OptionId": opt_ids["North"], "percent": "100.00"}],
        },
    )

    today = date.today()
    d_ago_45 = (today - timedelta(days=45)).isoformat()
    d_ago_10 = (today - timedelta(days=10)).isoformat()
    d_ago_5 = (today - timedelta(days=5)).isoformat()
    d_due_next = (today + timedelta(days=14)).isoformat()

    # 7. Opening capital via Manual Journal + Prior FY revenue for Cross-FY demonstration
    create_manual_journal(
        conn, org_id=oid, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        payload={
            "narration": "Prior FY consulting retained profit & equipment depreciation",
            "journalDate": "2026-05-15",
            "taxMode": "NO_TAX",
            "postImmediately": True,
            "lines": [
                {"description": "Prepaid consulting accrual", "accountId": acc_by_code["620"], "taxRateId": tax_by_code["BASEXCLUDED"], "debit": "5000.00", "credit": "0.00"},
                {"description": "FY26 Retained Sales", "accountId": acc_by_code["200"], "taxRateId": tax_by_code["BASEXCLUDED"], "debit": "0.00", "credit": "5000.00"},
            ],
        },
    )

    # 8. Quotes, POs, Sales Invoices, Bills, Credit Notes & Payments
    create_quote(
        conn, org_id=oid, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        payload={
            "contactId": c_ids["DIISR - Small Business Services"],
            "issueDate": d_ago_5, "expiryDate": d_due_next, "taxMode": "EXCLUSIVE", "status": "ACCEPTED",
            "title": "Q4 Website Architecture Advisory", "reference": "QUO-WEB",
            "lines": [{"description": "Architecture & Discovery (20 hrs)", "quantity": "20", "unitAmount": "150.00", "accountId": acc_by_code["200"], "taxRateId": tax_by_code["OUTPUT"], "tracking1OptionId": opt_ids["Eastside"]}],
        },
    )
    create_purchase_order(
        conn, org_id=oid, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        payload={
            "contactId": c_ids["AusPost Office Supplies"],
            "issueDate": d_ago_5, "deliveryDate": d_due_next, "taxMode": "INCLUSIVE", "status": "APPROVED",
            "reference": "STATIONERY-Q4",
            "lines": [{"description": "Bulk Shipping Cartons (50 pack)", "quantity": "5", "unitAmount": "66.00", "accountId": acc_by_code["453"], "taxRateId": tax_by_code["INPUT"]}],
        },
    )

    # Sales Invoice 1 (matched later on bank rec or part-paid!)
    inv1 = create_invoice(
        conn, org_id=oid, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        payload={
            "invoiceType": "ACCREC", "contactId": c_ids["Ridgeway University"],
            "invoiceNumber": "ORC01025", "issueDate": d_ago_45, "dueDate": d_ago_10, "taxMode": "INCLUSIVE", "approveImmediately": True,
            "lines": [{"description": "Quarterly Research Data Portal Support", "quantity": "1", "unitAmount": "6187.50", "accountId": acc_by_code["200"], "taxRateId": tax_by_code["OUTPUT"], "tracking1OptionId": opt_ids["Eastside"]}],
        },
    )
    # Sales Invoice 2 (overdue)
    create_invoice(
        conn, org_id=oid, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        payload={
            "invoiceType": "ACCREC", "contactId": c_ids["DIISR - Small Business Services"],
            "invoiceNumber": "ORC01042", "issueDate": d_ago_45, "dueDate": d_ago_10, "taxMode": "EXCLUSIVE", "approveImmediately": True,
            "lines": [{"description": "Monthly Hosting & Advisory Retainer", "quantity": "1", "unitAmount": "3121.82", "accountId": acc_by_code["200"], "taxRateId": tax_by_code["OUTPUT"], "tracking1OptionId": opt_ids["South"]}],
        },
    )
    # Sales Credit Note allocated partly or left open (-60.50 in Aged AR!)
    create_invoice(
        conn, org_id=oid, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        payload={
            "invoiceType": "ACCRECCREDIT", "contactId": c_ids["Bayside Club"],
            "invoiceNumber": "CN-0001", "issueDate": d_ago_5, "dueDate": d_ago_5, "taxMode": "INCLUSIVE", "approveImmediately": True,
            "lines": [{"description": "Downtime SLA credit", "quantity": "1", "unitAmount": "60.50", "accountId": acc_by_code["200"], "taxRateId": tax_by_code["OUTPUT"]}],
        },
    )
    # Bill from Truxton Property Management (with un-reconciled payment so Match Existing Payment lights up!)
    bill1 = create_invoice(
        conn, org_id=oid, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        payload={
            "invoiceType": "ACCPAY", "contactId": c_ids["Truxton Property Management"],
            "invoiceNumber": "RENT-NOV", "issueDate": d_ago_10, "dueDate": d_due_next, "taxMode": "INCLUSIVE", "approveImmediately": True,
            "lines": [{"description": "Office Lease Rent - November", "quantity": "1", "unitAmount": "1181.25", "accountId": acc_by_code["469"], "taxRateId": tax_by_code["INPUT"], "tracking1OptionId": opt_ids["Eastside"]}],
        },
    )
    record_payment(
        conn, org_id=oid, invoice_id=bill1["id"], bank_account_id=bank_main_id,
        payment_date=d_ago_5, amount_cents=118125, reference="Rent",
        actor_user_id=uid, actor_name=uname, actor_role="ADVISER", is_reconciled=False,
    )

    # 9. Import Bank Statement Lines into Main Account (Matches INV, Existing Payment, Bank Rule 7-Eleven & Bank Fee!)
    import_statement_lines(
        conn, org_id=oid, bank_account_id=bank_main_id, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        rows=[
            {"txDate": d_ago_5, "amount": "6187.50", "payee": "Ridgeway University", "description": "ORC01025", "reference": "ORC01025"},
            {"txDate": d_ago_5, "amount": "-1181.25", "payee": "Truxton Property Management", "description": "Rent", "reference": "RENT"},
            {"txDate": today.isoformat(), "amount": "-15.50", "payee": "7-Eleven", "description": "Misc corner store", "reference": "EFTPOS"},
            {"txDate": today.isoformat(), "amount": "-15.00", "payee": "NAB", "description": "Monthly account fee", "reference": "FEE"},
            {"txDate": today.isoformat(), "amount": "-12.00", "payee": "Central City Parking", "description": "Parking Lot A", "reference": "PARK"},
            {"txDate": today.isoformat(), "amount": "-12.00", "payee": "Central City Parking", "description": "Parking Lot A", "reference": "PARK"},
        ],
    )
    # Deposit initial cash in Savings Account via Spend/Receive or Conversion Balance so Savings shows positive and Main shows realistic Twin Balance!
    import_statement_lines(
        conn, org_id=oid, bank_account_id=bank_sav_id, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        rows=[{"txDate": "2026-07-01", "amount": "6878.28", "payee": "Owner Capital", "description": "Initial Savings Capital", "reference": "CAP-01"}],
    )
    sav_line = conn.execute("SELECT id, version FROM bank_statement_lines WHERE bank_account_id = ? LIMIT 1", (bank_sav_id,)).fetchone()
    reconcile_statement_line(
        conn, org_id=oid, bank_account_id=bank_sav_id, actor_user_id=uid, actor_name=uname, actor_role="ADVISER",
        payload={
            "statementLineId": sav_line["id"], "version": sav_line["version"], "action": "CREATE_BANK_TX",
            "createPayload": {"taxMode": "NO_TAX", "reference": "CAP-01", "lines": [{"description": "Owner initial savings deposit", "accountId": acc_by_code["880"], "taxRateId": tax_by_code["BASEXCLUDED"], "amount": "6878.28"}]},
        },
    )

    return org
