-- =========================================================================
-- CLEANED LAYER: one view per raw table. Trims text, turns empty strings
-- into NULLs, adds the derived flags and signs every report needs, and
-- nothing else. No aggregation happens here.
-- =========================================================================
CREATE SCHEMA clean;

-- Grain: one row per account.
-- balance_sign presents balance sheet accounts in their natural direction
-- (assets debit-positive, liabilities and equity credit-positive).
CREATE VIEW clean.accounts AS
SELECT
    btrim(account_code)                                   AS account_code,
    btrim(account_name)                                   AS account_name,
    lower(btrim(account_type))                            AS account_type,
    btrim(statement_section)                              AS statement_section,
    nullif(btrim(cash_flow_line), '')                     AS cash_flow_line,
    lower(btrim(account_type)) IN ('revenue', 'expense')  AS is_pnl,
    lower(btrim(account_type)) IN ('asset', 'liability', 'equity') AS is_balance_sheet,
    CASE WHEN lower(btrim(account_type)) = 'asset' THEN 1 ELSE -1 END AS balance_sign,
    CASE btrim(statement_section)
        WHEN 'Revenue'                 THEN 10
        WHEN 'Cost of sales'           THEN 20
        WHEN 'Operating expenses'      THEN 30
        WHEN 'Finance costs'           THEN 40
        WHEN 'Current assets'          THEN 110
        WHEN 'Non-current assets'      THEN 120
        WHEN 'Current liabilities'     THEN 210
        WHEN 'Non-current liabilities' THEN 220
        WHEN 'Equity'                  THEN 310
    END                                                   AS section_order
FROM raw.chart_of_accounts;

-- Grain: one row per cost centre.
CREATE VIEW clean.cost_centres AS
SELECT btrim(cost_centre_code) AS cost_centre_code,
       btrim(cost_centre_name) AS cost_centre_name,
       nullif(btrim(manager_name), '') AS manager_name
FROM raw.cost_centres;

-- Grain: one row per fiscal month, including the opening period.
CREATE VIEW clean.periods AS
SELECT period_start, period_end, fiscal_year,
       lower(btrim(status)) AS status,
       closed_at,
       is_opening_period,
       (period_start - interval '1 year')::date AS prior_year_period_start
FROM raw.fiscal_periods;

-- Grain: one row per customer.
CREATE VIEW clean.customers AS
SELECT btrim(customer_id) AS customer_id, btrim(customer_name) AS customer_name,
       nullif(btrim(segment), '') AS segment, nullif(btrim(country), '') AS country,
       payment_terms_days
FROM raw.customers;

-- Grain: one row per journal entry line, with its header attached.
-- amount = debit - credit, so every balanced entry sums to zero.
-- period_start is always derived from the accounting date, never from the
-- posting timestamp, which is what makes late postings land in the right month.
CREATE VIEW clean.journal_lines AS
SELECT
    l.line_id,
    l.entry_id,
    e.entry_number,
    l.line_number,
    e.entry_date,
    date_trunc('month', e.entry_date)::date        AS period_start,
    e.posted_at,
    btrim(e.description)                           AS description,
    upper(btrim(e.source))                         AS source,
    btrim(l.account_code)                          AS account_code,
    nullif(btrim(l.cost_centre_code), '')          AS cost_centre_code,
    nullif(btrim(l.customer_id), '')               AS customer_id,
    l.debit,
    l.credit,
    l.debit - l.credit                             AS amount,
    e.reverses_entry_id,
    e.reverses_entry_id IS NOT NULL                AS is_reversal,
    EXISTS (SELECT 1 FROM raw.journal_entries r
            WHERE r.reverses_entry_id = e.entry_id) AS is_reversed,
    e.posted_at::date > (date_trunc('month', e.entry_date)
                         + interval '1 month - 1 day')::date AS is_late_posting
FROM raw.journal_lines l
JOIN raw.journal_entries e ON e.entry_id = l.entry_id;

-- Grain: one row per sales invoice.
CREATE VIEW clean.invoices AS
SELECT invoice_id, btrim(invoice_number) AS invoice_number,
       btrim(customer_id) AS customer_id, invoice_date, due_date, amount,
       btrim(revenue_account_code) AS revenue_account_code, entry_id
FROM raw.invoices;

-- Grain: one row per customer receipt.
CREATE VIEW clean.payments AS
SELECT payment_id, invoice_id, payment_date, amount, entry_id
FROM raw.payments;

-- Grain: one row per month x cost centre x account.
CREATE VIEW clean.budget AS
SELECT period_start, btrim(cost_centre_code) AS cost_centre_code,
       btrim(account_code) AS account_code, amount
FROM raw.budget;
