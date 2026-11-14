-- =============================================================================
-- AU Accounting SaaS Blueprint - Authoritative SQLite 3 Schema (Python + Flask)
-- Aligned after Phase 1 Audit & Phase 2 Full-Site Exploration (E01-E44).
-- Principles:
--   1. Multi-tenant isolation via org_id across every business table.
--   2. Zero IEEE-754 floats for financial money: stored as integer minor units
--      (*_cents = AUD * 100) for sums/balances, and DECIMAL text for arbitrary precision.
--   3. Append-Only Immutable GL enforced by SQLite BEFORE UPDATE/DELETE triggers.
--   4. Explicit separation of is_system_locked vs manual_journal_excluded (47/54 rule).
--   5. Complete Credit Note Allocations, Quotes, POs, Bank Rules, Products, & Recode Audit.
-- =============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- -----------------------------------------------------------------------------
-- 1. Organisations, Settings, Counters & Users/RBAC
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organisations (
    id              TEXT PRIMARY KEY,
    short_code      TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    legal_name      TEXT,
    country_code    TEXT NOT NULL DEFAULT 'AU',
    base_currency   TEXT NOT NULL DEFAULT 'AUD',
    abn             TEXT,
    industry        TEXT,
    postal_address  TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS org_settings (
    org_id                  TEXT PRIMARY KEY REFERENCES organisations(id) ON DELETE CASCADE,
    fy_end_month            INTEGER NOT NULL DEFAULT 6 CHECK (fy_end_month BETWEEN 1 AND 12),
    fy_end_day              INTEGER NOT NULL DEFAULT 30 CHECK (fy_end_day BETWEEN 1 AND 31),
    gst_accounting_method   TEXT NOT NULL DEFAULT 'ACCRUAL' CHECK (gst_accounting_method IN ('ACCRUAL', 'CASH')),
    bas_reporting_type      TEXT NOT NULL DEFAULT 'SIMPLER_BAS' CHECK (bas_reporting_type IN ('SIMPLER_BAS', 'FULL_BAS')),
    bas_calculation_period  TEXT NOT NULL DEFAULT 'QUARTERLY' CHECK (bas_calculation_period IN ('MONTHLY', 'QUARTERLY', 'ANNUALLY')),
    bas_g1_mode             TEXT NOT NULL DEFAULT 'INCLUSIVE' CHECK (bas_g1_mode IN ('INCLUSIVE', 'EXCLUSIVE')),
    sales_tax_default       TEXT NOT NULL DEFAULT 'EXCLUSIVE' CHECK (sales_tax_default IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    purchases_tax_default   TEXT NOT NULL DEFAULT 'INCLUSIVE' CHECK (purchases_tax_default IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    invoice_prefix          TEXT NOT NULL DEFAULT 'INV-',
    next_invoice_seq        INTEGER NOT NULL DEFAULT 1,
    credit_note_prefix      TEXT NOT NULL DEFAULT 'CN-',
    next_credit_note_seq    INTEGER NOT NULL DEFAULT 1,
    quote_prefix            TEXT NOT NULL DEFAULT 'QU-',
    next_quote_seq          INTEGER NOT NULL DEFAULT 1,
    po_prefix               TEXT NOT NULL DEFAULT 'PO-',
    next_po_seq             INTEGER NOT NULL DEFAULT 1,
    soft_lock_date          TEXT,
    hard_lock_date          TEXT,
    conversion_date         TEXT,
    conversion_locked_at    TEXT,
    updated_at              TEXT NOT NULL,
    CHECK (hard_lock_date IS NULL OR soft_lock_date IS NULL OR hard_lock_date <= soft_lock_date)
);

CREATE TABLE IF NOT EXISTS org_counters (
    org_id                  TEXT PRIMARY KEY REFERENCES organisations(id) ON DELETE CASCADE,
    next_journal_number     INTEGER NOT NULL DEFAULT 1 CHECK (next_journal_number >= 1)
);

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS org_memberships (
    id              TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('ADVISER', 'STANDARD', 'READONLY')),
    created_at      TEXT NOT NULL,
    UNIQUE (org_id, user_id)
);

-- -----------------------------------------------------------------------------
-- 2. Tax Rates, Chart of Accounts & Products/Services Catalog
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tax_rates (
    id                          TEXT PRIMARY KEY,
    org_id                      TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code                        TEXT NOT NULL,
    name                        TEXT NOT NULL,
    rate_decimal                TEXT NOT NULL DEFAULT '0.0000', -- e.g. '0.1000'
    bas_field_names_json        TEXT NOT NULL DEFAULT '[]',     -- e.g. '["1A","G1"]'
    can_apply_to_assets         INTEGER NOT NULL DEFAULT 1 CHECK (can_apply_to_assets IN (0, 1)),
    can_apply_to_equity         INTEGER NOT NULL DEFAULT 1 CHECK (can_apply_to_equity IN (0, 1)),
    can_apply_to_expenses       INTEGER NOT NULL DEFAULT 1 CHECK (can_apply_to_expenses IN (0, 1)),
    can_apply_to_liabilities    INTEGER NOT NULL DEFAULT 1 CHECK (can_apply_to_liabilities IN (0, 1)),
    can_apply_to_revenue        INTEGER NOT NULL DEFAULT 1 CHECK (can_apply_to_revenue IN (0, 1)),
    is_system                   INTEGER NOT NULL DEFAULT 0 CHECK (is_system IN (0, 1)),
    status                      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    UNIQUE (org_id, code)
);

CREATE TABLE IF NOT EXISTS accounts (
    id                          TEXT PRIMARY KEY,
    org_id                      TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code                        TEXT,
    name                        TEXT NOT NULL,
    account_class               TEXT NOT NULL CHECK (account_class IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')),
    account_type                TEXT NOT NULL CHECK (account_type IN (
                                    'BANK', 'CURRENT', 'INVENTORY', 'FIXED',
                                    'CURRLIAB', 'TERMLIAB', 'EQUITY',
                                    'REVENUE', 'OTHERINCOME', 'DIRECTCOSTS', 'EXPENSE'
                                )),
    system_account              TEXT, -- DEBTORS, CREDITORS, GST, RETAINEDEARNINGS, HISTORICAL_ADJ, ROUNDING, UNPAID_EXPENSE_CLAIMS, WAGES_PAYABLE, TRACKING_TRANSFERS, etc.
    is_system_locked            INTEGER NOT NULL DEFAULT 0 CHECK (is_system_locked IN (0, 1)),
    manual_journal_excluded     INTEGER NOT NULL DEFAULT 0 CHECK (manual_journal_excluded IN (0, 1)),
    enable_payments_to_account  INTEGER NOT NULL DEFAULT 0 CHECK (enable_payments_to_account IN (0, 1)),
    show_on_watchlist           INTEGER NOT NULL DEFAULT 0 CHECK (show_on_watchlist IN (0, 1)),
    default_tax_rate_id         TEXT REFERENCES tax_rates(id),
    description                 TEXT,
    bank_account_number         TEXT,
    bank_currency               TEXT,
    status                      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    created_at                  TEXT NOT NULL,
    UNIQUE (org_id, code)
);

CREATE TABLE IF NOT EXISTS products (
    id                      TEXT PRIMARY KEY,
    org_id                  TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code                    TEXT NOT NULL,
    name                    TEXT NOT NULL,
    is_tracked              INTEGER NOT NULL DEFAULT 0 CHECK (is_tracked IN (0, 1)),
    cost_price_decimal      TEXT,
    purchase_description    TEXT,
    purchase_account_id     TEXT REFERENCES accounts(id),
    purchase_tax_rate_id    TEXT REFERENCES tax_rates(id),
    sale_price_decimal      TEXT,
    sales_description       TEXT,
    sales_account_id        TEXT REFERENCES accounts(id),
    sales_tax_rate_id       TEXT REFERENCES tax_rates(id),
    inventory_account_id    TEXT REFERENCES accounts(id),
    quantity_on_hand_e4     INTEGER NOT NULL DEFAULT 0,
    avg_cost_cents          INTEGER NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    created_at              TEXT NOT NULL,
    UNIQUE (org_id, code)
);

-- -----------------------------------------------------------------------------
-- 3. Contacts & Tracking Categories (max 2 active categories enforced in service)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contacts (
    id                          TEXT PRIMARY KEY,
    org_id                      TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name                        TEXT NOT NULL,
    account_number              TEXT,
    abn                         TEXT,
    email                       TEXT,
    phone                       TEXT,
    address                     TEXT,
    bank_bsb_account            TEXT,
    is_customer                 INTEGER NOT NULL DEFAULT 0 CHECK (is_customer IN (0, 1)),
    is_supplier                 INTEGER NOT NULL DEFAULT 0 CHECK (is_supplier IN (0, 1)),
    default_sales_account_id    TEXT REFERENCES accounts(id),
    default_purchase_account_id TEXT REFERENCES accounts(id),
    default_sales_tax_rate_id   TEXT REFERENCES tax_rates(id),
    default_purchase_tax_rate_id TEXT REFERENCES tax_rates(id),
    contact_groups_json         TEXT NOT NULL DEFAULT '[]',
    status                      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    created_at                  TEXT NOT NULL,
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS tracking_categories (
    id          TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS tracking_options (
    id              TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    category_id     TEXT NOT NULL REFERENCES tracking_categories(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    UNIQUE (category_id, name)
);

-- -----------------------------------------------------------------------------
-- 4. Append-Only Immutable General Ledger (Journals & Journal Lines)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journals (
    id                      TEXT PRIMARY KEY,
    org_id                  TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    journal_number          INTEGER NOT NULL,
    journal_date            TEXT NOT NULL,
    source_type             TEXT NOT NULL CHECK (source_type IN (
                                'ACCREC', 'ACCREC_REVERSAL', 'ACCRECCREDIT', 'ACCRECCREDIT_REVERSAL', 'ACCREC_PAYMENT', 'ACCREC_PAYMENT_REVERSAL',
                                'ACCPAY', 'ACCPAY_REVERSAL', 'ACCPAYCREDIT', 'ACCPAYCREDIT_REVERSAL', 'ACCPAY_PAYMENT', 'ACCPAY_PAYMENT_REVERSAL',
                                'CASHREC', 'CASHREC_REVERSAL', 'CASHPAID', 'CASHPAID_REVERSAL',
                                'TRANSFER', 'TRANSFER_REVERSAL',
                                'MANJOURNAL', 'MANJOURNAL_REVERSAL',
                                'CONVERSION', 'CONVERSION_REVERSAL',
                                'RECODE_REVERSAL', 'RECODE'
                            )),
    source_id               TEXT NOT NULL,
    reference               TEXT,
    narration               TEXT,
    reversal_of_journal_id  TEXT REFERENCES journals(id),
    show_on_cash_basis      INTEGER NOT NULL DEFAULT 1 CHECK (show_on_cash_basis IN (0, 1)),
    correlation_id          TEXT,
    posted_by               TEXT NOT NULL,
    posted_at               TEXT NOT NULL,
    UNIQUE (org_id, journal_number)
);

CREATE INDEX IF NOT EXISTS idx_journals_org_date ON journals (org_id, journal_date, journal_number);
CREATE INDEX IF NOT EXISTS idx_journals_source ON journals (org_id, source_type, source_id);

CREATE TABLE IF NOT EXISTS journal_lines (
    id                      TEXT PRIMARY KEY,
    org_id                  TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    journal_id              TEXT NOT NULL REFERENCES journals(id),
    line_no                 INTEGER NOT NULL CHECK (line_no >= 1),
    account_id              TEXT NOT NULL REFERENCES accounts(id),
    contact_id              TEXT REFERENCES contacts(id),
    description             TEXT,
    debit_cents             INTEGER NOT NULL DEFAULT 0 CHECK (debit_cents >= 0),
    credit_cents            INTEGER NOT NULL DEFAULT 0 CHECK (credit_cents >= 0),
    tax_rate_id             TEXT REFERENCES tax_rates(id),
    tax_type_code           TEXT,
    gross_cents             INTEGER NOT NULL DEFAULT 0,
    net_cents               INTEGER NOT NULL DEFAULT 0,
    tax_cents               INTEGER NOT NULL DEFAULT 0,
    tracking_1_option_id    TEXT REFERENCES tracking_options(id),
    tracking_2_option_id    TEXT REFERENCES tracking_options(id),
    CHECK (NOT (debit_cents > 0 AND credit_cents > 0)),
    CHECK (debit_cents > 0 OR credit_cents > 0),
    UNIQUE (journal_id, line_no)
);

CREATE INDEX IF NOT EXISTS idx_jlines_org_account ON journal_lines (org_id, account_id);

-- Database Engine Append-Only Enforcement on General Ledger
CREATE TRIGGER IF NOT EXISTS trg_journals_immutable_update
BEFORE UPDATE ON journals
BEGIN
    SELECT RAISE(ABORT, 'LEDGER_IMMUTABLE: posted journals cannot be modified; append a reversal journal instead');
END;

CREATE TRIGGER IF NOT EXISTS trg_journals_immutable_delete
BEFORE DELETE ON journals
BEGIN
    SELECT RAISE(ABORT, 'LEDGER_IMMUTABLE: posted journals cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS trg_journal_lines_immutable_update
BEFORE UPDATE ON journal_lines
BEGIN
    SELECT RAISE(ABORT, 'LEDGER_IMMUTABLE: posted journal_lines cannot be modified');
END;

CREATE TRIGGER IF NOT EXISTS trg_journal_lines_immutable_delete
BEFORE DELETE ON journal_lines
BEGIN
    SELECT RAISE(ABORT, 'LEDGER_IMMUTABLE: posted journal_lines cannot be deleted');
END;

-- -----------------------------------------------------------------------------
-- 5. Manual Journals (Draft/Posted/Voided/Archived Wrapper)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS manual_journals (
    id                      TEXT PRIMARY KEY,
    org_id                  TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    narration               TEXT NOT NULL,
    journal_date            TEXT NOT NULL,
    auto_reversing_date     TEXT,
    tax_mode                TEXT NOT NULL DEFAULT 'NO_TAX' CHECK (tax_mode IN ('NO_TAX', 'EXCLUSIVE', 'INCLUSIVE')),
    show_on_cash_basis      INTEGER NOT NULL DEFAULT 1 CHECK (show_on_cash_basis IN (0, 1)),
    status                  TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'POSTED', 'VOIDED', 'ARCHIVED')),
    posted_journal_id       TEXT REFERENCES journals(id),
    reversal_journal_id     TEXT REFERENCES journals(id),
    version                 INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_journal_lines (
    id                      TEXT PRIMARY KEY,
    manual_journal_id       TEXT NOT NULL REFERENCES manual_journals(id) ON DELETE CASCADE,
    line_no                 INTEGER NOT NULL CHECK (line_no >= 1),
    description             TEXT,
    account_id              TEXT NOT NULL REFERENCES accounts(id),
    tax_rate_id             TEXT NOT NULL REFERENCES tax_rates(id),
    debit_cents             INTEGER NOT NULL DEFAULT 0 CHECK (debit_cents >= 0),
    credit_cents            INTEGER NOT NULL DEFAULT 0 CHECK (credit_cents >= 0),
    net_cents               INTEGER NOT NULL DEFAULT 0,
    tax_cents               INTEGER NOT NULL DEFAULT 0,
    gross_cents             INTEGER NOT NULL DEFAULT 0,
    tracking_1_option_id    TEXT REFERENCES tracking_options(id),
    tracking_2_option_id    TEXT REFERENCES tracking_options(id),
    UNIQUE (manual_journal_id, line_no)
);

-- -----------------------------------------------------------------------------
-- 6. Pre-GL Commercial Documents: Quotes & Purchase Orders
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quotes (
    id                      TEXT PRIMARY KEY,
    org_id                  TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contact_id              TEXT NOT NULL REFERENCES contacts(id),
    quote_number            TEXT NOT NULL,
    reference               TEXT,
    issue_date              TEXT NOT NULL,
    expiry_date             TEXT,
    tax_mode                TEXT NOT NULL DEFAULT 'EXCLUSIVE' CHECK (tax_mode IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    status                  TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SENT', 'DECLINED', 'ACCEPTED', 'INVOICED', 'EXPIRED')),
    title                   TEXT,
    summary                 TEXT,
    terms                   TEXT,
    sub_total_cents         INTEGER NOT NULL DEFAULT 0,
    total_tax_cents         INTEGER NOT NULL DEFAULT 0,
    total_cents             INTEGER NOT NULL DEFAULT 0,
    converted_invoice_id    TEXT,
    version                 INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    UNIQUE (org_id, quote_number)
);

CREATE TABLE IF NOT EXISTS quote_lines (
    id                      TEXT PRIMARY KEY,
    quote_id                TEXT NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    line_no                 INTEGER NOT NULL CHECK (line_no >= 1),
    product_id              TEXT REFERENCES products(id),
    description             TEXT NOT NULL,
    quantity_decimal        TEXT NOT NULL DEFAULT '1',
    unit_amount_decimal     TEXT NOT NULL DEFAULT '0.00',
    discount_pct_decimal    TEXT NOT NULL DEFAULT '0',
    account_id              TEXT NOT NULL REFERENCES accounts(id),
    tax_rate_id             TEXT NOT NULL REFERENCES tax_rates(id),
    net_cents               INTEGER NOT NULL DEFAULT 0,
    tax_cents               INTEGER NOT NULL DEFAULT 0,
    gross_cents             INTEGER NOT NULL DEFAULT 0,
    tracking_1_option_id    TEXT REFERENCES tracking_options(id),
    tracking_2_option_id    TEXT REFERENCES tracking_options(id),
    UNIQUE (quote_id, line_no)
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id                      TEXT PRIMARY KEY,
    org_id                  TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    contact_id              TEXT NOT NULL REFERENCES contacts(id),
    po_number               TEXT NOT NULL,
    reference               TEXT,
    issue_date              TEXT NOT NULL,
    delivery_date           TEXT,
    tax_mode                TEXT NOT NULL DEFAULT 'INCLUSIVE' CHECK (tax_mode IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    status                  TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'AWAITING_APPROVAL', 'APPROVED', 'BILLED', 'DELETED')),
    delivery_instructions   TEXT,
    sub_total_cents         INTEGER NOT NULL DEFAULT 0,
    total_tax_cents         INTEGER NOT NULL DEFAULT 0,
    total_cents             INTEGER NOT NULL DEFAULT 0,
    converted_bill_id       TEXT,
    version                 INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    UNIQUE (org_id, po_number)
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id                      TEXT PRIMARY KEY,
    purchase_order_id       TEXT NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    line_no                 INTEGER NOT NULL CHECK (line_no >= 1),
    product_id              TEXT REFERENCES products(id),
    description             TEXT NOT NULL,
    quantity_decimal        TEXT NOT NULL DEFAULT '1',
    unit_amount_decimal     TEXT NOT NULL DEFAULT '0.00',
    discount_pct_decimal    TEXT NOT NULL DEFAULT '0',
    account_id              TEXT NOT NULL REFERENCES accounts(id),
    tax_rate_id             TEXT NOT NULL REFERENCES tax_rates(id),
    net_cents               INTEGER NOT NULL DEFAULT 0,
    tax_cents               INTEGER NOT NULL DEFAULT 0,
    gross_cents             INTEGER NOT NULL DEFAULT 0,
    tracking_1_option_id    TEXT REFERENCES tracking_options(id),
    tracking_2_option_id    TEXT REFERENCES tracking_options(id),
    UNIQUE (purchase_order_id, line_no)
);

-- -----------------------------------------------------------------------------
-- 7. Subledger Documents: Invoices, Bills, Credit Notes & Allocations
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoices (
    id                  TEXT PRIMARY KEY,
    org_id              TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    invoice_type        TEXT NOT NULL CHECK (invoice_type IN ('ACCREC', 'ACCPAY', 'ACCRECCREDIT', 'ACCPAYCREDIT')),
    contact_id          TEXT NOT NULL REFERENCES contacts(id),
    invoice_number      TEXT NOT NULL,
    reference           TEXT,
    issue_date          TEXT NOT NULL,
    due_date            TEXT NOT NULL,
    currency_code       TEXT NOT NULL DEFAULT 'AUD',
    tax_mode            TEXT NOT NULL CHECK (tax_mode IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    status              TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SUBMITTED', 'AUTHORISED', 'PAID', 'VOIDED')),
    sub_total_cents     INTEGER NOT NULL DEFAULT 0,
    total_tax_cents     INTEGER NOT NULL DEFAULT 0,
    total_cents         INTEGER NOT NULL DEFAULT 0,
    amount_paid_cents   INTEGER NOT NULL DEFAULT 0,
    amount_credited_cents INTEGER NOT NULL DEFAULT 0,
    posted_journal_id   TEXT REFERENCES journals(id),
    reversal_journal_id TEXT REFERENCES journals(id),
    source_quote_id     TEXT REFERENCES quotes(id),
    source_po_id        TEXT REFERENCES purchase_orders(id),
    version             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (org_id, invoice_type, invoice_number)
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id                      TEXT PRIMARY KEY,
    invoice_id              TEXT NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    line_no                 INTEGER NOT NULL CHECK (line_no >= 1),
    product_id              TEXT REFERENCES products(id),
    description             TEXT NOT NULL,
    quantity_decimal        TEXT NOT NULL DEFAULT '1',
    unit_amount_decimal     TEXT NOT NULL DEFAULT '0.00',
    discount_pct_decimal    TEXT NOT NULL DEFAULT '0',
    account_id              TEXT NOT NULL REFERENCES accounts(id),
    tax_rate_id             TEXT NOT NULL REFERENCES tax_rates(id),
    net_cents               INTEGER NOT NULL DEFAULT 0,
    tax_cents               INTEGER NOT NULL DEFAULT 0,
    gross_cents             INTEGER NOT NULL DEFAULT 0,
    tracking_1_option_id    TEXT REFERENCES tracking_options(id),
    tracking_2_option_id    TEXT REFERENCES tracking_options(id),
    UNIQUE (invoice_id, line_no)
);

CREATE TABLE IF NOT EXISTS credit_note_allocations (
    id                  TEXT PRIMARY KEY,
    org_id              TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    credit_note_id      TEXT NOT NULL REFERENCES invoices(id),
    target_invoice_id   TEXT NOT NULL REFERENCES invoices(id),
    allocation_date     TEXT NOT NULL,
    amount_cents        INTEGER NOT NULL CHECK (amount_cents > 0),
    status              TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'REVERSED')),
    created_by          TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cn_alloc_org ON credit_note_allocations (org_id, allocation_date);

-- -----------------------------------------------------------------------------
-- 8. Payments, Bank Transactions, Statement Lines & Bank Rules
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments (
    id                  TEXT PRIMARY KEY,
    org_id              TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    invoice_id          TEXT NOT NULL REFERENCES invoices(id),
    bank_account_id     TEXT NOT NULL REFERENCES accounts(id),
    payment_date        TEXT NOT NULL,
    amount_cents        INTEGER NOT NULL CHECK (amount_cents > 0),
    reference           TEXT,
    is_reconciled       INTEGER NOT NULL DEFAULT 0 CHECK (is_reconciled IN (0, 1)),
    status              TEXT NOT NULL DEFAULT 'AUTHORISED' CHECK (status IN ('AUTHORISED', 'DELETED')),
    journal_id          TEXT NOT NULL REFERENCES journals(id),
    reversal_journal_id TEXT REFERENCES journals(id),
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_payments_org_date ON payments (org_id, payment_date, status);

CREATE TABLE IF NOT EXISTS bank_transactions (
    id                  TEXT PRIMARY KEY,
    org_id              TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    tx_type             TEXT NOT NULL CHECK (tx_type IN ('RECEIVE', 'SPEND', 'TRANSFER')),
    bank_account_id     TEXT NOT NULL REFERENCES accounts(id),
    transfer_account_id TEXT REFERENCES accounts(id),
    contact_id          TEXT REFERENCES contacts(id),
    tx_date             TEXT NOT NULL,
    reference           TEXT,
    tax_mode            TEXT NOT NULL DEFAULT 'INCLUSIVE' CHECK (tax_mode IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    sub_total_cents     INTEGER NOT NULL DEFAULT 0,
    total_tax_cents     INTEGER NOT NULL DEFAULT 0,
    total_cents         INTEGER NOT NULL DEFAULT 0,
    is_reconciled       INTEGER NOT NULL DEFAULT 0 CHECK (is_reconciled IN (0, 1)),
    status              TEXT NOT NULL DEFAULT 'AUTHORISED' CHECK (status IN ('AUTHORISED', 'DELETED')),
    journal_id          TEXT NOT NULL REFERENCES journals(id),
    reversal_journal_id TEXT REFERENCES journals(id),
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bank_transaction_lines (
    id                      TEXT PRIMARY KEY,
    bank_transaction_id     TEXT NOT NULL REFERENCES bank_transactions(id) ON DELETE CASCADE,
    line_no                 INTEGER NOT NULL CHECK (line_no >= 1),
    description             TEXT,
    account_id              TEXT NOT NULL REFERENCES accounts(id),
    tax_rate_id             TEXT NOT NULL REFERENCES tax_rates(id),
    net_cents               INTEGER NOT NULL DEFAULT 0,
    tax_cents               INTEGER NOT NULL DEFAULT 0,
    gross_cents             INTEGER NOT NULL DEFAULT 0,
    tracking_1_option_id    TEXT REFERENCES tracking_options(id),
    tracking_2_option_id    TEXT REFERENCES tracking_options(id),
    UNIQUE (bank_transaction_id, line_no)
);

CREATE TABLE IF NOT EXISTS bank_statement_lines (
    id                      TEXT PRIMARY KEY,
    org_id                  TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    bank_account_id         TEXT NOT NULL REFERENCES accounts(id),
    tx_date                 TEXT NOT NULL,
    amount_cents            INTEGER NOT NULL CHECK (amount_cents <> 0), -- +deposit, -withdrawal
    payee                   TEXT,
    description             TEXT,
    reference               TEXT,
    cheque_number           TEXT,
    occurrence_idx          INTEGER NOT NULL DEFAULT 1,
    import_hash             TEXT NOT NULL,
    import_source           TEXT NOT NULL DEFAULT 'CSV' CHECK (import_source IN ('CSV', 'MANUAL')),
    reconcile_status        TEXT NOT NULL DEFAULT 'UNRECONCILED' CHECK (reconcile_status IN ('UNRECONCILED', 'RECONCILED', 'DELETED')),
    matched_entity_type     TEXT CHECK (matched_entity_type IN ('PAYMENT', 'BANK_TRANSACTION', 'PAYMENT_GROUP')),
    matched_entity_id       TEXT,
    matched_entity_ids_json TEXT,
    discuss_note            TEXT,
    reconciled_at           TEXT,
    version                 INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL,
    UNIQUE (bank_account_id, import_hash)
);

CREATE TABLE IF NOT EXISTS bank_rules (
    id                  TEXT PRIMARY KEY,
    org_id              TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    rule_type           TEXT NOT NULL CHECK (rule_type IN ('SPEND', 'RECEIVE', 'TRANSFER')),
    match_strategy      TEXT NOT NULL DEFAULT 'ALL' CHECK (match_strategy IN ('ANY', 'ALL')),
    conditions_json     TEXT NOT NULL DEFAULT '[]',     -- [{field, operator, value}]
    contact_id          TEXT REFERENCES contacts(id),
    target_bank_id      TEXT REFERENCES accounts(id),   -- only for TRANSFER rules
    fixed_lines_json    TEXT NOT NULL DEFAULT '[]',     -- [{description, accountId, taxRateId, tracking1Id, amountCents}]
    percent_lines_json  TEXT NOT NULL DEFAULT '[]',     -- [{description, accountId, taxRateId, tracking1Id, percentDecimal}]
    reference_source    TEXT DEFAULT 'FROM_STATEMENT',
    bank_account_scope  TEXT,                           -- NULL = all bank accounts, or specific bank_account_id
    priority_order      INTEGER NOT NULL DEFAULT 1,
    status              TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    created_at          TEXT NOT NULL
);

-- -----------------------------------------------------------------------------
-- 9. Conversion Balances, Find & Recode, Simpler BAS, Connected Apps & Audit
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversion_balance_entries (
    id              TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    account_id      TEXT NOT NULL REFERENCES accounts(id),
    debit_cents     INTEGER NOT NULL DEFAULT 0 CHECK (debit_cents >= 0),
    credit_cents    INTEGER NOT NULL DEFAULT 0 CHECK (credit_cents >= 0),
    UNIQUE (org_id, account_id)
);

CREATE TABLE IF NOT EXISTS find_recode_batches (
    id                      TEXT PRIMARY KEY,
    org_id                  TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    approved_by             TEXT NOT NULL,
    transactions_affected   INTEGER NOT NULL,
    date_range_label        TEXT NOT NULL,
    changes_summary_json    TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'COMPLETED',
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bas_statements (
    id                      TEXT PRIMARY KEY,
    org_id                  TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    period_start            TEXT NOT NULL,
    period_end              TEXT NOT NULL,
    accounting_method       TEXT NOT NULL CHECK (accounting_method IN ('ACCRUAL', 'CASH')),
    g1_mode                 TEXT NOT NULL CHECK (g1_mode IN ('INCLUSIVE', 'EXCLUSIVE')),
    min_journal_number      INTEGER,
    max_journal_number      INTEGER NOT NULL,
    g1_total_sales_dollars  INTEGER NOT NULL DEFAULT 0,
    gst_1a_sales_dollars    INTEGER NOT NULL DEFAULT 0,
    gst_1b_purchases_dollars INTEGER NOT NULL DEFAULT 0,
    adjustment_1a_dollars   INTEGER NOT NULL DEFAULT 0,
    adjustment_1b_dollars   INTEGER NOT NULL DEFAULT 0,
    net_payment_9_dollars   INTEGER NOT NULL DEFAULT 0,
    unfiled_included_count  INTEGER NOT NULL DEFAULT 0,
    status                  TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'FINALISED')),
    snapshot_json           TEXT NOT NULL,
    finalised_by            TEXT,
    finalised_at            TEXT,
    UNIQUE (org_id, period_start, period_end)
);

CREATE TABLE IF NOT EXISTS connected_apps (
    id              TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    app_slug        TEXT NOT NULL,
    app_name        TEXT NOT NULL,
    category        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'CONNECTED' CHECK (status IN ('CONNECTED', 'DISCONNECTED')),
    scopes_json     TEXT NOT NULL DEFAULT '[]',
    connected_at    TEXT NOT NULL,
    UNIQUE (org_id, app_slug)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id              TEXT PRIMARY KEY,
    org_id          TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    actor_user_id   TEXT NOT NULL,
    actor_name      TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    action          TEXT NOT NULL,
    summary         TEXT NOT NULL,
    diff_json       TEXT,
    correlation_id  TEXT,
    created_at      TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_audit_logs_immutable_update
BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'AUDIT_IMMUTABLE: audit_logs cannot be modified');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_logs_immutable_delete
BEFORE DELETE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'AUDIT_IMMUTABLE: audit_logs cannot be deleted');
END;

CREATE TABLE IF NOT EXISTS idempotency_records (
    org_id          TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash    TEXT NOT NULL,
    response_status INTEGER NOT NULL,
    response_body   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (org_id, idempotency_key)
);
