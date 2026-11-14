-- =============================================================================
-- AU Accounting SaaS Blueprint - Core PostgreSQL 16 Schema (MVP)
-- Traceability: Xero-Research/03_数据对象与接口研究.md & 04_技术架构与实现原理研究.md
-- Principles:
--   1. Multi-tenant isolation via org_id on all domain tables.
--   2. Monetary values stored as NUMERIC(18,4), never FLOAT.
--   3. Append-only immutable GL (journals + journal_lines protected by triggers).
--   4. Monotonic per-org journal_number sequence via org_counters.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------------------------------------------------------
-- 1. Organisations, Settings & Counters
-- -----------------------------------------------------------------------------
CREATE TABLE organisations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    short_code      VARCHAR(12) NOT NULL UNIQUE,
    display_name    VARCHAR(160) NOT NULL,
    legal_name      VARCHAR(160),
    country_code    CHAR(2) NOT NULL DEFAULT 'AU',
    base_currency   CHAR(3) NOT NULL DEFAULT 'AUD',
    abn             VARCHAR(14),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE org_settings (
    org_id                  UUID PRIMARY KEY REFERENCES organisations(id) ON DELETE CASCADE,
    fy_end_month            SMALLINT NOT NULL DEFAULT 6 CHECK (fy_end_month BETWEEN 1 AND 12),
    fy_end_day              SMALLINT NOT NULL DEFAULT 30 CHECK (fy_end_day BETWEEN 1 AND 31),
    gst_accounting_method   VARCHAR(16) NOT NULL DEFAULT 'ACCRUAL' CHECK (gst_accounting_method IN ('ACCRUAL', 'CASH')),
    bas_reporting_type      VARCHAR(16) NOT NULL DEFAULT 'SIMPLER_BAS' CHECK (bas_reporting_type IN ('SIMPLER_BAS', 'FULL_BAS')),
    bas_calculation_period  VARCHAR(16) NOT NULL DEFAULT 'QUARTERLY' CHECK (bas_calculation_period IN ('MONTHLY', 'QUARTERLY', 'ANNUALLY')),
    bas_g1_mode             VARCHAR(16) NOT NULL DEFAULT 'INCLUSIVE' CHECK (bas_g1_mode IN ('INCLUSIVE', 'EXCLUSIVE')),
    sales_tax_default       VARCHAR(16) NOT NULL DEFAULT 'EXCLUSIVE' CHECK (sales_tax_default IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    purchases_tax_default   VARCHAR(16) NOT NULL DEFAULT 'INCLUSIVE' CHECK (purchases_tax_default IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    soft_lock_date          DATE,
    hard_lock_date          DATE,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (hard_lock_date IS NULL OR soft_lock_date IS NULL OR hard_lock_date <= soft_lock_date)
);

CREATE TABLE org_counters (
    org_id                  UUID PRIMARY KEY REFERENCES organisations(id) ON DELETE CASCADE,
    next_journal_number     BIGINT NOT NULL DEFAULT 1 CHECK (next_journal_number >= 1)
);

CREATE TABLE org_memberships (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL,
    role            VARCHAR(16) NOT NULL CHECK (role IN ('ADVISER', 'STANDARD', 'READONLY')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, user_id)
);

-- -----------------------------------------------------------------------------
-- 2. Tax Rates & Chart of Accounts
-- -----------------------------------------------------------------------------
CREATE TABLE tax_rates (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                      UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code                        VARCHAR(32) NOT NULL, -- e.g. OUTPUT, INPUT, EXEMPTOUTPUT, EXEMPTEXPENSES, BASEXCLUDED, GSTONIMPORTS
    name                        VARCHAR(120) NOT NULL,
    rate                        NUMERIC(8,4) NOT NULL DEFAULT 0 CHECK (rate >= 0 AND rate <= 1),
    bas_field_names             JSONB NOT NULL DEFAULT '[]'::jsonb, -- e.g. ["1A","G1"] or ["1B","G11"]
    can_apply_to_assets         BOOLEAN NOT NULL DEFAULT TRUE,
    can_apply_to_equity         BOOLEAN NOT NULL DEFAULT TRUE,
    can_apply_to_expenses       BOOLEAN NOT NULL DEFAULT TRUE,
    can_apply_to_liabilities    BOOLEAN NOT NULL DEFAULT TRUE,
    can_apply_to_revenue        BOOLEAN NOT NULL DEFAULT TRUE,
    is_system                   BOOLEAN NOT NULL DEFAULT FALSE,
    status                      VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    UNIQUE (org_id, code)
);

CREATE TABLE accounts (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                      UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    code                        VARCHAR(20), -- Nullable for BANK accounts without code if preferred, or unique code
    name                        VARCHAR(150) NOT NULL,
    account_class               VARCHAR(16) NOT NULL CHECK (account_class IN ('ASSET', 'LIABILITY', 'EQUITY', 'REVENUE', 'EXPENSE')),
    account_type                VARCHAR(24) NOT NULL CHECK (account_type IN (
                                    'BANK', 'CURRENT', 'INVENTORY', 'FIXED',
                                    'CURRLIAB', 'TERMLIAB', 'EQUITY',
                                    'REVENUE', 'OTHERINCOME', 'DIRECTCOSTS', 'EXPENSE'
                                )),
    system_account              VARCHAR(32) CHECK (system_account IN (
                                    'DEBTORS', 'CREDITORS', 'GST', 'RETAINEDEARNINGS',
                                    'HISTORICAL_ADJ', 'ROUNDING', 'UNPAID_EXPENSE_CLAIMS',
                                    'WAGES_PAYABLE', 'TRACKING_TRANSFERS'
                                )),
    is_system_locked            BOOLEAN NOT NULL DEFAULT FALSE,
    enable_payments_to_account  BOOLEAN NOT NULL DEFAULT FALSE,
    default_tax_rate_id         UUID REFERENCES tax_rates(id),
    description                 TEXT,
    bank_account_number         VARCHAR(64),
    bank_currency               CHAR(3),
    status                      VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, code)
);

-- -----------------------------------------------------------------------------
-- 3. Contacts & Tracking Categories (max 2 active categories enforced in service)
-- -----------------------------------------------------------------------------
CREATE TABLE contacts (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                      UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name                        VARCHAR(200) NOT NULL,
    abn                         VARCHAR(14),
    email                       VARCHAR(200),
    is_customer                 BOOLEAN NOT NULL DEFAULT FALSE,
    is_supplier                 BOOLEAN NOT NULL DEFAULT FALSE,
    default_sales_account_id    UUID REFERENCES accounts(id),
    default_purchase_account_id UUID REFERENCES accounts(id),
    default_sales_tax_rate_id   UUID REFERENCES tax_rates(id),
    default_purchase_tax_rate_id UUID REFERENCES tax_rates(id),
    status                      VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    UNIQUE (org_id, name)
);

CREATE TABLE tracking_categories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name        VARCHAR(80) NOT NULL,
    status      VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    UNIQUE (org_id, name)
);

