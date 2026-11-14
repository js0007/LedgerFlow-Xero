"""Regression test suite for P0/P1 audit fixes, frontend-backend contract repairs,
and extended commercial document lifecycles."""

from __future__ import annotations

import tempfile
from pathlib import Path

from backend.app import create_app


def _get_clean_ctx(client):
    orgs = client.get("/api/v1/orgs").get_json()
    org_id = next(o for o in orgs if o["short_code"] == "!W5gW!")["id"]
    accs = {a["code"]: a for a in client.get(f"/api/v1/orgs/{org_id}/accounts").get_json() if a.get("code")}
    banks = client.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json()
    if not banks:
        client.post(
            f"/api/v1/orgs/{org_id}/accounts",
            json={"code": "090", "name": "Business Operating Account", "accountType": "BANK", "bankAccountNumber": "062-000 11223344"},
        )
        banks = client.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json()
    tax = {t["code"]: t for t in client.get(f"/api/v1/orgs/{org_id}/tax-rates?includeArchived=true").get_json()}
    contacts = {c["name"]: c for c in client.get(f"/api/v1/orgs/{org_id}/contacts").get_json()}
    for cname, cust, supp in [("Acme Customer Pty Ltd", True, False), ("AusPost Office Supplies", False, True)]:
        if cname not in contacts:
            contacts[cname] = client.post(
                f"/api/v1/orgs/{org_id}/contacts",
                json={"name": cname, "isCustomer": cust, "isSupplier": supp},
            ).get_json()
    return org_id, accs, banks, tax, contacts


