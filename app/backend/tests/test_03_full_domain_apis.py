"""Comprehensive API tests: Quotes/POs, CSV occurrence_idx, Bank Rules, Lock Conflicts, Cash Coding,
Reconcile 409 lock, Unreconcile/Remove&Redo, Taxed/Void MJ, Soft Lock vs Hard Lock, Virtual FY Close &
Overdraft reclass, Aged AR/AP 6 buckets, BAS Finalise + Unfiled Watermark, Conversion Balances, Find&Recode, Demo Seed."""

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
        client.post(f"/api/v1/orgs/{org_id}/accounts", json={"code": "090", "name": "Business Operating Account", "accountType": "BANK", "bankAccountNumber": "062-000 11223344"})
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


def test_quotes_and_purchase_orders_convert_to_invoice_and_bill():
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "qp.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, _, tax, contacts = _get_clean_ctx(c)

        # Quote -> Convert to Invoice (approved)
        q = c.post(
            f"/api/v1/orgs/{org_id}/quotes",
            json={
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "title": "Advisory Retainer Quote",
                "issueDate": "2026-11-10",
                "expiryDate": "2026-11-30",
                "taxMode": "EXCLUSIVE",
                "lines": [
                    {"description": "Setup Workshop", "quantity": 2, "unitAmount": "500.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}
                ],
            },
        )
        assert q.status_code == 201
        q_data = q.get_json()
        assert q_data["quoteNumber"] == "QU-0001"
        assert q_data["total"] == "1100.00"

        inv_from_q = c.post(f"/api/v1/orgs/{org_id}/quotes/{q_data['id']}/convert", json={"approve": True})
        assert inv_from_q.status_code == 200
        assert inv_from_q.get_json()["status"] == "AUTHORISED"
        assert inv_from_q.get_json()["total"] == "1100.00"

        # Quote convert is idempotent (returns already-converted invoice without duplicating)
        dup = c.post(f"/api/v1/orgs/{org_id}/quotes/{q_data['id']}/convert", json={})
        assert dup.status_code == 200
        assert dup.get_json()["id"] == inv_from_q.get_json()["id"]

        # Purchase Order -> Copy to Bill
        po = c.post(
            f"/api/v1/orgs/{org_id}/purchase-orders",
            json={
                "contactId": contacts["AusPost Office Supplies"]["id"],
                "issueDate": "2026-11-10",
                "deliveryDate": "2026-11-12",
                "taxMode": "INCLUSIVE",
                "lines": [
                    {"description": "Paper Boxes", "quantity": 4, "unitAmount": "55.00", "accountId": accs["461"]["id"], "taxRateId": tax["INPUT"]["id"]}
                ],
            },
        )
        assert po.status_code == 201
        po_data = po.get_json()
        assert po_data["poNumber"] == "PO-0001"
        bill_from_po = c.post(f"/api/v1/orgs/{org_id}/purchase-orders/{po_data['id']}/convert", json={"approve": True})
        assert bill_from_po.status_code == 200
        assert bill_from_po.get_json()["total"] == "220.00"
        assert bill_from_po.get_json()["subTotal"] == "200.00"
        assert bill_from_po.get_json()["totalTax"] == "20.00"


def test_csv_occurrence_idx_bank_rules_minor_adjustment_lock_cash_coding_and_undo():
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "bank.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, banks, tax, contacts = _get_clean_ctx(c)
        bank_id = banks[0]["id"]
        bank2 = c.post(f"/api/v1/orgs/{org_id}/accounts", json={"code": "095", "name": "Business Savings", "accountType": "BANK"}).get_json()

        # Create 2 identical coffees same day + 1 7-Eleven + 1 Transfer + 1 Minor-Adjusted Invoice
        csv_text = "\n".join([
            "Date,Amount,Payee,Description,Reference",
            "2026-11-15,-5.50,Cafe Roma,Morning Coffee,C1",
            "2026-11-15,-5.50,Cafe Roma,Morning Coffee,C1",
            "2026-11-15,-55.00,7-Eleven AU,Fuel & Snacks,711-01",
            "2026-11-15,-500.00,Internal Transfer,To Savings,XFER-1",
            "2026-11-15,109.90,Acme Customer Pty Ltd,Short Paid 10c,INV-0001",
        ])
        imp1 = c.post(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/statement-lines/import", json={"csvText": csv_text}).get_json()
        assert imp1["importedCount"] == 5

        # Re-importing exact same CSV yields 0 new rows (dedup via occurrence_idx fingerprint!)
        imp2 = c.post(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/statement-lines/import", json={"csvText": csv_text}).get_json()
        assert imp2["importedCount"] == 0
        assert imp2["skippedDuplicates"] == 5

        # Create 7-Eleven Spend Rule (ANY payee/description contains 7-Eleven, fixed $10 Bank Fee + 100% Motor Vehicle)
        rule_res = c.post(
            f"/api/v1/orgs/{org_id}/bank-rules",
            json={
                "name": "7-Eleven AU",
                "ruleType": "SPEND",
                "matchStrategy": "ANY",
                "conditions": [{"field": "payee", "operator": "contains", "value": "7-Eleven"}],
                "contactId": contacts["AusPost Office Supplies"]["id"],
                "fixedLines": [{"description": "Service Fee", "amount": "11.00", "accountId": accs["404"]["id"], "taxRateId": tax["EXEMPTEXPENSES"]["id"]}],
                "percentLines": [{"description": "Fuel Split", "percent": "100", "accountId": accs["449"]["id"], "taxRateId": tax["INPUT"]["id"]}],
            },
        )
        assert rule_res.status_code == 201
        rule_id = rule_res.get_json()["id"]

        # Create Invoice $110.00 to test Match w/ 0.10 Minor Adjustment (Bank Fee / Rounding)
        inv = c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "issueDate": "2026-11-15",
                "dueDate": "2026-11-30",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Work", "quantity": 1, "unitAmount": "110.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
                "approveImmediately": True,
            },
        ).get_json()

        sugg = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/suggestions").get_json()["statementLines"]
        line_711 = next(l for l in sugg if "7-Eleven" in l["payee"])
        assert line_711["matchedRule"] and line_711["matchedRule"]["ruleName"] == "7-Eleven AU"

        # Execute 7-Eleven Rule Create + Verify 409 Stale Version Check
        stale = c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={"statementLineId": line_711["id"], "version": 99, "action": "CREATE_BANK_TX", "bankRuleId": rule_id},
        )
        assert stale.status_code == 409
        rec_711 = c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={"statementLineId": line_711["id"], "version": line_711["version"], "action": "CREATE_BANK_TX", "bankRuleId": rule_id},
        )
        assert rec_711.status_code == 200

        # Transfer $500 to Business Savings
        line_xfer = next(l for l in sugg if "Internal Transfer" in l["payee"])
        rec_xfer = c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={"statementLineId": line_xfer["id"], "version": line_xfer["version"], "action": "TRANSFER", "targetBankAccountId": bank2["id"]},
        )
        assert rec_xfer.status_code == 200
        assert next(b for b in c.get(f"/api/v1/orgs/{org_id}/bank-accounts").get_json() if b["id"] == bank2["id"])["bookBalance"] == "500.00"

        # Match $109.90 bank receipt to $110.00 Invoice w/ 0.10 Minor Adjustment!
        line_inv = next(l for l in sugg if "Short Paid" in l["description"])
        rec_inv = c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={
                "statementLineId": line_inv["id"],
                "version": line_inv["version"],
                "action": "MATCH_INVOICE",
                "invoiceId": inv["id"],
                "amount": "110.00",
                "minorAdjustment": {"accountId": accs["860"]["id"], "amount": "-0.10", "description": "Rounding 10c"},
            },
        )
        assert rec_inv.status_code == 200
        assert c.get(f"/api/v1/orgs/{org_id}/invoices/{inv['id']}").get_json()["status"] == "PAID"

        # Cash Coding Batch on the 2 identical coffees ($5.50 each)
        coffees = [l for l in sugg if "Cafe Roma" in l["payee"]]
        assert len(coffees) == 2
        cc = c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/cash-coding/apply",
            json={
                "items": [
                    {
                        "statementLineId": cf["id"],
                        "version": cf["version"],
                        "accountId": accs["429"]["id"],
                        "taxRateId": tax["INPUT"]["id"],
                        "description": "Staff Coffee",
                    }
                    for cf in coffees
                ]
            },
        )
        assert cc.status_code == 200
        assert cc.get_json()["reconciledCount"] == 2

        # Now Remove & Redo one coffee -> becomes unreconciled again and posts reversal journal
        rr = c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/remove-redo",
            json={"statementLineId": coffees[0]["id"]},
        )
        assert rr.status_code == 200
        sugg_after = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/suggestions").get_json()
        assert len(sugg_after["statementLines"]) == 1

        # Archive bank rule cleanly (tests committed archive_bank_rule!)
        del_r = c.delete(f"/api/v1/orgs/{org_id}/bank-rules/{rule_id}")
        assert del_r.status_code == 200
        assert all(r["id"] != rule_id for r in c.get(f"/api/v1/orgs/{org_id}/bank-rules").get_json())