CREATE TABLE tracking_options (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    category_id     UUID NOT NULL REFERENCES tracking_categories(id) ON DELETE CASCADE,
    name            VARCHAR(80) NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'ARCHIVED')),
    UNIQUE (category_id, name)
);

-- -----------------------------------------------------------------------------
-- 4. Append-Only Immutable General Ledger (Journals & Journal Lines)
-- -----------------------------------------------------------------------------
CREATE TABLE journals (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    journal_number          BIGINT NOT NULL,
    journal_date            DATE NOT NULL,
    source_type             VARCHAR(32) NOT NULL CHECK (source_type IN (
                                'ACCREC', 'ACCREC_REVERSAL', 'ACCRECCREDIT', 'ACCREC_PAYMENT',
                                'ACCPAY', 'ACCPAY_REVERSAL', 'ACCPAYCREDIT', 'ACCPAY_PAYMENT',
                                'CASHREC', 'CASHPAID', 'TRANSFER',
                                'MANJOURNAL', 'MANJOURNAL_REVERSAL', 'CONVERSION'
                            )),
    source_id               UUID NOT NULL,
    reference               VARCHAR(160),
    narration               VARCHAR(500),
    reversal_of_journal_id  UUID REFERENCES journals(id),
    show_on_cash_basis      BOOLEAN NOT NULL DEFAULT TRUE,
    correlation_id          UUID,
    posted_by               UUID NOT NULL,
    posted_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, journal_number)
);