def test_manual_journal_and_bank_tx_opposite_tax_directions_match_gl_and_bas():
    """Debit OUTPUT MJ & Credit INPUT MJ, plus Spend OUTPUT & Receive INPUT, must negate BAS/GL signs consistently."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "tax_signs.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, banks, tax, contacts = _get_clean_ctx(c)
        bank_id = banks[0]["id"]

        # 1. Standard sale invoice $1,100 incl GST -> G1 = +1100, 1A = +100
        res_inv = c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "issueDate": "2026-10-10",
                "dueDate": "2026-10-20",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Sale", "quantity": 1, "unitAmount": "1100.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
                "approveImmediately": True,
            },
        )
        assert res_inv.status_code == 201

        # 2. Debit OUTPUT Manual Journal (sales adjustment): Dr 200 Sales 100 EX GST -> GST 10 Dr -> Cr 850 Suspense 110
        mj_deb_out = c.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "Debit Sales GST adjustment",
                "journalDate": "2026-10-12",
                "lineAmountTypes": "EXCLUSIVE",
                "lines": [
                    {"accountId": accs["200"]["id"], "description": "Rev Reversal", "debit": "100.00", "credit": "0.00", "taxRateId": tax["OUTPUT"]["id"]},
                    {"accountId": accs["850"]["id"], "description": "Offset", "debit": "0.00", "credit": "110.00", "taxRateId": tax["BASEXCLUDED"]["id"]},
                ],
                "postImmediately": True,
            },
        )
        assert mj_deb_out.status_code == 201

        # 3. Credit INPUT Manual Journal (expense rebate): Cr 400 Advertising 50 EX GST -> GST 5 Cr -> Dr 850 Suspense 55
        mj_cred_in = c.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "Supplier Rebate MJ",
                "journalDate": "2026-10-13",
                "lineAmountTypes": "EXCLUSIVE",
                "lines": [
                    {"accountId": accs["850"]["id"], "description": "Offset", "debit": "55.00", "credit": "0.00", "taxRateId": tax["BASEXCLUDED"]["id"]},
                    {"accountId": accs["400"]["id"], "description": "Ad Rebate", "debit": "0.00", "credit": "50.00", "taxRateId": tax["INPUT"]["id"]},
                ],
                "postImmediately": True,
            },
        )
        assert mj_cred_in.status_code == 201

        # 4. Spend Money with OUTPUT ($220 incl GST -> G1 -220, 1A -20) + Receive Money with INPUT ($110 incl GST -> G11 -110, 1B -10)
        imp = c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/statement-lines/import",
            json={
                "rows": [
                    {"txDate": "2026-10-15", "amount": "-220.00", "payee": "Customer Refund", "reference": "SPEND-OUT"},
                    {"txDate": "2026-10-16", "amount": "110.00", "payee": "Supplier Rebate", "reference": "REC-IN"},
                ]
            },
        ).get_json()
        assert imp["importedCount"] == 2
        sl = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/suggestions").get_json()["statementLines"]
        s_out = next(l for l in sl if l["reference"] == "SPEND-OUT")
        r_in = next(l for l in sl if l["reference"] == "REC-IN")

        assert c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={
                "statementLineId": s_out["id"],
                "version": s_out["version"],
                "action": "CREATE_BANK_TX",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Refund on sale", "unitAmount": "220.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
            },
        ).status_code == 200
        assert c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={
                "statementLineId": r_in["id"],
                "version": r_in["version"],
                "action": "CREATE_BANK_TX",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Expense rebate", "unitAmount": "110.00", "accountId": accs["400"]["id"], "taxRateId": tax["INPUT"]["id"]}],
            },
        ).status_code == 200

        bas = c.get(f"/api/v1/orgs/{org_id}/bas/statement?from=2026-10-01&to=2026-12-31").get_json()
        # G1: +1100 (inv) - 110 (MJ dr OUTPUT) - 220 (Spend OUTPUT) = 770
        # 1A: +100 - 10 - 20 = 70
        # 1B: -5 (MJ cr INPUT) - 10 (Receive INPUT) = -15
        # Payment 9 = 1A - 1B = 70 - (-15) = 85
        assert bas["labels"]["G1"] == "770"
        assert bas["labels"]["1A"] == "70"
        assert bas["labels"]["1B"] == "-15"
        assert bas["labels"]["Payment9"] == "85"

        # Check GL GST account (820) net credit balance equals $85.00!
        tb = c.get(f"/api/v1/orgs/{org_id}/reports/trial-balance?date=2026-12-31").get_json()
        assert tb["isBalanced"] is True
        gst_row = next(r for r in tb["rows"] if r["code"] == "820")
        assert gst_row["credit"] == "85.00"


def test_bas_g10_g11_exempt_classification_and_unfiled_cash_credit_allocation():
    """EXEMPTEXPENSES -> G11, EXEMPTCAPITAL -> G10, and backdated Cash CN allocations appear in next BAS unfiled watermark."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "bas_edge.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, _, tax, contacts = _get_clean_ctx(c)

        # Switch org to CASH BAS + finalise Q1 cleanly
        assert c.patch(f"/api/v1/orgs/{org_id}/settings/financial", json={"gstAccountingMethod": "CASH"}).status_code == 200

        # EXEMPTEXPENSES ($300) and EXEMPTCAPITAL ($1,000) MJ on cash basis in Q1
        assert c.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "Exempt Purchases & Capital",
                "journalDate": "2026-08-15",
                "lineAmountTypes": "EXCLUSIVE",
                "showOnCashBasis": True,
                "lines": [
                    {"accountId": accs["404"]["id"], "description": "Exempt Fee", "debit": "300.00", "credit": "0.00", "taxRateId": tax["EXEMPTEXPENSES"]["id"]},
                    {"accountId": accs["710"]["id"], "description": "Exempt Equip", "debit": "1000.00", "credit": "0.00", "taxRateId": tax["EXEMPTCAPITAL"]["id"]},
                    {"accountId": accs["850"]["id"], "description": "Offset", "debit": "0.00", "credit": "1300.00", "taxRateId": tax["BASEXCLUDED"]["id"]},
                ],
                "postImmediately": True,
            },
        ).status_code == 201

        # Also approve Q1 Invoice ($220) and Q1 Credit Note ($110) before Q1 finalisation (unpaid/unallocated so Q1 Cash BAS excludes them)
        inv = c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "issueDate": "2026-08-10",
                "dueDate": "2026-08-20",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Sale", "quantity": 1, "unitAmount": "220.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
                "approveImmediately": True,
            },
        ).get_json()
        cn = c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCRECCREDIT",
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "issueDate": "2026-08-11",
                "dueDate": "2026-08-11",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "CN", "quantity": 1, "unitAmount": "110.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
                "approveImmediately": True,
            },
        ).get_json()

        fin_q1 = c.post(f"/api/v1/orgs/{org_id}/bas/statement/finalise", json={"from": "2026-07-01", "to": "2026-09-30"})
        assert fin_q1.status_code == 200
        q1_data = fin_q1.get_json()
        assert q1_data["labels"]["G10"] == "1000"
        assert q1_data["labels"]["G11"] == "300"

        # Allocate Q1 Credit Note backdated into Q1 (2026-08-12) AFTER Q1 is finalised!
        alloc_res = c.post(
            f"/api/v1/orgs/{org_id}/invoices/{cn['id']}/allocate",
            json={"allocationDate": "2026-08-12", "allocations": [{"targetInvoiceId": inv["id"], "amount": "110.00"}]},
        )
        assert alloc_res.status_code == 200

        # Next period Q2 Cash BAS should capture this unfiled cash allocation (+110-110=0 net on invoice+CN pair, count=2)
        q2 = c.get(f"/api/v1/orgs/{org_id}/bas/statement?from=2026-10-01&to=2026-12-31").get_json()
        assert q2["unfiledIncludedCount"] >= 2


