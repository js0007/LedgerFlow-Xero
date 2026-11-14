"""Unit & invariant tests: SQLite append-only GL/Audit triggers, exact Decimal line rounding, AU seed integrity."""

from __future__ import annotations

import sqlite3
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app import create_app
from backend.db import get_connection
from backend.money import cents_from_value, compute_line_amounts, decimal_str_from_cents, whole_dollars_from_cents


def test_sqlite_append_only_triggers_abort_updates_and_deletes():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "trig.db"
        create_app(db_path=db_path, bootstrap=True)
        conn = get_connection(db_path)
        try:
            j_row = conn.execute("SELECT id FROM journals LIMIT 1").fetchone()
            jl_row = conn.execute("SELECT id FROM journal_lines LIMIT 1").fetchone()
            al_row = conn.execute("SELECT id FROM audit_logs LIMIT 1").fetchone()
            assert j_row and jl_row and al_row

            with pytest.raises(sqlite3.DatabaseError, match="LEDGER_IMMUTABLE"):
                conn.execute("UPDATE journals SET narration = 'tamper' WHERE id = ?", (j_row["id"],))
            with pytest.raises(sqlite3.DatabaseError, match="LEDGER_IMMUTABLE"):
                conn.execute("DELETE FROM journals WHERE id = ?", (j_row["id"],))

            with pytest.raises(sqlite3.DatabaseError, match="LEDGER_IMMUTABLE"):
                conn.execute("UPDATE journal_lines SET debit_cents = 999999 WHERE id = ?", (jl_row["id"],))
            with pytest.raises(sqlite3.DatabaseError, match="LEDGER_IMMUTABLE"):
                conn.execute("DELETE FROM journal_lines WHERE id = ?", (jl_row["id"],))

            with pytest.raises(sqlite3.DatabaseError, match="AUDIT_IMMUTABLE"):
                conn.execute("UPDATE audit_logs SET summary = 'tamper' WHERE id = ?", (al_row["id"],))
            with pytest.raises(sqlite3.DatabaseError, match="AUDIT_IMMUTABLE"):
                conn.execute("DELETE FROM audit_logs WHERE id = ?", (al_row["id"],))
        finally:
            conn.close()


def test_exact_decimal_line_rounding_and_au_whole_dollars():
    # Inclusive $110.00 @ 10% -> Net 100.00, Tax 10.00, Gross 110.00
    n, t, g = compute_line_amounts(
        quantity=1, unit_amount="110.00", discount_pct=0, tax_rate_decimal=Decimal("0.10"), tax_mode="INCLUSIVE"
    )
    assert (n, t, g) == (10000, 1000, 11000)

    # Exclusive $100.00 w/ 15% discount @ 10% -> GrossEx 85.00, Tax 8.50, Total 93.50
    n2, t2, g2 = compute_line_amounts(
        quantity=1, unit_amount="100.00", discount_pct="15.00", tax_rate_decimal=Decimal("0.10"), tax_mode="EXCLUSIVE"
    )
    assert (n2, t2, g2) == (8500, 850, 9350)

    # No-tax line zeroes tax regardless of nominal rate
    n3, t3, g3 = compute_line_amounts(
        quantity=2, unit_amount="49.95", discount_pct=0, tax_rate_decimal=Decimal("0.10"), tax_mode="NO_TAX"
    )
    assert (n3, t3, g3) == (9990, 0, 9990)

    # Half-up & ATO truncation whole dollars
    assert cents_from_value("123.455") == 12346
    assert decimal_str_from_cents(-6050) == "-60.50"
    assert whole_dollars_from_cents(27599) == 275
    assert whole_dollars_from_cents(-5590) == -55


def test_au_seed_accounts_tax_rates_and_manual_journal_exclusions():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "seed.db"
        app = create_app(db_path=db_path, bootstrap=True)
        client = app.test_client()

        orgs = client.get("/api/v1/orgs").get_json()
        clean_org = next(o for o in orgs if o["short_code"] == "!W5gW!")
        org_id = clean_org["id"]

        all_accounts = client.get(f"/api/v1/orgs/{org_id}/accounts").get_json()
        non_bank = [a for a in all_accounts if a["accountType"] != "BANK"]
        assert len(non_bank) == 54

        mj_selectable = client.get(f"/api/v1/orgs/{org_id}/accounts?excludeManualExcluded=true").get_json()
        assert len(mj_selectable) == 47
        mj_codes = {a["code"] for a in mj_selectable}
        for excluded in ("497", "498", "610", "630", "800", "801", "877"):
            assert excluded not in mj_codes
        for included_sys in ("804", "820", "825", "826", "840", "850", "860", "960"):
            assert included_sys in mj_codes

        active_rates = client.get(f"/api/v1/orgs/{org_id}/tax-rates").get_json()
        assert len(active_rates) == 6
        all_rates = client.get(f"/api/v1/orgs/{org_id}/tax-rates?includeArchived=true").get_json()
        assert len(all_rates) == 11