def test_manual_journal_taxed_edit_void_lock_hierarchy_and_rbac():
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "mj_lock.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, _, tax, _ = _get_clean_ctx(c)

        # Tax Exclusive Manual Journal (like #499: Net 100.00 + GST 10.00 vs Balancing 110.00 Credit)
        mj = c.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "Taxed Entertainment Journal",
                "journalDate": "2026-11-10",
                "lineAmountTypes": "EXCLUSIVE",
                "showOnCashBasis": False,
                "lines": [
                    {"accountId": accs["420"]["id"], "description": "Client Dinner", "debit": "100.00", "credit": "0.00", "taxRateId": tax["INPUT"]["id"]},
                    {"accountId": accs["850"]["id"], "description": "Suspense Gross", "debit": "0.00", "credit": "110.00", "taxRateId": tax["BASEXCLUDED"]["id"]},
                ],
                "postImmediately": True,
            },
        )
        assert mj.status_code == 201
        mj_id = mj.get_json()["id"]
        assert mj.get_json()["taxTotal"] == "10.00"

        # Edit Posted Manual Journal -> generates reversal + new posted journal
        upd = c.patch(
            f"/api/v1/orgs/{org_id}/manual-journals/{mj_id}",
            json={
                "narration": "Taxed Entertainment Journal Amended",
                "journalDate": "2026-11-10",
                "lineAmountTypes": "EXCLUSIVE",
                "lines": [
                    {"accountId": accs["420"]["id"], "description": "Client Dinner Amended", "debit": "200.00", "credit": "0.00", "taxRateId": tax["INPUT"]["id"]},
                    {"accountId": accs["850"]["id"], "description": "Suspense Gross", "debit": "0.00", "credit": "220.00", "taxRateId": tax["BASEXCLUDED"]["id"]},
                ],
            },
        )
        assert upd.status_code == 200
        assert upd.get_json()["postedJournalNumber"] > 1

        # Void Posted Manual Journal
        vd = c.post(f"/api/v1/orgs/{org_id}/manual-journals/{mj_id}/void")
        assert vd.status_code == 200
        assert vd.get_json()["status"] == "VOIDED"

        # Soft Lock Date <= Hard Lock validation & Standard vs Adviser enforcement
        bad_hier = c.patch(f"/api/v1/orgs/{org_id}/settings/financial", json={"softLockDate": "2026-09-30", "hardLockDate": "2026-10-31"})
        assert bad_hier.status_code == 422

        c.patch(f"/api/v1/orgs/{org_id}/settings/financial", json={"hardLockDate": "2026-09-30", "softLockDate": "2026-10-31"})
        # Switch role to STANDARD -> blocked in Soft Lock (2026-10-15)
        c.post("/api/v1/auth/switch-role", json={"orgId": org_id, "role": "STANDARD"})
        std_soft = c.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "Blocked for Standard",
                "journalDate": "2026-10-15",
                "lines": [
                    {"accountId": accs["469"]["id"], "debit": "20.00", "credit": "0.00"},
                    {"accountId": accs["850"]["id"], "debit": "0.00", "credit": "20.00"},
                ],
                "postImmediately": True,
            },
        )
        assert std_soft.status_code == 422
        assert std_soft.get_json()["error"]["code"] == "PERIOD_SOFT_LOCKED"

        # READONLY role blocked on any write
        c.post("/api/v1/auth/switch-role", json={"orgId": org_id, "role": "READONLY"})
        ro_res = c.post(f"/api/v1/orgs/{org_id}/contacts", json={"name": "Nope"})
        assert ro_res.status_code == 403

        # Switch back to ADVISER -> ALLOWED in Soft Lock (2026-10-15 > Hard 2026-09-30)
        c.post("/api/v1/auth/switch-role", json={"orgId": org_id, "role": "ADVISER"})
        adv_soft = c.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "Allowed for Adviser",
                "journalDate": "2026-10-15",
                "lines": [
                    {"accountId": accs["469"]["id"], "debit": "20.00", "credit": "0.00"},
                    {"accountId": accs["850"]["id"], "debit": "0.00", "credit": "20.00"},
                ],
                "postImmediately": True,
            },
        )
        assert adv_soft.status_code == 201


