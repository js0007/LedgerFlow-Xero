"""Invoices, Bills, Credit Notes, Quotes, POs, Payments, Banking, Manual Journals, Reports, BAS & Audit Routes."""

from __future__ import annotations

import json
from datetime import date

from flask import Blueprint, g, jsonify, request

from ..db import ApiError, check_idempotency, save_idempotency
from ..money import cents_from_value
from ..services import banking, bas, documents, manual_journals, reports
from .core_routes import get_actor

acc_bp = Blueprint("accounting", __name__, url_prefix="/api/v1")


def _idempotent(conn, org_id: str, handler):
    key = request.headers.get("Idempotency-Key")
    payload = request.get_json(silent=True) or {}
    cached = check_idempotency(conn, org_id, key, payload)
    if cached is not None:
        return jsonify(cached[1]), cached[0]
    status, body = handler(payload)
    save_idempotency(conn, org_id, key, payload, status, body)
    return jsonify(body), status


# --- Manual Journals ---
@acc_bp.get("/orgs/<org_id>/manual-journals")
def list_mj(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(manual_journals.list_manual_journals(conn, org_id, request.args.get("status")))


@acc_bp.post("/orgs/<org_id>/manual-journals")
def create_mj(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    return _idempotent(
        conn, org_id,
        lambda body: (201, manual_journals.create_manual_journal(conn, org_id=org_id, payload=body, actor_user_id=uid, actor_name=uname, actor_role=role)),
    )


@acc_bp.get("/orgs/<org_id>/manual-journals/<mj_id>")
def get_mj(org_id: str, mj_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(manual_journals.get_manual_journal(conn, org_id, mj_id))


@acc_bp.patch("/orgs/<org_id>/manual-journals/<mj_id>")
def patch_mj(org_id: str, mj_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(manual_journals.update_manual_journal(conn, org_id=org_id, mj_id=mj_id, payload=body, actor_user_id=uid, actor_name=uname, actor_role=role))


@acc_bp.post("/orgs/<org_id>/manual-journals/<mj_id>/post")
def post_mj(org_id: str, mj_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    return jsonify(manual_journals.post_manual_journal(conn, org_id=org_id, mj_id=mj_id, actor_user_id=uid, actor_name=uname, actor_role=role))


@acc_bp.post("/orgs/<org_id>/manual-journals/<mj_id>/void")
def void_mj(org_id: str, mj_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    return jsonify(manual_journals.void_manual_journal(conn, org_id=org_id, mj_id=mj_id, actor_user_id=uid, actor_name=uname, actor_role=role))


# --- Quotes & Purchase Orders ---
@acc_bp.get("/orgs/<org_id>/quotes")
def list_quotes(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    rows = conn.execute("SELECT id FROM quotes WHERE org_id = ? ORDER BY issue_date DESC", (org_id,)).fetchall()
    return jsonify([documents._get_commercial_doc(conn, org_id, "quotes", "quote_lines", "quote_id", r["id"]) for r in rows])


@acc_bp.post("/orgs/<org_id>/quotes")
def create_quote(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(documents.create_quote(conn, org_id=org_id, payload=body, actor_user_id=uid, actor_name=uname, actor_role=role)), 201


@acc_bp.post("/orgs/<org_id>/quotes/<quote_id>/convert")
def convert_quote(org_id: str, quote_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(silent=True) or {}
    return jsonify(documents.convert_quote_to_invoice(conn, org_id=org_id, quote_id=quote_id, approve=bool(body.get("approve", False)), actor_user_id=uid, actor_name=uname, actor_role=role))


@acc_bp.get("/orgs/<org_id>/purchase-orders")
def list_pos(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    rows = conn.execute("SELECT id FROM purchase_orders WHERE org_id = ? ORDER BY issue_date DESC", (org_id,)).fetchall()
    return jsonify([documents._get_commercial_doc(conn, org_id, "purchase_orders", "purchase_order_lines", "purchase_order_id", r["id"]) for r in rows])


@acc_bp.post("/orgs/<org_id>/purchase-orders")
def create_po(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(documents.create_purchase_order(conn, org_id=org_id, payload=body, actor_user_id=uid, actor_name=uname, actor_role=role)), 201


@acc_bp.post("/orgs/<org_id>/purchase-orders/<po_id>/convert")
def convert_po(org_id: str, po_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(silent=True) or {}
    return jsonify(documents.convert_po_to_bill(conn, org_id=org_id, po_id=po_id, approve=bool(body.get("approve", False)), actor_user_id=uid, actor_name=uname, actor_role=role))


# --- Invoices, Bills, Credit Notes, Allocations & Payments ---
@acc_bp.get("/orgs/<org_id>/invoices")
def list_invoices(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(
        documents.list_invoices(
            conn,
            org_id,
            invoice_type=request.args.get("invoiceType"),
            status=request.args.get("status"),
            contact_id=request.args.get("contactId"),
        )
    )


@acc_bp.post("/orgs/<org_id>/invoices")
def create_invoice(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    return _idempotent(
        conn, org_id,
        lambda body: (201, documents.create_invoice(conn, org_id=org_id, payload=body, actor_user_id=uid, actor_name=uname, actor_role=role)),
    )


@acc_bp.get("/orgs/<org_id>/invoices/<invoice_id>")
def get_invoice(org_id: str, invoice_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(documents.get_invoice(conn, org_id, invoice_id))


@acc_bp.patch("/orgs/<org_id>/invoices/<invoice_id>")
def update_invoice(org_id: str, invoice_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(documents.update_draft_invoice(conn, org_id=org_id, invoice_id=invoice_id, payload=body, actor_user_id=uid, actor_name=uname, actor_role=role))


@acc_bp.post("/orgs/<org_id>/invoices/<invoice_id>/approve")
def approve_invoice(org_id: str, invoice_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    return _idempotent(
        conn, org_id,
        lambda _: (200, documents.approve_invoice(conn, org_id=org_id, invoice_id=invoice_id, actor_user_id=uid, actor_name=uname, actor_role=role)),
    )


@acc_bp.post("/orgs/<org_id>/invoices/<invoice_id>/void")
def void_invoice(org_id: str, invoice_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    return jsonify(documents.void_invoice(conn, org_id=org_id, invoice_id=invoice_id, actor_user_id=uid, actor_name=uname, actor_role=role))


@acc_bp.post("/orgs/<org_id>/invoices/<credit_note_id>/allocate")
def allocate_cn(org_id: str, credit_note_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(
        documents.allocate_credit_note(
            conn,
            org_id=org_id,
            credit_note_id=credit_note_id,
            allocations=body.get("allocations", []),
            allocation_date=body.get("allocationDate"),
            actor_user_id=uid,
            actor_name=uname,
            actor_role=role,
        )
    )


@acc_bp.post("/orgs/<org_id>/payments")
def record_payment_route(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    res = documents.record_payment(
        conn,
        org_id=org_id,
        invoice_id=body["invoiceId"],
        bank_account_id=body["bankAccountId"],
        payment_date=body.get("paymentDate") or date.today().isoformat(),
        amount_cents=cents_from_value(body["amount"]),
        reference=body.get("reference"),
        actor_user_id=uid,
        actor_name=uname,
        actor_role=role,
    )
    return jsonify(res), 201


@acc_bp.delete("/orgs/<org_id>/payments/<payment_id>")
def delete_payment_route(org_id: str, payment_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    return jsonify(documents.delete_payment(conn, org_id=org_id, payment_id=payment_id, actor_user_id=uid, actor_name=uname, actor_role=role))


# --- Banking, CSV Import, Reconcile, Cash Coding & Bank Rules ---
@acc_bp.get("/orgs/<org_id>/bank-accounts")
def list_bank_accounts_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(banking.list_bank_accounts(conn, org_id))


@acc_bp.get("/orgs/<org_id>/bank-accounts/<bank_account_id>/transactions")
def list_bank_transactions_route(org_id: str, bank_account_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(banking.list_bank_transactions(conn, org_id, bank_account_id))


@acc_bp.get("/orgs/<org_id>/bank-accounts/<bank_account_id>/statement-lines")
def list_statement_lines_route(org_id: str, bank_account_id: str):
    conn = g.db
    get_actor(conn, org_id)
    status = request.args.get("status")
    sql = "SELECT * FROM bank_statement_lines WHERE org_id = ? AND bank_account_id = ? AND reconcile_status != 'DELETED'"
    params: list[object] = [org_id, bank_account_id]
    if status and status.upper() != "ALL":
        sql += " AND reconcile_status = ?"
        params.append(status.upper())
    sql += " ORDER BY tx_date DESC, created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    return jsonify(
        [
            {
                "id": r["id"],
                "txDate": r["tx_date"],
                "amount": f"{int(r['amount_cents']) / 100:.2f}",
                "payee": r["payee"],
                "description": r["description"],
                "reference": r["reference"],
                "occurrenceIdx": r["occurrence_idx"],
                "reconcileStatus": r["reconcile_status"],
                "matchedEntityType": r["matched_entity_type"],
                "matchedEntityId": r["matched_entity_id"],
                "reconciledAt": r["reconciled_at"],
                "version": r["version"],
            }
            for r in rows
        ]
    )


@acc_bp.post("/orgs/<org_id>/bank-accounts/<bank_account_id>/statement-lines/import")
def import_statement_lines_route(org_id: str, bank_account_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(
        banking.import_statement_lines(
            conn, org_id=org_id, bank_account_id=bank_account_id,
            csv_text=body.get("csvText"), rows=body.get("rows"),
            actor_user_id=uid, actor_name=uname, actor_role=role,
        )
    ), 201


@acc_bp.get("/orgs/<org_id>/bank-accounts/<bank_account_id>/suggestions")
def bank_suggestions_route(org_id: str, bank_account_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(banking.get_reconciliation_suggestions(conn, org_id, bank_account_id))


@acc_bp.post("/orgs/<org_id>/bank-accounts/<bank_account_id>/reconcile")
def reconcile_route(org_id: str, bank_account_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    return _idempotent(
        conn, org_id,
        lambda body: (200, banking.reconcile_statement_line(conn, org_id=org_id, bank_account_id=bank_account_id, payload=body, actor_user_id=uid, actor_name=uname, actor_role=role)),
    )


@acc_bp.post("/orgs/<org_id>/bank-accounts/<bank_account_id>/cash-coding/apply")
def cash_coding_route(org_id: str, bank_account_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(banking.cash_coding_batch_apply(conn, org_id=org_id, bank_account_id=bank_account_id, items=body.get("items", []), actor_user_id=uid, actor_name=uname, actor_role=role))


@acc_bp.post("/orgs/<org_id>/bank-accounts/<bank_account_id>/unreconcile")
def unreconcile_route(org_id: str, bank_account_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(banking.unreconcile_statement_line(conn, org_id=org_id, bank_account_id=bank_account_id, stmt_id=body["statementLineId"], actor_user_id=uid, actor_name=uname, actor_role=role))


@acc_bp.post("/orgs/<org_id>/bank-accounts/<bank_account_id>/remove-redo")
def remove_redo_route(org_id: str, bank_account_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(banking.remove_and_redo_statement_line(conn, org_id=org_id, bank_account_id=bank_account_id, stmt_id=body["statementLineId"], actor_user_id=uid, actor_name=uname, actor_role=role))


@acc_bp.get("/orgs/<org_id>/bank-rules")
def list_bank_rules_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(banking.list_bank_rules(conn, org_id))


@acc_bp.post("/orgs/<org_id>/bank-rules")
def create_bank_rule_route(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(banking.save_bank_rule(conn, org_id=org_id, payload=body, rule_id=None, actor_user_id=uid, actor_name=uname, actor_role=role)), 201


@acc_bp.put("/orgs/<org_id>/bank-rules/<rule_id>")
def update_bank_rule_route(org_id: str, rule_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(banking.save_bank_rule(conn, org_id=org_id, payload=body, rule_id=rule_id, actor_user_id=uid, actor_name=uname, actor_role=role))


@acc_bp.delete("/orgs/<org_id>/bank-rules/<rule_id>")
def archive_bank_rule_route(org_id: str, rule_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    banking.archive_bank_rule(conn, org_id=org_id, rule_id=rule_id, actor_user_id=uid, actor_name=uname, actor_role=role)
    return jsonify({"archived": True})


# --- Reports, Conversion Balances, Find & Recode, BAS & Audit ---
@acc_bp.get("/orgs/<org_id>/reports/trial-balance")
def trial_balance_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(reports.get_trial_balance(conn, org_id=org_id, as_of_date=request.args.get("date") or date.today().isoformat()))


@acc_bp.get("/orgs/<org_id>/reports/profit-and-loss")
def pnl_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    today = date.today()
    return jsonify(
        reports.get_profit_and_loss(
            conn, org_id=org_id,
            from_date=request.args.get("from") or f"{today.year}-07-01" if today.month >= 7 else f"{today.year-1}-07-01",
            to_date=request.args.get("to") or today.isoformat(),
            basis=request.args.get("basis") or "ACCRUAL",
            tracking_option_id=request.args.get("trackingOptionId"),
        )
    )


@acc_bp.get("/orgs/<org_id>/reports/balance-sheet")
def bs_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(reports.get_balance_sheet(conn, org_id=org_id, as_of_date=request.args.get("date") or date.today().isoformat()))


@acc_bp.get("/orgs/<org_id>/reports/journals")
def journals_report_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(reports.get_journal_report(conn, org_id=org_id, from_date=request.args.get("from"), to_date=request.args.get("to")))


@acc_bp.get("/orgs/<org_id>/reports/account-transactions")
def account_tx_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(
        reports.get_account_transactions(
            conn, org_id=org_id, account_id=request.args.get("accountId"),
            from_date=request.args.get("from"), to_date=request.args.get("to"),
        )
    )


@acc_bp.get("/orgs/<org_id>/reports/aged-receivables")
def aged_ar_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(
        reports.get_aged_report(
            conn, org_id=org_id, report_kind="RECEIVABLES",
            as_of_date=request.args.get("date") or date.today().isoformat(),
            aging_by=request.args.get("agingBy") or "DUE_DATE",
        )
    )


@acc_bp.get("/orgs/<org_id>/reports/aged-payables")
def aged_ap_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(
        reports.get_aged_report(
            conn, org_id=org_id, report_kind="PAYABLES",
            as_of_date=request.args.get("date") or date.today().isoformat(),
            aging_by=request.args.get("agingBy") or "DUE_DATE",
        )
    )


@acc_bp.get("/orgs/<org_id>/analytics/cash-flow")
def cash_flow_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(reports.get_cash_flow_projection(conn, org_id=org_id, days=int(request.args.get("days", 30))))


@acc_bp.get("/orgs/<org_id>/conversion-balances")
def get_conv_bal_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(reports.get_conversion_balances(conn, org_id))


@acc_bp.post("/orgs/<org_id>/conversion-balances/post")
def post_conv_bal_route(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(
        reports.post_conversion_balances(
            conn, org_id=org_id, conversion_date=body["conversionDate"],
            entries=body.get("entries", []), lock_balances=bool(body.get("lockBalances", False)),
            actor_user_id=uid, actor_name=uname, actor_role=role,
        )
    )


@acc_bp.get("/orgs/<org_id>/find-and-recode")
def search_recode_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(
        {
            "lines": reports.search_recodable_lines(conn, org_id=org_id, account_id=request.args.get("accountId"), tax_rate_id=request.args.get("taxRateId")),
            "history": [dict(r) for r in conn.execute("SELECT * FROM find_recode_batches WHERE org_id = ? ORDER BY created_at DESC", (org_id,)).fetchall()],
        }
    )


@acc_bp.post("/orgs/<org_id>/find-and-recode")
def apply_recode_route(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    body = request.get_json(force=True)
    return jsonify(
        reports.apply_find_and_recode(
            conn, org_id=org_id, journal_line_ids=body.get("journalLineIds", []),
            new_account_id=body.get("newAccountId"), new_tracking1_id=body.get("newTracking1OptionId"),
            actor_user_id=uid, actor_name=uname, actor_role=role,
        )
    )


@acc_bp.get("/orgs/<org_id>/bas/statement")
def get_bas_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    p_start = request.args.get("from") or "2026-10-01"
    p_end = request.args.get("to") or "2026-12-31"
    return jsonify(bas.compute_bas_statement(conn, org_id=org_id, period_start=p_start, period_end=p_end))


@acc_bp.post("/orgs/<org_id>/bas/statement/finalise")
def finalise_bas_route(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    return _idempotent(
        conn, org_id,
        lambda body: (200, bas.finalise_bas_statement(conn, org_id=org_id, period_start=body["from"], period_end=body["to"], actor_user_id=uid, actor_name=uname, actor_role=role)),
    )


@acc_bp.get("/orgs/<org_id>/bas/history")
def list_bas_history_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(bas.list_bas_history(conn, org_id))


@acc_bp.get("/orgs/<org_id>/audit-logs")
def list_audit_logs_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    rows = conn.execute("SELECT * FROM audit_logs WHERE org_id = ? ORDER BY created_at DESC LIMIT 200", (org_id,)).fetchall()
    return jsonify([dict(r) for r in rows])


@acc_bp.get("/orgs/<org_id>/assurance")
def assurance_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    return jsonify(reports.get_assurance_summary(conn, org_id))


@acc_bp.get("/orgs/<org_id>/connected-apps")
def list_connected_apps_route(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    rows = conn.execute("SELECT * FROM connected_apps WHERE org_id = ? ORDER BY connected_at DESC", (org_id,)).fetchall()
    return jsonify([{**dict(r), "scopes": json.loads(r["scopes_json"])} for r in rows])
