"""Core Platform, Auth/RBAC, Org Settings, COA, TaxRates, Products, Contacts & Tracking Routes."""

from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, g, jsonify, request

from ..db import ApiError, atomic_tx, new_id, utc_now_iso
from ..demo_seed import seed_demo_company_au
from ..money import decimal_str_from_cents
from ..seed import create_organisation_with_au_seed
from ..services.ledger import assert_can_write, parse_iso_date, write_audit

core_bp = Blueprint("core", __name__, url_prefix="/api/v1")


def get_actor(conn, org_id: str) -> tuple[str, str, str]:
    user = conn.execute("SELECT * FROM users ORDER BY created_at LIMIT 1").fetchone()
    if user is None:
        raise ApiError(401, "NO_USER", "Session user not found.")
    mem = conn.execute(
        "SELECT role FROM org_memberships WHERE org_id = ? AND user_id = ?",
        (org_id, user["id"]),
    ).fetchone()
    if mem is None:
        raise ApiError(403, "ORG_ACCESS_DENIED", "User is not a member of this organisation.")
    # Allow explicit header override only for role testing if valid, otherwise use persisted membership role!
    role = mem["role"]
    return user["id"], user["display_name"], role


@core_bp.get("/health")
def health():
    return jsonify({"status": "ok", "engine": "python-flask-sqlite"})


@core_bp.get("/auth/me")
def auth_me():
    conn = g.db
    user = conn.execute("SELECT id, email, display_name FROM users ORDER BY created_at LIMIT 1").fetchone()
    orgs = conn.execute(
        """
        SELECT o.id, o.short_code, o.display_name, o.country_code, o.base_currency, o.abn, m.role
        FROM organisations o JOIN org_memberships m ON m.org_id = o.id
        WHERE m.user_id = ? ORDER BY o.created_at
        """,
        (user["id"],),
    ).fetchall()
    return jsonify(
        {
            "user": {"id": user["id"], "email": user["email"], "displayName": user["display_name"]},
            "organisations": [
                {
                    "id": o["id"],
                    "shortCode": o["short_code"],
                    "displayName": o["display_name"],
                    "countryCode": o["country_code"],
                    "baseCurrency": o["base_currency"],
                    "abn": o["abn"],
                    "role": o["role"],
                }
                for o in orgs
            ],
        }
    )


@core_bp.post("/auth/switch-role")
def switch_role():
    conn = g.db
    body = request.get_json(force=True)
    org_id = body.get("orgId")
    new_role = (body.get("role") or "").upper()
    if new_role not in ("ADVISER", "STANDARD", "READONLY"):
        raise ApiError(400, "INVALID_ROLE", "Role must be ADVISER, STANDARD, or READONLY.")
    user_id, actor_name, _ = get_actor(conn, org_id)
    with atomic_tx(conn):
        conn.execute(
            "UPDATE org_memberships SET role = ? WHERE org_id = ? AND user_id = ?",
            (new_role, org_id, user_id),
        )
        write_audit(conn, org_id, user_id, actor_name, "USER_ROLE", user_id, "ROLE_CHANGED", f"Active role switched to {new_role}.")
    return jsonify({"orgId": org_id, "role": new_role})


@core_bp.get("/orgs")
def list_orgs():
    conn = g.db
    rows = conn.execute("SELECT id, short_code, display_name, legal_name, country_code, base_currency, abn FROM organisations ORDER BY created_at").fetchall()
    return jsonify([dict(r) for r in rows])


@core_bp.post("/orgs")
def create_org():
    conn = g.db
    body = request.get_json(force=True)
    name = (body.get("displayName") or "").strip()
    if not name:
        raise ApiError(422, "NAME_REQUIRED", "Organisation displayName is required.")
    user = conn.execute("SELECT * FROM users ORDER BY created_at LIMIT 1").fetchone()
    short_code = (body.get("shortCode") or f"!{new_id()[:4].upper()}!")
    org = create_organisation_with_au_seed(
        conn,
        display_name=name,
        short_code=short_code,
        owner_user_id=user["id"],
        owner_name=user["display_name"],
        legal_name=body.get("legalName"),
        abn=body.get("abn"),
        industry=body.get("industry"),
        role=(body.get("role") or "ADVISER").upper(),
    )
    return jsonify(org), 201