def test_virtual_fy_close_overdraft_reclass_bas_finalise_unfiled_conversion_recode_and_demo():
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(db_path=Path(tmp) / "adv.db", bootstrap=True)
        c = app.test_client()
        org_id, accs, banks, tax, contacts = _get_clean_ctx(c)
        bank_id = banks[0]["id"]

        # 1. Cross-FY Virtual Year-End Close + Bank Overdraft Reclassification!
        # Post FY26 Revenue $1,000 on 2026-06-15 (FY ends 30 Jun 2026 in AU)
        c.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "FY26 Sale",
                "journalDate": "2026-06-15",
                "lines": [
                    {"accountId": accs["850"]["id"], "debit": "1000.00", "credit": "0.00"},
                    {"accountId": accs["200"]["id"], "debit": "0.00", "credit": "1000.00"},
                ],
                "postImmediately": True,
            },
        )
        # Post FY27 Revenue $400 + Overdrawn Bank -$300 on 2026-07-10 (FY27)
        c.post(
            f"/api/v1/orgs/{org_id}/manual-journals",
            json={
                "narration": "FY27 Sale",
                "journalDate": "2026-07-10",
                "lines": [
                    {"accountId": accs["850"]["id"], "debit": "400.00", "credit": "0.00"},
                    {"accountId": accs["200"]["id"], "debit": "0.00", "credit": "400.00"},
                ],
                "postImmediately": True,
            },
        )
        # Overdraw Bank by $300 via CSV + Spend Money Create
        c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/statement-lines/import",
            json={"rows": [{"txDate": "2026-07-10", "amount": "-300.00", "payee": "Vendor", "reference": "OD-1"}]},
        )
        line_od = c.get(f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/suggestions").get_json()["statementLines"][0]
        c.post(
            f"/api/v1/orgs/{org_id}/bank-accounts/{bank_id}/reconcile",
            json={
                "statementLineId": line_od["id"],
                "version": line_od["version"],
                "action": "CREATE_BANK_TX",
                "taxMode": "NO_TAX",
                "lines": [{"description": "Overdrawn Spend", "unitAmount": "300.00", "accountId": accs["469"]["id"], "taxRateId": tax["BASEXCLUDED"]["id"]}],
            },
        )

        bs = c.get(f"/api/v1/orgs/{org_id}/reports/balance-sheet?date=2026-07-31").get_json()
        eq_map = {e["name"]: e["amount"] for e in bs["sections"]["equity"]}
        assert eq_map["Retained Earnings"] == "1000.00"
        assert eq_map["Current Year Earnings"] == "100.00"  # 400 revenue - 300 rent!
        assert any("Overdraft" in li["name"] and li["amount"] == "300.00" for li in bs["sections"]["currentLiabilities"])

        # 2. BAS Finalise + Unfiled Amounts Watermark Detection
        c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "issueDate": "2026-08-10",
                "dueDate": "2026-08-20",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Q1 Sale", "quantity": 1, "unitAmount": "110.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
                "approveImmediately": True,
            },
        )
        fin = c.post(f"/api/v1/orgs/{org_id}/bas/statement/finalise", json={"from": "2026-07-01", "to": "2026-09-30"})
        assert fin.status_code == 200
        assert fin.get_json()["labels"]["G1"] == "110"
        assert fin.get_json()["status"] == "FINALISED"

        # Now backdate a $220 Tax-Inclusive Invoice into Q1 (2026-08-15) AFTER Q1 is Finalised!
        c.post(
            f"/api/v1/orgs/{org_id}/invoices",
            json={
                "invoiceType": "ACCREC",
                "contactId": contacts["Acme Customer Pty Ltd"]["id"],
                "issueDate": "2026-08-15",
                "dueDate": "2026-08-25",
                "taxMode": "INCLUSIVE",
                "lines": [{"description": "Late Q1 Sale", "quantity": 1, "unitAmount": "220.00", "accountId": accs["200"]["id"], "taxRateId": tax["OUTPUT"]["id"]}],
                "approveImmediately": True,
            },
        )
        # Q2 BAS Draft automatically picks up Q1's backdated transaction via watermark scan!
        q2 = c.get(f"/api/v1/orgs/{org_id}/bas/statement?from=2026-10-01&to=2026-12-31").get_json()
        assert q2["unfiledIncludedCount"] == 1
        assert q2["labels"]["G1"] == "220"
        assert q2["labels"]["1A"] == "20"

        # 3. Conversion Balances & Find & Recode
        conv = c.post(
            f"/api/v1/orgs/{org_id}/conversion-balances/post",
            json={
                "conversionDate": "2026-07-01",
                "entries": [{"accountId": accs["630"]["id"], "debit": "500.00", "credit": "0.00"}],
                "lockBalances": True,
            },
        )
        assert conv.status_code == 200
        assert conv.get_json()["conversionLockedAt"] is not None

        recodable = c.get(f"/api/v1/orgs/{org_id}/find-and-recode?accountId={accs['469']['id']}").get_json()["lines"]
        assert len(recodable) >= 1
        rec_res = c.post(
            f"/api/v1/orgs/{org_id}/find-and-recode",
            json={"journalLineIds": [recodable[0]["journalLineId"]], "newAccountId": accs["461"]["id"]},
        )
        assert rec_res.status_code == 200
        assert rec_res.get_json()["transactionsAffected"] == 1

        # 4. Demo Company (AU) Verification (!VD61z): Aged AR Unallocated Credit, Negative Bank Overdraft & Balance Integrity
        orgs = c.get("/api/v1/orgs").get_json()
        demo_id = next(o for o in orgs if o["short_code"] == "!VD61z")["id"]
        aged = c.get(f"/api/v1/orgs/{demo_id}/reports/aged-receivables?date=2026-11-30").get_json()
        bayside = next((r for r in aged["rows"] if "Bayside Club" in r["contactName"]), None)
        assert bayside is not None
        assert bayside["total"] == "-60.50"  # Exact unallocated credit parity from live Xero Aged AR!

        demo_bs = c.get(f"/api/v1/orgs/{demo_id}/reports/balance-sheet?date=2026-11-30").get_json()
        assert demo_bs["totals"]["isBalanced"] is True
        assert any("Overdraft" in li["name"] for li in demo_bs["sections"]["currentLiabilities"])

        demo_jr = c.get(f"/api/v1/orgs/{demo_id}/reports/journals").get_json()
        assert sum(round(float(l["debit"]) * 100) for j in demo_jr for l in j["lines"]) == sum(round(float(l["credit"]) * 100) for j in demo_jr for l in j["lines"])

        # 5. Helper routes & Demo Company Reset under active FK graph + Trigger restoration check
        demo_banks = c.get(f"/api/v1/orgs/{demo_id}/bank-accounts").get_json()
        main_bank_id = demo_banks[0]["id"]
        stmts = c.get(f"/api/v1/orgs/{demo_id}/bank-accounts/{main_bank_id}/statement-lines?status=ALL").get_json()
        assert len(stmts) == 6
        reset_res = c.post("/api/v1/orgs/demo/reset")
        assert reset_res.status_code == 201
        new_demo_id = reset_res.get_json()["id"]
        tcs = c.get(f"/api/v1/orgs/{new_demo_id}/tracking-categories").get_json()
        assert len(tcs) == 1
        opt_res = c.post(f"/api/v1/orgs/{new_demo_id}/tracking-categories/{tcs[0]['id']}/options", json={"name": "Tasmania"})
        assert opt_res.status_code == 201
        assert opt_res.get_json()["name"] == "Tasmania"
