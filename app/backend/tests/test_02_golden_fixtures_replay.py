"""End-to-end replay of golden live Xero AU verification fixtures (suite_1_mvp_baseline & suite_2_extended_regression)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from backend.app import create_app


def _lookup_helpers(client, org_id):
    accounts = {a["code"]: a for a in client.get(f"/api/v1/orgs/{org_id}/accounts").get_json() if a.get("code")}
    banks = client.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json()
    if not banks:
        client.post(f"/api/v1/orgs/{org_id}/accounts", json={"code": "090", "name": "Business Operating Account", "accountType": "BANK", "bankAccountNumber": "062-000 11223344"})
        banks = client.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json()
    tax_rates = {tr["code"]: tr for tr in client.get(f"/api/v1/orgs/{org_id}/tax-rates?includeArchived=true").get_json()}
    contacts = {c["name"]: c for c in client.get(f"/api/v1/orgs/{org_id}/contacts").get_json()}
    for cname, cust, supp in [("Acme Customer Pty Ltd", True, False), ("AusPost Office Supplies", False, True)]:
        if cname not in contacts:
            contacts[cname] = client.post(
                f"/api/v1/orgs/{org_id}/contacts",
                json={"name": cname, "isCustomer": cust, "isSupplier": supp},
            ).get_json()
    return accounts, banks, tax_rates, contacts


def test_golden_suite_1_and_suite_2_cumulative_parity():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "golden.db"
        app = create_app(db_path=db_path, bootstrap=True)
        client = app.test_client()

        orgs = client.get("/api/v1/orgs").get_json()
        org_id = next(o for o in orgs if o["short_code"] == "!W5gW!")["id"]

        accounts, banks, tax_rates, contacts = _lookup_helpers(client, org_id)
        bank_id = banks[0]["id"]  # Business Operating Account
        acme_id = contacts["Acme Customer Pty Ltd"]["id"]
        auspost_id = contacts["AusPost Office Supplies"]["id"]

        # =====================================================================
        # SUITE 1: MVP-S1 — Approved Sales Invoice $110 Tax-Inclusive -> INV-0001
        # =====================================================================
        inv1 = client.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": acme_id,
                "issueDate": "2026-11-14",
                "dueDate": "2026-11-28",
                "reference": "MVP-BASELINE",
                "taxMode": "INCLUSIVE",
                "lines": [
                    {
                        "description": "Consulting Service Baseline",
                        "quantity": 1,
                        "unitAmount": "110.00",
                        "accountId": accounts["200"]["id"],
                        "taxRateId": tax_rates["OUTPUT"]["id"],
                    }
                ],
                "approveImmediately": True,
            },
        ).get_json()
        assert inv1["invoiceNumber"] == "INV-0001"
        assert inv1["status"] == "AUTHORISED"
        assert inv1["subTotal"] == "100.00"
        assert inv1["totalTax"] == "10.00"
        assert inv1["total"] == "110.00"

        # MVP-S2: Import CSV (2 x $110 deposits on 2026-11-14) + Match Line 0 to INV-0001
        imp = client.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/statement-lines/import",
            json={
                "rows": [
                    {"txDate": "2026-11-14", "amount": "110.00", "payee": "Acme Customer Pty Ltd", "reference": "INV-0001"},
                    {"txDate": "2026-11-14", "amount": "110.00", "payee": "Walk-in Cash Customer", "reference": "CASH-001"},
                ]
            },
        )
        assert imp.status_code == 201
        assert imp.get_json()["importedCount"] == 2

        sugg = client.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/suggestions").get_json()
        assert sugg["bankAccount"]["statementBalance"] == "220.00"
        line_acme = next(s for s in sugg["statementLines"] if s["payee"] == "Acme Customer Pty Ltd")
        line_cash = next(s for s in sugg["statementLines"] if s["payee"] == "Walk-in Cash Customer")

        rec1 = client.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={
                "statementLineId": line_acme["id"],
                "version": line_acme["version"],
                "action": "MATCH_INVOICE",
                "invoiceId": inv1["id"],
                "amount": "110.00",
            },
        )
        assert rec1.status_code == 200
        inv1_after = client.get(f"/api/v1/orgs/{org_id}/invoices/{inv1['id']}").get_json()
        assert inv1_after["status"] == "PAID"

        # MVP-S3: Reconcile Create Receive Money ($110 Inclusive -> Sales 100 + GST 10)
        rec2 = client.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={
                "statementLineId": line_cash["id"],
                "version": line_cash["version"],
                "action": "CREATE_BANK_TX",
                "taxMode": "INCLUSIVE",
                "lines": [
                    {
                        "description": "Cash Coding Direct Sale",
                        "unitAmount": "110.00",
                        "accountId": accounts["200"]["id"],
                        "taxRateId": tax_rates["OUTPUT"]["id"],
                    }
                ],
            },
        )
        assert rec2.status_code == 200

        # MVP End-of-Period Assertions
        jr1 = client.get(f"/api/v1/orgs/{org_id}/reports/journals").get_json()
        assert len(jr1) == 3
        jr1_dr = sum(float(l["debit"]) for j in jr1 for l in j["lines"])
        jr1_cr = sum(float(l["credit"]) for j in jr1 for l in j["lines"])
        assert abs(jr1_dr - 330.00) < 1e-6 and abs(jr1_cr - 330.00) < 1e-6

        tb1 = client.get(f"/api/v1/orgs/{org_id}/reports/trial-balance?date=2026-11-30").get_json()
        tb1_map = {r["name"]: r for r in tb1["rows"]}
        assert tb1_map["Business Operating Account"]["debit"] == "220.00"
        assert tb1_map["Sales"]["credit"] == "200.00"
        assert tb1_map["GST"]["credit"] == "20.00"
        assert "Accounts Receivable" not in tb1_map  # zero-net hidden!

        pnl1 = client.get(f"/api/v1/orgs/{org_id}/reports/profit-and-loss?from=2026-11-01&to=2026-11-30&basis=ACCRUAL").get_json()
        assert pnl1["totals"]["tradingIncome"] == "200.00"
        assert pnl1["totals"]["netProfit"] == "200.00"

        bs1 = client.get(f"/api/v1/orgs/{org_id}/reports/balance-sheet?date=2026-11-30").get_json()
        assert bs1["totals"]["totalAssets"] == "220.00"
        assert bs1["totals"]["totalLiabilities"] == "20.00"
        assert bs1["totals"]["netAssets"] == "200.00"
        assert bs1["totals"]["totalEquity"] == "200.00"

        bas1 = client.get(f"/api/v1/orgs/{org_id}/bas/statement?from=2026-10-01&to=2026-12-31").get_json()
        assert bas1["labels"]["G1"] == "220"
        assert bas1["labels"]["1A"] == "20"
        assert bas1["labels"]["1B"] == "0"
        assert bas1["labels"]["Payment9"] == "20"

        # =====================================================================
        # SUITE 2: EXT-01..EXT-06 Cumulative Regression
        # =====================================================================
        # EXT-01: Manual Journal w/ Auto-Reversing Date + NO_TAX
        mj_res = client.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "Prepaid Rent Accrual Adjustment (Auto-Reverse Test)",
                "journalDate": "2026-11-14",
                "autoReversingDate": "2026-12-01",
                "lineAmountTypes": "NO_TAX",
                "showOnCashBasis": True,
                "lines": [
                    {"accountId": accounts["469"]["id"], "description": "Nov Rent", "debit": "100.00", "credit": "0.00"},
                    {"accountId": accounts["850"]["id"], "description": "Suspense", "debit": "0.00", "credit": "100.00"},
                ],
                "postImmediately": True,
            },
        )
        assert mj_res.status_code == 201
        mj_data = mj_res.get_json()
        assert mj_data["status"] == "POSTED"
        assert mj_data["postedJournalNumber"] == 4
        assert mj_data["reversalJournalNumber"] == 5

        # EXT-02: Purchase Bill $110 Tax-Inclusive -> normalised Net 100, GST 10, Total 110
        bill1 = client.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCPAY",
                "contactId": auspost_id,
                "invoiceNumber": "BILL-0001",
                "issueDate": "2026-11-14",
                "dueDate": "2026-11-21",
                "taxMode": "INCLUSIVE",
                "lines": [
                    {
                        "description": "Office stationery restock",
                        "quantity": 1,
                        "unitAmount": "110.00",
                        "accountId": accounts["461"]["id"],
                        "taxRateId": tax_rates["INPUT"]["id"],
                    }
                ],
                "approveImmediately": True,
            },
        ).get_json()
        assert bill1["subTotal"] == "100.00"
        assert bill1["totalTax"] == "10.00"
        assert bill1["total"] == "110.00"

        # EXT-03: INV-0002 ($110) + Part Pay $55 + CN-0003 ($55) + Allocate to INV-0002
        inv2 = client.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": acme_id,
                "issueDate": "2026-11-14",
                "dueDate": "2026-11-22",
                "reference": "EXT-CREDIT-TEST",
                "taxMode": "EXCLUSIVE",
                "lines": [
                    {
                        "description": "Consulting Retainer - Credit Note Test",
                        "quantity": 1,
                        "unitAmount": "100.00",
                        "accountId": accounts["200"]["id"],
                        "taxRateId": tax_rates["OUTPUT"]["id"],
                    }
                ],
                "approveImmediately": True,
            },
        ).get_json()
        assert inv2["invoiceNumber"] == "INV-0002"

        pay2 = client.post(
            f"/api/v1/orgs/{org_id}/payments",
            json={
                "invoiceId": inv2["id"],
                "bankAccountId": bank_id,
                "paymentDate": "2026-11-14",
                "amount": "55.00",
                "reference": "PART-PAY-55",
            },
        )
        assert pay2.status_code == 201
        assert client.get(f"/api/v1/orgs/{org_id}/invoices/{inv2['id']}").get_json()["amountDue"] == "55.00"

        # Verify shared INV/CN sequence produces CN-0003!
        cn3 = client.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCRECCREDIT",
                "contactId": acme_id,
                "issueDate": "2026-11-14",
                "reference": "CREDIT-INV-0002",
                "taxMode": "EXCLUSIVE",
                "lines": [
                    {
                        "description": "50% Fee Adjustment on INV-0002",
                        "quantity": 1,
                        "unitAmount": "50.00",
                        "accountId": accounts["200"]["id"],
                        "taxRateId": tax_rates["OUTPUT"]["id"],
                    }
                ],
                "approveImmediately": True,
            },
        ).get_json()
        assert cn3["invoiceNumber"] == "CN-0003"
        assert cn3["total"] == "55.00"

        # Before Allocation: Cash BAS only sees paid cash (110 + 110 + 55 = 275) — NOT CN-0003!
        client.patch(f"/api/v1/orgs/{org_id}/settings/financial", json={"gstAccountingMethod": "CASH"})
        bas_pre_alloc = client.get(f"/api/v1/orgs/{org_id}/bas/statement?from=2026-10-01&to=2026-12-31").get_json()
        assert bas_pre_alloc["labels"]["G1"] == "275"
        assert bas_pre_alloc["labels"]["1A"] == "25"

        # Allocate CN-0003 -> INV-0002
        alloc_res = client.post(
            f"/api/v1/orgs/{org_id}/invoices/{cn3['id']}/allocate",
            json={"allocationDate": "2026-11-14", "allocations": [{"targetInvoiceId": inv2["id"], "amount": "55.00"}]},
        )
        assert alloc_res.status_code == 200
        assert alloc_res.get_json()["status"] == "PAID"
        assert client.get(f"/api/v1/orgs/{org_id}/invoices/{inv2['id']}").get_json()["status"] == "PAID"

        # Bank balance in Xero = 275.00 (220 + 55 payment) while Bank Statement Balance = 220.00
        banks_now = client.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json()
        assert banks_now[0]["bookBalance"] == "275.00"
        assert banks_now[0]["statementBalance"] == "220.00"

        # EXT-04: Cumulative GL Debits=Credits & P&L Accrual (Net Profit $50) vs Cash (Net Profit $150)
        jr_all = client.get(f"/api/v1/orgs/{org_id}/reports/journals").get_json()
        assert sum(round(float(l["debit"]) * 100) for j in jr_all for l in j["lines"]) == sum(round(float(l["credit"]) * 100) for j in jr_all for l in j["lines"])

        pnl_acc = client.get(f"/api/v1/orgs/{org_id}/reports/profit-and-loss?from=2026-11-01&to=2026-11-30&basis=ACCRUAL").get_json()
        assert pnl_acc["totals"]["tradingIncome"] == "250.00"
        assert pnl_acc["totals"]["operatingExpenses"] == "200.00"
        assert pnl_acc["totals"]["netProfit"] == "50.00"

        pnl_cash = client.get(f"/api/v1/orgs/{org_id}/reports/profit-and-loss?from=2026-11-01&to=2026-11-30&basis=CASH").get_json()
        assert pnl_cash["totals"]["tradingIncome"] == "250.00"
        assert pnl_cash["totals"]["operatingExpenses"] == "100.00"  # Unpaid BILL-0001 excluded, MJ #4 w/ showOnCashBasis=1 included!
        assert pnl_cash["totals"]["netProfit"] == "150.00"

        # EXT-05: Cumulative Simpler BAS Accrual (G1=275, 1A=25, 1B=10, G11=110, 9=15) vs Cash (G1=275, 1A=25, 1B=0, G11=0, 9=25)
        client.patch(f"/api/v1/orgs/{org_id}/settings/financial", json={"gstAccountingMethod": "ACCRUAL"})
        bas_acc = client.get(f"/api/v1/orgs/{org_id}/bas/statement?from=2026-10-01&to=2026-12-31").get_json()
        assert bas_acc["labels"]["G1"] == "275"
        assert bas_acc["labels"]["1A"] == "25"
        assert bas_acc["labels"]["1B"] == "10"
        assert bas_acc["labels"]["G11"] == "110"
        assert bas_acc["labels"]["Payment9"] == "15"

        client.patch(f"/api/v1/orgs/{org_id}/settings/financial", json={"gstAccountingMethod": "CASH"})
        bas_cash = client.get(f"/api/v1/orgs/{org_id}/bas/statement?from=2026-10-01&to=2026-12-31").get_json()
        assert bas_cash["labels"]["G1"] == "275"
        assert bas_cash["labels"]["1A"] == "25"
        assert bas_cash["labels"]["1B"] == "0"
        assert bas_cash["labels"]["G11"] == "0"
        assert bas_cash["labels"]["Payment9"] == "25"

        # EXT-06: Negative Validation — Hard Lock Date & Unbalanced Manual Journal
        client.patch(f"/api/v1/orgs/{org_id}/settings/financial", json={"hardLockDate": "2026-10-31"})
        locked_post = client.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "Should fail hard lock",
                "journalDate": "2026-10-15",
                "lines": [
                    {"accountId": accounts["469"]["id"], "debit": "50.00", "credit": "0.00"},
                    {"accountId": accounts["850"]["id"], "debit": "0.00", "credit": "50.00"},
                ],
                "postImmediately": True,
            },
        )
        assert locked_post.status_code == 422
        assert locked_post.get_json()["error"]["code"] == "PERIOD_HARD_LOCKED"

        unbal = client.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "Unbalanced test",
                "journalDate": "2026-11-15",
                "lines": [
                    {"accountId": accounts["469"]["id"], "debit": "50.00", "credit": "0.00"},
                    {"accountId": accounts["850"]["id"], "debit": "0.00", "credit": "50.01"},
                ],
                "postImmediately": True,
            },
        )
        assert unbal.status_code == 422
        assert unbal.get_json()["error"]["code"] == "UNBALANCED_JOURNAL"
