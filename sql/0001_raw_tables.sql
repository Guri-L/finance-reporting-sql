-- =========================================================================
-- RAW LAYER: tables exactly as the ledger extract delivers them.
-- Typed, with primary keys, but deliberately WITHOUT foreign keys: this is a
-- landing zone, and referential integrity is proven by the control checks
-- (controls.orphaned_keys) rather than assumed.
-- =========================================================================
CREATE SCHEMA raw;

-- Grain: one row per general ledger account.
CREATE TABLE raw.chart_of_accounts (
    account_code       text PRIMARY KEY,
    account_name       text NOT NULL,
    account_type       text NOT NULL,   -- asset | liability | equity | revenue | expense
    statement_section  text NOT NULL,   -- e.g. 'Current assets', 'Operating expenses'
    cash_flow_line     text             -- balance sheet accounts only
);

-- Grain: one row per cost centre.
CREATE TABLE raw.cost_centres (
    cost_centre_code  text PRIMARY KEY,
    cost_centre_name  text NOT NULL,
    manager_name      text
);

-- Grain: one row per fiscal month. The opening period (Dec 2023) only holds
-- the opening balances and is never reported on.
CREATE TABLE raw.fiscal_periods (
    period_start       date PRIMARY KEY,
    period_end         date NOT NULL,
    fiscal_year        integer NOT NULL,
    status             text NOT NULL,   -- open | closed
    closed_at          timestamp,
    is_opening_period  boolean NOT NULL DEFAULT false
);

-- Grain: one row per customer.
CREATE TABLE raw.customers (
    customer_id         text PRIMARY KEY,
    customer_name       text NOT NULL,
    segment             text,
    country             text,
    payment_terms_days  integer NOT NULL
);

-- Grain: one row per journal entry (header).
CREATE TABLE raw.journal_entries (
    entry_id           bigint PRIMARY KEY,
    entry_number       text NOT NULL,
    entry_date         date NOT NULL,       -- accounting date: decides the period
    posted_at          timestamp NOT NULL,  -- when it was actually keyed in
    description        text,
    source             text NOT NULL,       -- GL | AR | AP | PAY | CASH
    reverses_entry_id  bigint               -- set on reversal entries
);

-- Grain: one row per journal entry line. Exactly one of debit/credit is non-zero.
CREATE TABLE raw.journal_lines (
    line_id           bigint PRIMARY KEY,
    entry_id          bigint NOT NULL,
    line_number       integer NOT NULL,
    account_code      text NOT NULL,
    cost_centre_code  text,                 -- required on P&L lines, empty on balance sheet lines
    customer_id       text,                 -- receivables lines only
    debit             numeric(14,2) NOT NULL DEFAULT 0,
    credit            numeric(14,2) NOT NULL DEFAULT 0
);
CREATE INDEX journal_lines_entry_idx   ON raw.journal_lines (entry_id);
CREATE INDEX journal_lines_account_idx ON raw.journal_lines (account_code);
CREATE INDEX journal_entries_date_idx  ON raw.journal_entries (entry_date);

-- Grain: one row per sales invoice.
CREATE TABLE raw.invoices (
    invoice_id            bigint PRIMARY KEY,
    invoice_number        text NOT NULL,
    customer_id           text NOT NULL,
    invoice_date          date NOT NULL,
    due_date              date NOT NULL,
    amount                numeric(14,2) NOT NULL,
    revenue_account_code  text NOT NULL,
    entry_id              bigint NOT NULL
);

-- Grain: one row per customer receipt applied to one invoice.
CREATE TABLE raw.payments (
    payment_id    bigint PRIMARY KEY,
    invoice_id    bigint NOT NULL,
    payment_date  date NOT NULL,
    amount        numeric(14,2) NOT NULL,
    entry_id      bigint NOT NULL
);
CREATE INDEX payments_invoice_idx ON raw.payments (invoice_id);

-- Grain: one row per month x cost centre x account.
CREATE TABLE raw.budget (
    period_start      date NOT NULL,
    cost_centre_code  text NOT NULL,
    account_code      text NOT NULL,
    amount            numeric(14,2) NOT NULL,
    PRIMARY KEY (period_start, cost_centre_code, account_code)
);