@core_bp.post("/orgs/demo/reset")
def create_or_reset_demo():
    conn = g.db
    org = seed_demo_company_au(conn, replace_existing=True)
    return jsonify(org), 201


@core_bp.get("/orgs/<org_id>/dashboard")
def get_dashboard(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    from ..services.banking import list_bank_accounts
    from datetime import date

    today_str = date.today().isoformat()
    org = conn.execute("SELECT * FROM organisations WHERE id = ?", (org_id,)).fetchone()
    banks = list_bank_accounts(conn, org_id)

    ar_row = conn.execute(
        """
        SELECT COUNT(CASE WHEN invoice_type = 'ACCREC' THEN 1 END) AS cnt,
               COALESCE(SUM(
                   CASE WHEN invoice_type = 'ACCREC' THEN (total_cents - amount_paid_cents - amount_credited_cents)
                        WHEN invoice_type = 'ACCRECCREDIT' THEN -(total_cents - amount_paid_cents - amount_credited_cents)
                        ELSE 0 END
               ), 0) AS due_cents,
               COALESCE(SUM(CASE WHEN invoice_type = 'ACCREC' AND due_date < ? THEN total_cents - amount_paid_cents - amount_credited_cents ELSE 0 END), 0) AS overdue_cents,
               COUNT(CASE WHEN invoice_type = 'ACCREC' AND due_date < ? THEN 1 END) AS overdue_cnt
        FROM invoices WHERE org_id = ? AND invoice_type IN ('ACCREC', 'ACCRECCREDIT') AND status = 'AUTHORISED'
        """,
        (today_str, today_str, org_id),
    ).fetchone()
    ap_row = conn.execute(
        """
        SELECT COUNT(CASE WHEN invoice_type = 'ACCPAY' THEN 1 END) AS cnt,
               COALESCE(SUM(
                   CASE WHEN invoice_type = 'ACCPAY' THEN (total_cents - amount_paid_cents - amount_credited_cents)
                        WHEN invoice_type = 'ACCPAYCREDIT' THEN -(total_cents - amount_paid_cents - amount_credited_cents)
                        ELSE 0 END
               ), 0) AS due_cents,
               COALESCE(SUM(CASE WHEN invoice_type = 'ACCPAY' AND due_date < ? THEN total_cents - amount_paid_cents - amount_credited_cents ELSE 0 END), 0) AS overdue_cents,
               COUNT(CASE WHEN invoice_type = 'ACCPAY' AND due_date < ? THEN 1 END) AS overdue_cnt
        FROM invoices WHERE org_id = ? AND invoice_type IN ('ACCPAY', 'ACCPAYCREDIT') AND status = 'AUTHORISED'
        """,
        (today_str, today_str, org_id),
    ).fetchone()

    watchlist = conn.execute(
        """
        SELECT a.id, a.code, a.name, a.account_class,
               COALESCE(SUM(jl.debit_cents - jl.credit_cents), 0) AS net_dr
        FROM accounts a
        LEFT JOIN journal_lines jl ON jl.account_id = a.id
        WHERE a.org_id = ? AND a.show_on_watchlist = 1 AND a.status = 'ACTIVE'
        GROUP BY a.id ORDER BY a.code
        """,
        (org_id,),
    ).fetchall()

    recent_payments = conn.execute(
        """
        SELECT p.payment_date, p.amount_cents, i.invoice_number, c.name AS contact_name
        FROM payments p JOIN invoices i ON i.id = p.invoice_id JOIN contacts c ON c.id = i.contact_id
        WHERE p.org_id = ? AND p.status = 'AUTHORISED' AND i.invoice_type = 'ACCREC'
        ORDER BY p.payment_date DESC, p.created_at DESC LIMIT 5
        """,
        (org_id,),
    ).fetchall()

    return jsonify(
        {
            "organisation": {"id": org["id"], "shortCode": org["short_code"], "displayName": org["display_name"], "abn": org["abn"]},
            "bankAccounts": banks,
            "receivables": {
                "awaitingCount": int(ar_row["cnt"]),
                "awaitingAmount": decimal_str_from_cents(int(ar_row["due_cents"])),
                "overdueCount": int(ar_row["overdue_cnt"]),
                "overdueAmount": decimal_str_from_cents(int(ar_row["overdue_cents"])),
            },
            "payables": {
                "awaitingCount": int(ap_row["cnt"]),
                "awaitingAmount": decimal_str_from_cents(int(ap_row["due_cents"])),
                "overdueCount": int(ap_row["overdue_cnt"]),
                "overdueAmount": decimal_str_from_cents(int(ap_row["overdue_cents"])),
            },
            "watchlist": [
                {
                    "id": w["id"],
                    "code": w["code"],
                    "name": w["name"],
                    "ytd": decimal_str_from_cents(int(w["net_dr"]) if w["account_class"] in ("ASSET", "EXPENSE") else -int(w["net_dr"])),
                }
                for w in watchlist
            ],
            "recentInvoicePayments": [
                {
                    "invoiceNumber": rp["invoice_number"],
                    "contactName": rp["contact_name"],
                    "date": rp["payment_date"],
                    "amount": decimal_str_from_cents(rp["amount_cents"]),
                }
                for rp in recent_payments
            ],
        }
    )


# --- Organisation & Financial Settings ---
@core_bp.get("/orgs/<org_id>/settings/organisation")
def get_org_details(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    org = conn.execute("SELECT * FROM organisations WHERE id = ?", (org_id,)).fetchone()
    settings = conn.execute("SELECT invoice_prefix, next_invoice_seq, credit_note_prefix, quote_prefix, po_prefix FROM org_settings WHERE org_id = ?", (org_id,)).fetchone()
    return jsonify({**dict(org), **dict(settings)})


@core_bp.patch("/orgs/<org_id>/settings/organisation")
def update_org_details(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    body = request.get_json(force=True)
    with atomic_tx(conn):
        conn.execute(
            """
            UPDATE organisations SET display_name=COALESCE(?, display_name), legal_name=COALESCE(?, legal_name),
            abn=COALESCE(?, abn), industry=COALESCE(?, industry), postal_address=COALESCE(?, postal_address)
            WHERE id=?
            """,
            (body.get("displayName"), body.get("legalName"), body.get("abn"), body.get("industry"), body.get("postalAddress"), org_id),
        )
        if body.get("invoicePrefix"):
            conn.execute("UPDATE org_settings SET invoice_prefix=?, updated_at=? WHERE org_id=?", (body["invoicePrefix"], utc_now_iso(), org_id))
        write_audit(conn, org_id, uid, uname, "ORGANISATION", org_id, "UPDATED", "Organisation details updated.")
    return get_org_details(org_id)


@core_bp.get("/orgs/<org_id>/settings/financial")
def get_financial_settings(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    s = conn.execute("SELECT * FROM org_settings WHERE org_id = ?", (org_id,)).fetchone()
    return jsonify(
        {
            "orgId": s["org_id"],
            "fyEndMonth": s["fy_end_month"],
            "fyEndDay": s["fy_end_day"],
            "gstAccountingMethod": s["gst_accounting_method"],
            "basReportingType": s["bas_reporting_type"],
            "basCalculationPeriod": s["bas_calculation_period"],
            "basG1Mode": s["bas_g1_mode"],
            "salesTaxDefault": s["sales_tax_default"],
            "purchasesTaxDefault": s["purchases_tax_default"],
            "softLockDate": s["soft_lock_date"],
            "hardLockDate": s["hard_lock_date"],
            "updatedAt": s["updated_at"],
        }
    )


@core_bp.patch("/orgs/<org_id>/settings/financial")
def patch_financial_settings(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    body = request.get_json(force=True)
    curr = conn.execute("SELECT * FROM org_settings WHERE org_id = ?", (org_id,)).fetchone()

    lock_touching = ("softLockDate" in body or "hardLockDate" in body)
    if lock_touching and role.upper() != "ADVISER":
        raise ApiError(403, "ADVISER_REQUIRED", "Only Advisers can modify Lock Dates.")

    soft = body["softLockDate"] if "softLockDate" in body else curr["soft_lock_date"]
    hard = body["hardLockDate"] if "hardLockDate" in body else curr["hard_lock_date"]
    if soft:
        parse_iso_date(soft)
    if hard:
        parse_iso_date(hard)
    if soft and hard and parse_iso_date(hard) > parse_iso_date(soft):
        raise ApiError(422, "INVALID_LOCK_HIERARCHY", "Hard lock date cannot be after soft lock date.")

    method = (body.get("gstAccountingMethod") or curr["gst_accounting_method"]).upper()
    g1_mode = (body.get("basG1Mode") or curr["bas_g1_mode"]).upper()
    sales_def = (body.get("salesTaxDefault") or curr["sales_tax_default"]).upper()
    purch_def = (body.get("purchasesTaxDefault") or curr["purchases_tax_default"]).upper()
    fy_m = int(body.get("fyEndMonth") or curr["fy_end_month"])
    fy_d = int(body.get("fyEndDay") or curr["fy_end_day"])

    with atomic_tx(conn):
        conn.execute(
            """
            UPDATE org_settings SET fy_end_month=?, fy_end_day=?, gst_accounting_method=?, bas_g1_mode=?,
            sales_tax_default=?, purchases_tax_default=?, soft_lock_date=?, hard_lock_date=?, updated_at=?
            WHERE org_id=?
            """,
            (fy_m, fy_d, method, g1_mode, sales_def, purch_def, soft, hard, utc_now_iso(), org_id),
        )
        write_audit(
            conn, org_id, uid, uname, "FINANCIAL_SETTINGS", org_id, "UPDATED",
            f"Financial settings updated (Method={method}, G1={g1_mode}, SoftLock={soft}, HardLock={hard}).",
            {"softLockDate": soft, "hardLockDate": hard, "gstAccountingMethod": method, "basG1Mode": g1_mode},
        )
    return get_financial_settings(org_id)


# --- COA, Tax Rates, Products & Tracking ---
@core_bp.get("/orgs/<org_id>/accounts")
def list_accounts(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    excl_mj = request.args.get("excludeManualExcluded", "").lower() in ("true", "1")
    include_archived = request.args.get("includeArchived", "").lower() in ("true", "1")

    sql = """
        SELECT a.*, tr.name AS default_tax_name, tr.code AS default_tax_code,
               COALESCE(SUM(jl.debit_cents - jl.credit_cents), 0) AS net_dr_cents
        FROM accounts a
        LEFT JOIN tax_rates tr ON tr.id = a.default_tax_rate_id
        LEFT JOIN journal_lines jl ON jl.account_id = a.id
        WHERE a.org_id = ?
    """
    params: list[Any] = [org_id]
    if not include_archived:
        sql += " AND a.status = 'ACTIVE'"
    if excl_mj:
        sql += " AND a.manual_journal_excluded = 0 AND a.account_type != 'BANK'"
    sql += " GROUP BY a.id ORDER BY a.code, a.name"

    rows = conn.execute(sql, params).fetchall()
    return jsonify(
        [
            {
                "id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "accountClass": r["account_class"],
                "accountType": r["account_type"],
                "systemAccount": r["system_account"],
                "isSystemLocked": bool(r["is_system_locked"]),
                "manualJournalExcluded": bool(r["manual_journal_excluded"]),
                "enablePaymentsToAccount": bool(r["enable_payments_to_account"]),
                "showOnWatchlist": bool(r["show_on_watchlist"]),
                "defaultTaxRateId": r["default_tax_rate_id"],
                "defaultTaxName": r["default_tax_name"],
                "defaultTaxCode": r["default_tax_code"],
                "description": r["description"],
                "bankAccountNumber": r["bank_account_number"],
                "status": r["status"],
                "ytdBalance": decimal_str_from_cents(int(r["net_dr_cents"]) if r["account_class"] in ("ASSET", "EXPENSE") else -int(r["net_dr_cents"])),
            }
            for r in rows
        ]
    )


@core_bp.post("/orgs/<org_id>/accounts")
def create_account(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    body = request.get_json(force=True)
    raw_type = (body.get("accountType") or "EXPENSE").upper()
    acc_type = "EXPENSE" if raw_type == "OVERHEADS" else raw_type
    class_for_type = {
        "BANK": "ASSET", "CURRENT": "ASSET", "INVENTORY": "ASSET", "FIXED": "ASSET",
        "CURRLIAB": "LIABILITY", "TERMLIAB": "LIABILITY", "EQUITY": "EQUITY",
        "REVENUE": "REVENUE", "OTHERINCOME": "REVENUE", "DIRECTCOSTS": "EXPENSE", "EXPENSE": "EXPENSE",
    }
    if acc_type not in class_for_type:
        raise ApiError(400, "INVALID_ACCOUNT_TYPE", f"Invalid accountType '{acc_type}'.")
    acc_class = class_for_type[acc_type]
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(422, "NAME_REQUIRED", "Account name is required.")
    code = (body.get("code") or "").strip() or None
    aid = new_id()
    is_bank = acc_type == "BANK"
    with atomic_tx(conn):
        try:
            conn.execute(
                """
                INSERT INTO accounts (
                    id, org_id, code, name, account_class, account_type,
                    is_system_locked, manual_journal_excluded, enable_payments_to_account,
                    show_on_watchlist, default_tax_rate_id, description, bank_account_number, bank_currency, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
                """,
                (
                    aid, org_id, code, name, acc_class, acc_type,
                    1 if is_bank else 0, 1 if body.get("enablePaymentsToAccount") else 0,
                    1 if body.get("showOnWatchlist") else 0, body.get("defaultTaxRateId"),
                    body.get("description"), body.get("bankAccountNumber"), "AUD" if is_bank else None, utc_now_iso(),
                ),
            )
        except Exception as exc:
            raise ApiError(409, "DUPLICATE_ACCOUNT_CODE", f"Account code '{code}' already exists.") from exc
        write_audit(conn, org_id, uid, uname, "ACCOUNT", aid, "CREATED", f"Account '{code or ''} {name}' created.")
    return jsonify({"id": aid, "code": code, "name": name, "accountType": acc_type, "accountClass": acc_class}), 201


@core_bp.patch("/orgs/<org_id>/accounts/<account_id>")
def update_account(org_id: str, account_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    acc = conn.execute("SELECT * FROM accounts WHERE id = ? AND org_id = ?", (account_id, org_id)).fetchone()
    if acc is None:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "Account not found.")
    body = request.get_json(force=True)
    if int(acc["is_system_locked"]) == 1 and body.get("status") == "ARCHIVED":
        raise ApiError(422, "SYSTEM_ACCOUNT_LOCKED", "System-locked accounts cannot be archived.")
    with atomic_tx(conn):
        new_tax_rate_id = (body.get("defaultTaxRateId") or None) if "defaultTaxRateId" in body else acc["default_tax_rate_id"]
        conn.execute(
            """
            UPDATE accounts SET name=COALESCE(?, name), description=COALESCE(?, description),
            default_tax_rate_id=?,
            enable_payments_to_account=COALESCE(?, enable_payments_to_account),
            show_on_watchlist=COALESCE(?, show_on_watchlist),
            status=COALESCE(?, status) WHERE id=? AND org_id=?
            """,
            (
                body.get("name"), body.get("description"), new_tax_rate_id,
                (1 if body["enablePaymentsToAccount"] else 0) if "enablePaymentsToAccount" in body else None,
                (1 if body["showOnWatchlist"] else 0) if "showOnWatchlist" in body else None,
                body.get("status"), account_id, org_id,
            ),
        )
        write_audit(conn, org_id, uid, uname, "ACCOUNT", account_id, "UPDATED", f"Account '{acc['name']}' updated.")
    return jsonify({"id": account_id, "updated": True})


@core_bp.delete("/orgs/<org_id>/accounts/<account_id>")
def delete_account(org_id: str, account_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    acc = conn.execute("SELECT * FROM accounts WHERE id = ? AND org_id = ?", (account_id, org_id)).fetchone()
    if acc is None:
        raise ApiError(404, "ACCOUNT_NOT_FOUND", "Account not found.")
    if int(acc["is_system_locked"]) == 1:
        raise ApiError(422, "SYSTEM_ACCOUNT_LOCKED", "System accounts cannot be deleted.")
    used = conn.execute("SELECT 1 FROM journal_lines WHERE account_id = ? LIMIT 1", (account_id,)).fetchone()
    if used:
        raise ApiError(422, "ACCOUNT_IN_USE", "Accounts with posted journal history cannot be deleted; archive them instead.")
    with atomic_tx(conn):
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        write_audit(conn, org_id, uid, uname, "ACCOUNT", account_id, "DELETED", f"Deleted unused account '{acc['name']}'.")
    return jsonify({"deleted": True})


@core_bp.get("/orgs/<org_id>/tax-rates")
def list_tax_rates(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    include_archived = request.args.get("includeArchived", "").lower() in ("true", "1")
    sql = "SELECT * FROM tax_rates WHERE org_id = ?"
    if not include_archived:
        sql += " AND status = 'ACTIVE'"
    sql += " ORDER BY status, name"
    rows = conn.execute(sql, (org_id,)).fetchall()
    return jsonify(
        [
            {
                "id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "rateDecimal": r["rate_decimal"],
                "ratePercent": str(float(r["rate_decimal"]) * 100),
                "basFields": json.loads(r["bas_field_names_json"]),
                "canApplyToAssets": bool(r["can_apply_to_assets"]),
                "canApplyToEquity": bool(r["can_apply_to_equity"]),
                "canApplyToExpenses": bool(r["can_apply_to_expenses"]),
                "canApplyToLiabilities": bool(r["can_apply_to_liabilities"]),
                "canApplyToRevenue": bool(r["can_apply_to_revenue"]),
                "isSystem": bool(r["is_system"]),
                "status": r["status"],
            }
            for r in rows
        ]
    )


@core_bp.get("/orgs/<org_id>/tracking-categories")
def list_tracking_categories(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    cats = conn.execute("SELECT * FROM tracking_categories WHERE org_id = ? AND status = 'ACTIVE' ORDER BY name", (org_id,)).fetchall()
    out = []
    for c in cats:
        opts = conn.execute("SELECT id, name, status FROM tracking_options WHERE category_id = ? AND status = 'ACTIVE' ORDER BY name", (c["id"],)).fetchall()
        out.append({"id": c["id"], "name": c["name"], "status": c["status"], "options": [dict(o) for o in opts]})
    return jsonify(out)


@core_bp.post("/orgs/<org_id>/tracking-categories")
def create_tracking_category(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(422, "NAME_REQUIRED", "Tracking category name required.")
    cnt = int(conn.execute("SELECT COUNT(*) FROM tracking_categories WHERE org_id = ? AND status = 'ACTIVE'", (org_id,)).fetchone()[0])
    if cnt >= 2:
        raise ApiError(422, "TRACKING_LIMIT_REACHED", "Maximum 2 active tracking categories allowed.")
    cid = new_id()
    with atomic_tx(conn):
        conn.execute("INSERT INTO tracking_categories (id, org_id, name, status) VALUES (?, ?, ?, 'ACTIVE')", (cid, org_id, name))
        opts = []
        for opt_name in body.get("options", []):
            on = opt_name.strip()
            if on:
                oid_opt = new_id()
                conn.execute("INSERT INTO tracking_options (id, org_id, category_id, name, status) VALUES (?, ?, ?, ?, 'ACTIVE')", (oid_opt, org_id, cid, on))
                opts.append({"id": oid_opt, "name": on, "status": "ACTIVE"})
        write_audit(conn, org_id, uid, uname, "TRACKING_CATEGORY", cid, "CREATED", f"Tracking category '{name}' created.")
    return jsonify({"id": cid, "name": name, "options": opts}), 201


@core_bp.post("/orgs/<org_id>/tracking-categories/<category_id>/options")
def add_tracking_option(org_id: str, category_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(422, "NAME_REQUIRED", "Option name required.")
    oid_opt = new_id()
    with atomic_tx(conn):
        conn.execute("INSERT INTO tracking_options (id, org_id, category_id, name, status) VALUES (?, ?, ?, ?, 'ACTIVE')", (oid_opt, org_id, category_id, name))
        write_audit(conn, org_id, uid, uname, "TRACKING_OPTION", oid_opt, "CREATED", f"Tracking option '{name}' added.")
    return jsonify({"id": oid_opt, "name": name, "status": "ACTIVE"}), 201


@core_bp.get("/orgs/<org_id>/products")
def list_products(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    rows = conn.execute("SELECT * FROM products WHERE org_id = ? AND status = 'ACTIVE' ORDER BY code", (org_id,)).fetchall()
    return jsonify(
        [
            {
                "id": r["id"], "code": r["code"], "name": r["name"], "isTracked": bool(r["is_tracked"]),
                "costPrice": r["cost_price_decimal"], "salePrice": r["sale_price_decimal"],
                "purchaseAccountId": r["purchase_account_id"], "purchaseTaxRateId": r["purchase_tax_rate_id"],
                "salesAccountId": r["sales_account_id"], "salesTaxRateId": r["sales_tax_rate_id"],
                "quantityOnHand": f"{int(r['quantity_on_hand_e4']) / 10000:.0f}" if r["is_tracked"] else None,
                "avgCost": decimal_str_from_cents(r["avg_cost_cents"]) if r["is_tracked"] else None,
            }
            for r in rows
        ]
    )


@core_bp.post("/orgs/<org_id>/products")
def create_product(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    body = request.get_json(force=True)
    code = (body.get("code") or "").strip()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise ApiError(422, "PRODUCT_FIELDS_REQUIRED", "Product code and name are required.")
    pid = new_id()
    with atomic_tx(conn):
        try:
            conn.execute(
                """
                INSERT INTO products (id, org_id, code, name, is_tracked, cost_price_decimal, purchase_account_id, purchase_tax_rate_id, sale_price_decimal, sales_account_id, sales_tax_rate_id, status, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
                """,
                (
                    pid, org_id, code, name,
                    body.get("costPrice"), body.get("purchaseAccountId"), body.get("purchaseTaxRateId"),
                    body.get("salePrice"), body.get("salesAccountId"), body.get("salesTaxRateId"), utc_now_iso(),
                ),
            )
        except Exception as exc:
            raise ApiError(409, "DUPLICATE_PRODUCT_CODE", f"Product code '{code}' already exists.") from exc
        write_audit(conn, org_id, uid, uname, "PRODUCT", pid, "CREATED", f"Product/service '{code}' created.")
    return jsonify({"id": pid, "code": code, "name": name}), 201


@core_bp.patch("/orgs/<org_id>/products/<product_id>")
def update_product(org_id: str, product_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    prod = conn.execute("SELECT * FROM products WHERE id = ? AND org_id = ?", (product_id, org_id)).fetchone()
    if prod is None:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "Product not found.")
    body = request.get_json(force=True)
    new_code = (body.get("code") or prod["code"]).strip()
    new_name = (body.get("name") or prod["name"]).strip()
    if not new_code or not new_name:
        raise ApiError(422, "PRODUCT_FIELDS_REQUIRED", "Product code and name cannot be empty.")
    with atomic_tx(conn):
        try:
            conn.execute(
                """
                UPDATE products
                SET code = ?, name = ?,
                    cost_price_decimal = ?, purchase_account_id = ?, purchase_tax_rate_id = ?,
                    sale_price_decimal = ?, sales_account_id = ?, sales_tax_rate_id = ?,
                    status = ?
                WHERE id = ? AND org_id = ?
                """,
                (
                    new_code,
                    new_name,
                    body.get("costPrice", prod["cost_price_decimal"]) if "costPrice" in body else prod["cost_price_decimal"],
                    (body.get("purchaseAccountId") or None) if "purchaseAccountId" in body else prod["purchase_account_id"],
                    (body.get("purchaseTaxRateId") or None) if "purchaseTaxRateId" in body else prod["purchase_tax_rate_id"],
                    body.get("salePrice", prod["sale_price_decimal"]) if "salePrice" in body else prod["sale_price_decimal"],
                    (body.get("salesAccountId") or None) if "salesAccountId" in body else prod["sales_account_id"],
                    (body.get("salesTaxRateId") or None) if "salesTaxRateId" in body else prod["sales_tax_rate_id"],
                    (body.get("status") or prod["status"]).upper(),
                    product_id,
                    org_id,
                ),
            )
        except Exception as exc:
            raise ApiError(409, "DUPLICATE_PRODUCT_CODE", f"Product code '{new_code}' already exists.") from exc
        write_audit(conn, org_id, uid, uname, "PRODUCT", product_id, "UPDATED", f"Product '{new_code}' updated.")
    return jsonify({"id": product_id, "code": new_code, "name": new_name})


@core_bp.delete("/orgs/<org_id>/products/<product_id>")
def archive_product(org_id: str, product_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    prod = conn.execute("SELECT * FROM products WHERE id = ? AND org_id = ?", (product_id, org_id)).fetchone()
    if prod is None:
        raise ApiError(404, "PRODUCT_NOT_FOUND", "Product not found.")
    with atomic_tx(conn):
        conn.execute("UPDATE products SET status = 'ARCHIVED' WHERE id = ? AND org_id = ?", (product_id, org_id))
        write_audit(conn, org_id, uid, uname, "PRODUCT", product_id, "ARCHIVED", f"Product '{prod['code']}' archived.")
    return jsonify({"archived": True})


@core_bp.get("/orgs/<org_id>/contacts")
def list_contacts(org_id: str):
    conn = g.db
    get_actor(conn, org_id)
    rows = conn.execute("SELECT * FROM contacts WHERE org_id = ? AND status = 'ACTIVE' ORDER BY name", (org_id,)).fetchall()
    out = []
    for c in rows:
        bal = conn.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN invoice_type='ACCREC' THEN total_cents - amount_paid_cents - amount_credited_cents
                                WHEN invoice_type='ACCRECCREDIT' THEN -(total_cents - amount_paid_cents - amount_credited_cents) ELSE 0 END), 0) AS they_owe,
              COALESCE(SUM(CASE WHEN invoice_type='ACCPAY' THEN total_cents - amount_paid_cents - amount_credited_cents
                                WHEN invoice_type='ACCPAYCREDIT' THEN -(total_cents - amount_paid_cents - amount_credited_cents) ELSE 0 END), 0) AS you_owe
            FROM invoices WHERE org_id = ? AND contact_id = ? AND status = 'AUTHORISED'
            """,
            (org_id, c["id"]),
        ).fetchone()
        out.append(
            {
                "id": c["id"],
                "name": c["name"],
                "accountNumber": c["account_number"],
                "abn": c["abn"],
                "email": c["email"],
                "phone": c["phone"],
                "address": c["address"],
                "isCustomer": bool(c["is_customer"]),
                "isSupplier": bool(c["is_supplier"]),
                "defaultSalesAccountId": c["default_sales_account_id"],
                "defaultPurchaseAccountId": c["default_purchase_account_id"],
                "defaultSalesTaxRateId": c["default_sales_tax_rate_id"],
                "defaultPurchaseTaxRateId": c["default_purchase_tax_rate_id"],
                "groups": json.loads(c["contact_groups_json"] or "[]"),
                "theyOwe": decimal_str_from_cents(int(bal["they_owe"])),
                "youOwe": decimal_str_from_cents(int(bal["you_owe"])),
            }
        )
    return jsonify(out)


@core_bp.post("/orgs/<org_id>/contacts")
def create_contact(org_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError(422, "NAME_REQUIRED", "Contact name is required.")
    cid = new_id()
    with atomic_tx(conn):
        conn.execute(
            """
            INSERT INTO contacts (id, org_id, name, account_number, abn, email, phone, address, bank_bsb_account, is_customer, is_supplier, default_sales_account_id, default_purchase_account_id, default_sales_tax_rate_id, default_purchase_tax_rate_id, contact_groups_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
            """,
            (
                cid, org_id, name, body.get("accountNumber"), body.get("abn"), body.get("email"), body.get("phone"), body.get("address"),
                body.get("bankBsbAccount"), 1 if body.get("isCustomer") else 0, 1 if body.get("isSupplier") else 0,
                body.get("defaultSalesAccountId"), body.get("defaultPurchaseAccountId"),
                body.get("defaultSalesTaxRateId"), body.get("defaultPurchaseTaxRateId"),
                json.dumps(body.get("groups", [])), utc_now_iso(),
            ),
        )
        write_audit(conn, org_id, uid, uname, "CONTACT", cid, "CREATED", f"Contact '{name}' created.")
    return jsonify({"id": cid, "name": name}), 201


@core_bp.patch("/orgs/<org_id>/contacts/<contact_id>")
def update_contact(org_id: str, contact_id: str):
    conn = g.db
    uid, uname, role = get_actor(conn, org_id)
    assert_can_write(role)
    body = request.get_json(force=True)
    with atomic_tx(conn):
        conn.execute(
            """
            UPDATE contacts SET name=COALESCE(?, name), account_number=COALESCE(?, account_number),
            abn=COALESCE(?, abn), email=COALESCE(?, email), phone=COALESCE(?, phone), status=COALESCE(?, status)
            WHERE id=? AND org_id=?
            """,
            (body.get("name"), body.get("accountNumber"), body.get("abn"), body.get("email"), body.get("phone"), body.get("status"), contact_id, org_id),
        )
        write_audit(conn, org_id, uid, uname, "CONTACT", contact_id, "UPDATED", "Contact updated.")
    return jsonify({"id": contact_id, "updated": True})