CREATE INDEX idx_journals_org_date ON journals (org_id, journal_date, journal_number);
CREATE INDEX idx_journals_source ON journals (org_id, source_type, source_id);

CREATE TABLE journal_lines (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    journal_id              UUID NOT NULL REFERENCES journals(id),
    line_no                 INT NOT NULL CHECK (line_no >= 1),
    account_id              UUID NOT NULL REFERENCES accounts(id),
    description             VARCHAR(500),
    debit_amount            NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (debit_amount >= 0),
    credit_amount           NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (credit_amount >= 0),
    tax_rate_id             UUID REFERENCES tax_rates(id),
    tax_type_code           VARCHAR(32),
    gross_amount            NUMERIC(18,4) NOT NULL DEFAULT 0, -- signed or unsigned base for BAS reporting
    net_amount              NUMERIC(18,4) NOT NULL DEFAULT 0,
    tax_amount              NUMERIC(18,4) NOT NULL DEFAULT 0,
    tracking_1_option_id    UUID REFERENCES tracking_options(id),
    tracking_2_option_id    UUID REFERENCES tracking_options(id),
    CHECK (NOT (debit_amount > 0 AND credit_amount > 0)),
    CHECK (debit_amount > 0 OR credit_amount > 0),
    UNIQUE (journal_id, line_no)
);

CREATE INDEX idx_jlines_org_account ON journal_lines (org_id, account_id);

-- Enforce Append-Only GL Immutability at DB Engine Level
CREATE OR REPLACE FUNCTION prevent_gl_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'General Ledger tables (journals, journal_lines) are append-only and immutable. Create a reversal journal instead.'
        USING ERRCODE = '42501';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_journals_immutable
    BEFORE UPDATE OR DELETE ON journals
    FOR EACH ROW EXECUTE FUNCTION prevent_gl_mutation();

CREATE TRIGGER trg_journal_lines_immutable
    BEFORE UPDATE OR DELETE ON journal_lines
    FOR EACH ROW EXECUTE FUNCTION prevent_gl_mutation();

-- -----------------------------------------------------------------------------
-- 5. Manual Journals (Draft/Posted/Voided Wrapper)
-- -----------------------------------------------------------------------------
CREATE TABLE manual_journals (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    narration               VARCHAR(500) NOT NULL,
    journal_date            DATE NOT NULL,
    auto_reversing_date     DATE,
    tax_mode                VARCHAR(16) NOT NULL DEFAULT 'NO_TAX' CHECK (tax_mode IN ('NO_TAX', 'EXCLUSIVE', 'INCLUSIVE')),
    show_on_cash_basis      BOOLEAN NOT NULL DEFAULT TRUE,
    status                  VARCHAR(16) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'POSTED', 'VOIDED', 'ARCHIVED')),
    posted_journal_id       UUID REFERENCES journals(id),
    reversal_journal_id     UUID REFERENCES journals(id),
    version                 INT NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE manual_journal_lines (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    manual_journal_id       UUID NOT NULL REFERENCES manual_journals(id) ON DELETE CASCADE,
    line_no                 INT NOT NULL CHECK (line_no >= 1),
    description             VARCHAR(500),
    account_id              UUID NOT NULL REFERENCES accounts(id),
    tax_rate_id             UUID NOT NULL REFERENCES tax_rates(id),
    debit_input             NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (debit_input >= 0),
    credit_input            NUMERIC(18,4) NOT NULL DEFAULT 0 CHECK (credit_input >= 0),
    tracking_1_option_id    UUID REFERENCES tracking_options(id),
    tracking_2_option_id    UUID REFERENCES tracking_options(id),
    UNIQUE (manual_journal_id, line_no)
);