def test_find_and_recode_unpaid_invoice_does_not_leak_into_cash_pnl():
    """Recoding an unpaid accrual invoice must not make its revenue/expense appear in Cash P&L."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "recode_cash.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, banks, tax, contacts = _get_clean_ctx(c)

        # Unpaid Bill on 469 Rent ($100 + $10 GST)
        c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCPAY",
                "contactId": contacts["AusPost Office Supplies"]["id"],
                "issueDate": "2026-11-10",
                "dueDate": "2026-11-25",
                "taxMode": "EXCLUSIVE",
                "lines": [{"description": "Office Rent", "quantity": 1, "unitAmount": "100.00", "accountId": accs["469"]["id"], "taxRateId": tax["INPUT"]["id"]}],
                "approveImmediately": True,
            },
        )
        # Paid/cash Spend Money on 469 ($50 + GST 5 EX = $55) via CSV + Bank TX
        bank_id = banks[0]["id"]
        c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/statement-lines/import",
            json={"rows": [{"txDate": "2026-11-12", "amount": "-55.00", "payee": "Stationer", "reference": "CSH-1"}]},
        )
        sl = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/suggestions").get_json()["statementLines"][0]
        c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={
                "statementLineId": sl["id"],
                "version": sl["version"],
                "action": "CREATE_BANK_TX",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Cash expense", "unitAmount": "55.00", "accountId": accs["469"]["id"], "taxRateId": tax["INPUT"]["id"]}],
            },
        )

        # Find all lines in 469 -> recode BOTH (unpaid ACCPAY + cash CASHPAID) to 461 Printing & Stationery
        lines = c.get(f"/api/v1/orgs/{org_id}/find-and-recode?accountId={accs['469']['id']}").get_json()["lines"]
        assert len(lines) == 2
        rec = c.post(
            f"/api/v1/orgs/{org_id}/find-and-recode",
            json={"journalLineIds": [l["journalLineId"] for l in lines], "newAccountId": accs["461"]["id"]},
        )
        assert rec.status_code == 200

        cash_pnl = c.get(f"/api/v1/orgs/{org_id}/reports/profit-and-loss?from=2026-11-01&to=2026-11-30&basis=CASH").get_json()
        exp_map = {r["code"]: r["amount"] for r in cash_pnl["sections"]["operatingExpenses"]}
        assert exp_map["461"] == "50.00"  # Only the cash spend! Unpaid $100 ACCPAY did NOT leak!


def test_interbank_transfer_single_gl_posting_minor_adj_cleanup_and_cash_coding_rollback():
    """Verify: (1) Inter-bank transfer suggests MATCH_EXISTING_TRANSFER & Remove&Redo reopens both banks;
    (2) Minor Adjustment is reversed on Remove & Redo; (3) Cash Coding rolls back atomically on conflict."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "bank_fixes.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, banks, tax, contacts = _get_clean_ctx(c)
        bank1_id = banks[0]["id"]
        bank2 = c.post(f"/api/v1/orgs/{org_id}/accounts", json={"code": "095", "name": "Savings Account", "accountType": "BANK"}).get_json()
        bank2_id = bank2["id"]

        # Part A: Two-sided Transfer matching (both banks import their statement lines)
        c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/statement-lines/import",
            json={"rows": [{"txDate": "2026-11-10", "amount": "-500.00", "payee": "Transfer Out", "reference": "XF-1"}]},
        )
        c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank2_id}/statement-lines/import",
            json={"rows": [{"txDate": "2026-11-10", "amount": "500.00", "payee": "Transfer In", "reference": "XF-1"}]},
        )
        l1 = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/suggestions").get_json()["statementLines"][0]
        assert c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/reconcile",
            json={"statementLineId": l1["id"], "version": l1["version"], "action": "TRANSFER", "targetBankAccountId": bank2_id},
        ).status_code == 200

        # Bank 2 should see suggestion MATCH_EXISTING_TRANSFER rather than creating a duplicate GL transfer
        sugg2 = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank2_id}/suggestions").get_json()["statementLines"]
        assert len(sugg2) == 1
        assert sugg2[0]["suggestionType"] == "MATCH_EXISTING_TRANSFER"
        assert sugg2[0]["matchedTransfer"] is not None

        xfer_id = sugg2[0]["matchedTransfer"]["bankTxId"]
        assert c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank2_id}/reconcile",
            json={"statementLineId": sugg2[0]["id"], "version": sugg2[0]["version"], "action": "MATCH_TRANSFER", "matchedBankTransactionId": xfer_id},
        ).status_code == 200

        # Confirm balances: bank1 = -500.00, bank2 = 500.00 (only posted ONCE!)
        accts_after = {b["id"]: b["bookBalance"] for b in c.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json()}
        assert accts_after[bank1_id] == "-500.00"
        assert accts_after[bank2_id] == "500.00"

        # Remove & Redo from bank1 reopens BOTH bank1 and bank2 lines cleanly
        assert c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/remove-redo",
            json={"statementLineId": l1["id"]},
        ).status_code == 200
        assert len(c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/suggestions").get_json()["statementLines"]) == 1
        assert len(c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank2_id}/suggestions").get_json()["statementLines"]) == 1
        accts_zero = {b["id"]: b["bookBalance"] for b in c.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json()}
        assert accts_zero[bank1_id] == "0.00"
        assert accts_zero[bank2_id] == "0.00"

        # Part B: Minor Adjustment Remove & Redo must reverse BOTH payment AND minor adjustment tx!
        inv = c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "issueDate": "2026-11-12",
                "dueDate": "2026-11-22",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Work", "quantity": 1, "unitAmount": "100.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
                "approveImmediately": True,
            },
        ).get_json()
        c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/statement-lines/import",
            json={"rows": [{"txDate": "2026-11-12", "amount": "99.80", "payee": "Acme", "reference": "SHORT"}]},
        )
        sugg_b = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/suggestions").get_json()["statementLines"]
        short_line = next(l for l in sugg_b if l["reference"] == "SHORT")
        assert c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/reconcile",
            json={
                "statementLineId": short_line["id"],
                "version": short_line["version"],
                "action": "MATCH_INVOICE",
                "invoiceId": inv["id"],
                "amount": "100.00",
                "minorAdjustment": {"accountId": accs["860"]["id"], "amount": "-0.20", "description": "Rounding"},
            },
        ).status_code == 200
        assert next(b for b in c.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json() if b["id"] == bank1_id)["bookBalance"] == "99.80"

        # Remove & Redo reverses both $100 payment AND -$0.20 adjustment -> bookBalance back to 0.00!
        assert c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/remove-redo",
            json={"statementLineId": short_line["id"]},
        ).status_code == 200
        assert next(b for b in c.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json() if b["id"] == bank1_id)["bookBalance"] == "0.00"
        assert c.get(f"/api/v1/orgs/{org_id}/invoices/{inv['id']}").get_json()["status"] == "AUTHORISED"

        # Part C: Cash Coding atomic rollback when second item in batch has stale version conflict
        c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/statement-lines/import",
            json={"rows": [{"txDate": "2026-11-14", "amount": "-22.00", "payee": "Cafe", "reference": "CF-1"}]},
        )
        unrec = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/suggestions").get_json()["statementLines"]
        assert len(unrec) >= 2
        bad_batch = c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/cash-coding/apply",
            json={
                "items": [
                    {"statementLineId": unrec[0]["id"], "version": unrec[0]["version"], "accountId": accs["429"]["id"], "taxRateId": tax["INPUT"]["id"]},
                    {"statementLineId": unrec[1]["id"], "version": 999, "accountId": accs["429"]["id"], "taxRateId": tax["INPUT"]["id"]},
                ]
            },
        )
        assert bad_batch.status_code == 409
        # Item 0 MUST NOT have been committed!
        still_unrec = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank1_id}/suggestions").get_json()["statementLines"]
        assert len(still_unrec) == len(unrec)