-- -----------------------------------------------------------------------------
-- 6. Subledger Documents: Invoices, Bills & Credit Notes
-- -----------------------------------------------------------------------------
CREATE TABLE invoices (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    invoice_type        VARCHAR(16) NOT NULL CHECK (invoice_type IN ('ACCREC', 'ACCPAY', 'ACCRECCREDIT', 'ACCPAYCREDIT')),
    contact_id          UUID NOT NULL REFERENCES contacts(id),
    invoice_number      VARCHAR(60) NOT NULL,
    reference           VARCHAR(160),
    issue_date          DATE NOT NULL,
    due_date            DATE NOT NULL,
    currency_code       CHAR(3) NOT NULL DEFAULT 'AUD',
    tax_mode            VARCHAR(16) NOT NULL CHECK (tax_mode IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    status              VARCHAR(16) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SUBMITTED', 'AUTHORISED', 'PAID', 'VOIDED')),
    sub_total           NUMERIC(18,4) NOT NULL DEFAULT 0,
    total_tax           NUMERIC(18,4) NOT NULL DEFAULT 0,
    total               NUMERIC(18,4) NOT NULL DEFAULT 0,
    amount_paid         NUMERIC(18,4) NOT NULL DEFAULT 0,
    amount_credited     NUMERIC(18,4) NOT NULL DEFAULT 0,
    posted_journal_id   UUID REFERENCES journals(id),
    reversal_journal_id UUID REFERENCES journals(id),
    version             INT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, invoice_type, invoice_number)
);

CREATE TABLE invoice_lines (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id              UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    line_no                 INT NOT NULL CHECK (line_no >= 1),
    description             VARCHAR(500) NOT NULL,
    quantity                NUMERIC(18,4) NOT NULL DEFAULT 1,
    unit_amount             NUMERIC(18,4) NOT NULL DEFAULT 0,
    discount_pct            NUMERIC(6,2) NOT NULL DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 100),
    account_id              UUID NOT NULL REFERENCES accounts(id),
    tax_rate_id             UUID NOT NULL REFERENCES tax_rates(id),
    net_amount              NUMERIC(18,4) NOT NULL DEFAULT 0,
    tax_amount              NUMERIC(18,4) NOT NULL DEFAULT 0,
    gross_amount            NUMERIC(18,4) NOT NULL DEFAULT 0,
    tracking_1_option_id    UUID REFERENCES tracking_options(id),
    tracking_2_option_id    UUID REFERENCES tracking_options(id),
    UNIQUE (invoice_id, line_no)
);