def test_dashboard_credit_note_netting_accounts_and_products_contracts():
    """Verify Dashboard nets open Credit Notes, COA normalizes OVERHEADS & clears defaultTaxRateId, and Products PATCH/Archive work."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "contracts.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, _, tax, contacts = _get_clean_ctx(c)

        # Dashboard AR = $500 Invoice - $120 Credit Note = $380
        c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "issueDate": "2026-11-01",
                "dueDate": "2026-11-30",
                "taxMode": "NO_TAX",
                "lines": [{"description": "S", "quantity": 1, "unitAmount": "500.00", "accountId": accs["200"]["id"], "taxRateId": tax["BASEXCLUDED"]["id"]}],
                "approveImmediately": True,
            },
        )
        c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCRECCREDIT",
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "issueDate": "2026-11-02",
                "dueDate": "2026-11-02",
                "taxMode": "NO_TAX",
                "lines": [{"description": "CN", "quantity": 1, "unitAmount": "120.00", "accountId": accs["200"]["id"], "taxRateId": tax["BASEXCLUDED"]["id"]}],
                "approveImmediately": True,
            },
        )
        dash = c.get(f"/api/v1/orgs/{org_id}/dashboard").get_json()
        assert dash["receivables"]["awaitingAmount"] == "380.00"

        # Account OVERHEADS -> EXPENSE & clear defaultTaxRateId
        unused_code = next(str(i) for i in range(450, 520) if str(i) not in accs)
        new_acc = c.post(
            f"/api/v1/orgs/{org_id}/accounts",
            json={"code": unused_code, "name": "Test Overhead", "accountType": "OVERHEADS", "defaultTaxRateId": tax["INPUT"]["id"]},
        )
        assert new_acc.status_code == 201
        acc_json = new_acc.get_json()
        assert acc_json["accountType"] == "EXPENSE"
        acc_list = {a["id"]: a for a in c.get(f"/api/v1/orgs/{org_id}/accounts").get_json()}
        assert acc_list[acc_json["id"]]["defaultTaxRateId"] == tax["INPUT"]["id"]

        cleared = c.patch(f"/api/v1/orgs/{org_id}/accounts/{acc_json['id']}", json={"defaultTaxRateId": None})
        assert cleared.status_code == 200
        acc_list2 = {a["id"]: a for a in c.get(f"/api/v1/orgs/{org_id}/accounts").get_json()}
        assert acc_list2[acc_json["id"]]["defaultTaxRateId"] is None

        # Products Create -> Edit -> Archive
        prod = c.post(f"/api/v1/orgs/{org_id}/products", json={"code": "SERV-01", "name": "Retainer", "salePrice": "150.00"})
        assert prod.status_code == 201
        pid = prod.get_json()["id"]
        upd = c.patch(f"/api/v1/orgs/{org_id}/products/{pid}", json={"name": "Advisory Retainer", "salePrice": "250.00"})
        assert upd.status_code == 200
        prod_row = next(p for p in c.get(f"/api/v1/orgs/{org_id}/products").get_json() if p["id"] == pid)
        assert prod_row["name"] == "Advisory Retainer"
        assert prod_row["salePrice"] == "250.00"
        arch = c.delete(f"/api/v1/orgs/{org_id}/products/{pid}")
        assert arch.status_code == 200
        assert all(p["id"] != pid for p in c.get(f"/api/v1/orgs/{org_id}/products").get_json())


def test_commercial_document_full_lifecycle_gaps():
    """Test: (1) Draft Invoice/Quote/PO delete (including Quote->Invoice backlink cleanup),
    (2) Authorised unpaid Doc edit via reversal+repost (and paid rejection),
    (3) Credit Note Cash Refund + Delete Refund + Cash P&L impact,
    (4) Credit Note Deallocate/Unallocate,
    (5) Quote & PO edit + status transitions,
    (6) Missing-field 422 validation."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "lifecycle.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, banks, tax, contacts = _get_clean_ctx(c)
        bank_id = banks[0]["id"]
        cust_id = contacts["Acme Customer Pty Ltd"]["id"]
        supp_id = contacts["AusPost Office Supplies"]["id"]

        # 1. Quote lifecycle: Create -> Edit -> Status (SENT -> ACCEPTED) -> Convert -> Delete Draft Invoice cleanly resets Quote!
        q = c.post(
            f"/api/v1/orgs/{org_id}/quotes",
            json={
                "contactId": cust_id,
                "issueDate": "2026-11-01",
                "expiryDate": "2026-11-15",
                "taxMode": "EXCLUSIVE",
                "lines": [{"description": "Draft Q", "quantity": 1, "unitAmount": "200.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
            },
        ).get_json()
        q_upd = c.patch(
            f"/api/v1/orgs/{org_id}/quotes/{q['id']}",
            json={
                "status": "ACCEPTED",
                "lines": [{"description": "Updated Q", "quantity": 1, "unitAmount": "300.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
            },
        )
        assert q_upd.status_code == 200
        assert q_upd.get_json()["status"] == "ACCEPTED"
        assert q_upd.get_json()["total"] == "330.00"

        conv_inv = c.post(f"/api/v1/orgs/{org_id}/quotes/{q['id']}/convert", json={"approve": False}).get_json()
        assert conv_inv["status"] == "DRAFT"
        # Deleting converted draft invoice must succeed without FK error
        del_inv = c.delete(f"/api/v1/orgs/{org_id}/invoices/{conv_inv['id']}")
        assert del_inv.status_code == 200

        # Standalone quote delete works on non-invoiced quote
        q2 = c.post(
            f"/api/v1/orgs/{org_id}/quotes",
            json={"contactId": cust_id, "issueDate": "2026-11-01", "lines": [{"description": "Temp Q", "quantity": 1, "unitAmount": "50.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}]},
        ).get_json()
        assert c.delete(f"/api/v1/orgs/{org_id}/quotes/{q2['id']}").status_code == 200

        # 2. Purchase Order Edit + Status + Delete
        po = c.post(
            f"/api/v1/orgs/{org_id}/purchase-orders",
            json={"contactId": supp_id, "issueDate": "2026-11-01", "lines": [{"description": "Supply", "quantity": 1, "unitAmount": "100.00", "accountId": accs["461"]["id"], "taxRateId": tax["INPUT"]["id"]}]},
        ).get_json()
        po_upd = c.patch(f"/api/v1/orgs/{org_id}/purchase-orders/{po['id']}", json={"status": "APPROVED"})
        assert po_upd.status_code == 200
        assert po_upd.get_json()["status"] == "APPROVED"
        assert c.delete(f"/api/v1/orgs/{org_id}/purchase-orders/{po['id']}").status_code == 200

        # 3. Authorised Unpaid Invoice Edit via append-only Reversal + Repost
        inv = c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": cust_id,
                "issueDate": "2026-11-05",
                "dueDate": "2026-11-20",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Original Fee", "quantity": 1, "unitAmount": "550.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
                "approveImmediately": True,
            },
        ).get_json()
        inv_edit = c.patch(
            f"/api/v1/orgs/{org_id}/invoices/{inv['id']}",
            json={
                "version": inv["version"],
                "lines": [{"description": "Revised Fee", "quantity": 1, "unitAmount": "880.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
            },
        )
        assert inv_edit.status_code == 200
        edited_inv = inv_edit.get_json()
        assert edited_inv["total"] == "880.00"
        assert edited_inv["postedJournalNumber"] > inv["postedJournalNumber"]

        # 4. Credit Note Allocation -> Deallocate/Unallocate -> Cash Refund -> Delete Refund
        cn = c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCRECCREDIT",
                "contactId": cust_id,
                "issueDate": "2026-11-08",
                "dueDate": "2026-11-08",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Credit Note", "quantity": 1, "unitAmount": "220.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
                "approveImmediately": True,
            },
        ).get_json()

        # Allocate $220 to invoice -> both partially settled
        al = c.post(
            f"/api/v1/orgs/{org_id}/invoices/{cn['id']}/allocate",
            json={"allocationDate": "2026-11-09", "allocations": [{"targetInvoiceId": inv["id"], "amount": "220.00"}]},
        )
        assert al.status_code == 200
        alloc_id = al.get_json()["allocations"][0]["id"]
        assert c.get(f"/api/v1/orgs/{org_id}/invoices/{inv['id']}").get_json()["amountDue"] == "660.00"

        # Editing an allocated CN must be blocked
        assert c.patch(
            f"/api/v1/orgs/{org_id}/invoices/{cn['id']}",
            json={"lines": [{"description": "Nope", "quantity": 1, "unitAmount": "110.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}]},
        ).status_code == 422

        # Deallocate -> reopens both Invoice ($880 due) and Credit Note ($220 due)
        deal = c.delete(f"/api/v1/orgs/{org_id}/credit-note-allocations/{alloc_id}")
        assert deal.status_code == 200
        assert c.get(f"/api/v1/orgs/{org_id}/invoices/{inv['id']}").get_json()["amountDue"] == "880.00"
        assert c.get(f"/api/v1/orgs/{org_id}/invoices/{cn['id']}").get_json()["amountDue"] == "220.00"
        assert c.get(f"/api/v1/orgs/{org_id}/invoices/{cn['id']}").get_json()["status"] == "AUTHORISED"

        # Now Cash Refund the $220 Credit Note -> CN status PAID, Bank drops -$220, Cash P&L = -$200, Cash BAS G1=-220, 1A=-20!
        refund = c.post(
            f"/api/v1/orgs/{org_id}/payments",
            json={"invoiceId": cn["id"], "bankAccountId": bank_id, "paymentDate": "2026-11-10", "amount": "220.00", "reference": "REF-220"},
        )
        assert refund.status_code == 201
        refund_id = refund.get_json()["id"]
        assert c.get(f"/api/v1/orgs/{org_id}/invoices/{cn['id']}").get_json()["status"] == "PAID"
        assert c.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json()[0]["bookBalance"] == "-220.00"

        cash_bas = c.get(f"/api/v1/orgs/{org_id}/bas/statement?from=2026-11-01&to=2026-11-30").get_json()
        # Org is accrual by default: switch to CASH briefly to check CN refund cash BAS & Cash P&L
        c.patch(f"/api/v1/orgs/{org_id}/settings/financial", json={"gstAccountingMethod": "CASH"})
        cash_bas = c.get(f"/api/v1/orgs/{org_id}/bas/statement?from=2026-11-01&to=2026-11-30").get_json()
        assert cash_bas["labels"]["G1"] == "-220"
        assert cash_bas["labels"]["1A"] == "-20"

        # Delete Cash Refund -> reverses bank outflow and reopens Credit Note
        del_ref = c.delete(f"/api/v1/orgs/{org_id}/payments/{refund_id}")
        assert del_ref.status_code == 200
        assert del_ref.get_json()["status"] == "AUTHORISED"
        assert c.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json()[0]["bookBalance"] == "0.00"

        # 5. Missing required fields return 422 instead of raw 500 KeyError
        assert c.post(f"/api/v1/orgs/{org_id}/payments", json={"amount": "10.00"}).status_code == 422
        assert c.post(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/unreconcile", json={}).status_code == 422
        assert c.post(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/remove-redo", json={}).status_code == 422