-- -----------------------------------------------------------------------------
-- 7. Payments, Bank Statement Lines & Bank Transactions
-- -----------------------------------------------------------------------------
CREATE TABLE payments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    invoice_id          UUID NOT NULL REFERENCES invoices(id),
    bank_account_id     UUID NOT NULL REFERENCES accounts(id),
    payment_date        DATE NOT NULL,
    amount              NUMERIC(18,4) NOT NULL CHECK (amount > 0),
    reference           VARCHAR(160),
    is_reconciled       BOOLEAN NOT NULL DEFAULT FALSE,
    status              VARCHAR(16) NOT NULL DEFAULT 'AUTHORISED' CHECK (status IN ('AUTHORISED', 'DELETED')),
    journal_id          UUID NOT NULL REFERENCES journals(id),
    reversal_journal_id UUID REFERENCES journals(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE bank_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    tx_type             VARCHAR(16) NOT NULL CHECK (tx_type IN ('RECEIVE', 'SPEND', 'TRANSFER')),
    bank_account_id     UUID NOT NULL REFERENCES accounts(id),
    transfer_account_id UUID REFERENCES accounts(id),
    contact_id          UUID REFERENCES contacts(id),
    tx_date             DATE NOT NULL,
    reference           VARCHAR(160),
    tax_mode            VARCHAR(16) NOT NULL DEFAULT 'INCLUSIVE' CHECK (tax_mode IN ('INCLUSIVE', 'EXCLUSIVE', 'NO_TAX')),
    sub_total           NUMERIC(18,4) NOT NULL DEFAULT 0,
    total_tax           NUMERIC(18,4) NOT NULL DEFAULT 0,
    total               NUMERIC(18,4) NOT NULL DEFAULT 0,
    is_reconciled       BOOLEAN NOT NULL DEFAULT FALSE,
    status              VARCHAR(16) NOT NULL DEFAULT 'AUTHORISED' CHECK (status IN ('AUTHORISED', 'DELETED')),
    journal_id          UUID NOT NULL REFERENCES journals(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE bank_transaction_lines (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bank_transaction_id     UUID NOT NULL REFERENCES bank_transactions(id) ON DELETE CASCADE,
    line_no                 INT NOT NULL CHECK (line_no >= 1),
    description             VARCHAR(500),
    account_id              UUID NOT NULL REFERENCES accounts(id),
    tax_rate_id             UUID NOT NULL REFERENCES tax_rates(id),
    net_amount              NUMERIC(18,4) NOT NULL DEFAULT 0,
    tax_amount              NUMERIC(18,4) NOT NULL DEFAULT 0,
    gross_amount            NUMERIC(18,4) NOT NULL DEFAULT 0,
    tracking_1_option_id    UUID REFERENCES tracking_options(id),
    tracking_2_option_id    UUID REFERENCES tracking_options(id),
    UNIQUE (bank_transaction_id, line_no)
);

CREATE TABLE bank_statement_lines (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    bank_account_id         UUID NOT NULL REFERENCES accounts(id),
    tx_date                 DATE NOT NULL,
    amount                  NUMERIC(18,4) NOT NULL CHECK (amount <> 0), -- +credit/deposit, -debit/withdrawal
    payee                   VARCHAR(200),
    description             VARCHAR(500),
    reference               VARCHAR(160),
    cheque_number           VARCHAR(60),
    import_hash             CHAR(64) NOT NULL,
    reconcile_status        VARCHAR(16) NOT NULL DEFAULT 'UNRECONCILED' CHECK (reconcile_status IN ('UNRECONCILED', 'RECONCILED')),
    matched_entity_type     VARCHAR(24) CHECK (matched_entity_type IN ('PAYMENT', 'BANK_TRANSACTION')),
    matched_entity_id       UUID,
    reconciled_at           TIMESTAMPTZ,
    version                 INT NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (bank_account_id, import_hash)
);

-- -----------------------------------------------------------------------------
-- 8. AU Simpler BAS Activity Statements & Audit/Idempotency Stores
-- -----------------------------------------------------------------------------
CREATE TABLE bas_statements (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    accounting_method   VARCHAR(16) NOT NULL CHECK (accounting_method IN ('ACCRUAL', 'CASH')),
    g1_mode             VARCHAR(16) NOT NULL CHECK (g1_mode IN ('INCLUSIVE', 'EXCLUSIVE')),
    min_journal_number  BIGINT,
    max_journal_number  BIGINT NOT NULL,
    g1_total_sales      NUMERIC(18,0) NOT NULL DEFAULT 0, -- AU BAS whole dollars
    gst_1a_sales        NUMERIC(18,0) NOT NULL DEFAULT 0,
    gst_1b_purchases    NUMERIC(18,0) NOT NULL DEFAULT 0,
    adjustment_1a       NUMERIC(18,0) NOT NULL DEFAULT 0,
    adjustment_1b       NUMERIC(18,0) NOT NULL DEFAULT 0,
    net_payment_9       NUMERIC(18,0) NOT NULL DEFAULT 0,
    status              VARCHAR(16) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'FINALISED')),
    snapshot_json       JSONB NOT NULL,
    finalised_by        UUID,
    finalised_at        TIMESTAMPTZ,
    UNIQUE (org_id, period_start, period_end)
);

CREATE TABLE audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    actor_user_id   UUID NOT NULL,
    entity_type     VARCHAR(40) NOT NULL,
    entity_id       UUID NOT NULL,
    action          VARCHAR(40) NOT NULL,
    summary         TEXT NOT NULL,
    diff_json       JSONB,
    correlation_id  UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE idempotency_records (
    org_id          UUID NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    request_hash    CHAR(64) NOT NULL,
    response_status INT NOT NULL,
    response_body   JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (org_id, idempotency_key)
);
