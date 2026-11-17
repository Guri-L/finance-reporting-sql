-- =========================================================================
-- REPORTING LAYER: the single definition of every number the web app shows.
-- The app is only allowed to filter these views and add up their additive
-- columns; it never recalculates a measure. Percentages that have to be
-- recomputed for a filtered total go through the functions defined here, so
-- even then the formula lives in one place.
--
-- Sign conventions
--   P&L views          amounts are signed by profit impact: revenue positive,
--                      costs negative, so lines add up to the subtotals.
--   Budget vs actual   natural sign: revenue and costs both positive.
--   Balance sheet      assets, liabilities and equity all positive in their
--                      natural direction (accumulated depreciation negative).
--   Cash flow          cash in positive, cash out negative.
-- =========================================================================
CREATE SCHEMA reporting;

-- Variance of actual against budget as a percentage of budget, one decimal.
CREATE FUNCTION reporting.variance_pct(actual numeric, budget numeric)
RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN budget IS NULL OR budget = 0 THEN NULL
                ELSE round((actual - budget) / abs(budget) * 100, 1) END
$$;

-- numerator / denominator as a percentage, one decimal. NULL when undefined.
CREATE FUNCTION reporting.pct_of(numerator numeric, denominator numeric)
RETURNS numeric LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN denominator IS NULL OR denominator = 0 THEN NULL
                ELSE round(numerator / denominator * 100, 1) END
$$;

-- Grain: one row per reportable month (the opening period is excluded).
CREATE VIEW reporting.periods AS
SELECT period_start, period_end, fiscal_year, status,
       to_char(period_start, 'YYYY-MM') AS period_key,
       to_char(period_start, 'Mon YYYY') AS period_label
FROM clean.periods
WHERE NOT is_opening_period;

-- Grain: one row per cost centre.
CREATE VIEW reporting.cost_centres AS
SELECT cost_centre_code, cost_centre_name, manager_name FROM clean.cost_centres;

-- -------------------------------------------------------------------------
-- Profit and loss
-- -------------------------------------------------------------------------
-- Grain: one row per month x cost centre x P&L account. Dense: every
-- cost centre/account pair that has ever been posted to gets a row in every
-- month, so year-to-date and prior-year columns never have gaps.
-- (P&L lines without a cost centre would be dropped here; the control
-- controls.invalid_journal_lines guarantees there are none.)
CREATE VIEW reporting.pnl_monthly AS
WITH actuals AS (
    SELECT jl.period_start, jl.cost_centre_code, jl.account_code,
           -sum(jl.amount) AS amount            -- credit balance = profit
    FROM clean.journal_lines jl
    JOIN clean.accounts a USING (account_code)
    WHERE a.is_pnl
    GROUP BY 1, 2, 3
),
pairs AS (
    SELECT DISTINCT cost_centre_code, account_code FROM actuals
),
filled AS (
    SELECT p.period_start, p.fiscal_year, p.prior_year_period_start,
           k.cost_centre_code, k.account_code,
           coalesce(a.amount, 0) AS amount,
           sum(coalesce(a.amount, 0)) OVER (
               PARTITION BY p.fiscal_year, k.cost_centre_code, k.account_code
               ORDER BY p.period_start) AS ytd_amount
    FROM clean.periods p
    CROSS JOIN pairs k
    LEFT JOIN actuals a
           ON a.period_start = p.period_start
          AND a.cost_centre_code = k.cost_centre_code
          AND a.account_code = k.account_code
    WHERE NOT p.is_opening_period
)
SELECT f.period_start, f.fiscal_year, f.cost_centre_code, f.account_code,
       acc.account_name, acc.account_type, acc.statement_section, acc.section_order,
       f.amount,
       f.ytd_amount,
       py.amount     AS prior_year_amount,       -- same month last year
       py.ytd_amount AS prior_year_ytd_amount    -- NULL when there is no prior year
FROM filled f
JOIN clean.accounts acc USING (account_code)
LEFT JOIN filled py
       ON py.period_start = f.prior_year_period_start
      AND py.cost_centre_code = f.cost_centre_code
      AND py.account_code = f.account_code;

-- Grain: one row per month x cost centre x statement line (seven lines:
-- four sections and the three subtotals built from them). All columns are
-- additive across cost centres.
CREATE VIEW reporting.pnl_statement AS
WITH sections AS (
    SELECT period_start, fiscal_year, cost_centre_code, statement_section,
           sum(amount) AS amount, sum(ytd_amount) AS ytd_amount,
           sum(prior_year_amount) AS prior_year_amount,
           sum(prior_year_ytd_amount) AS prior_year_ytd_amount
    FROM reporting.pnl_monthly
    GROUP BY 1, 2, 3, 4
),
statement_lines (line_order, line_name, is_subtotal, sections) AS (
    VALUES (10, 'Revenue',            false, ARRAY['Revenue']),
           (20, 'Cost of sales',      false, ARRAY['Cost of sales']),
           (30, 'Gross profit',       true,  ARRAY['Revenue', 'Cost of sales']),
           (40, 'Operating expenses', false, ARRAY['Operating expenses']),
           (50, 'Operating profit',   true,  ARRAY['Revenue', 'Cost of sales', 'Operating expenses']),
           (60, 'Finance costs',      false, ARRAY['Finance costs']),
           (70, 'Net profit',         true,  ARRAY['Revenue', 'Cost of sales', 'Operating expenses', 'Finance costs'])
),
keys AS (
    SELECT DISTINCT period_start, fiscal_year, cost_centre_code FROM sections
)
SELECT k.period_start, k.fiscal_year, k.cost_centre_code,
       l.line_order, l.line_name, l.is_subtotal,
       coalesce(sum(s.amount), 0)     AS amount,
       coalesce(sum(s.ytd_amount), 0) AS ytd_amount,
       sum(s.prior_year_amount)       AS prior_year_amount,
       sum(s.prior_year_ytd_amount)   AS prior_year_ytd_amount
FROM keys k
CROSS JOIN statement_lines l
LEFT JOIN sections s
       ON s.period_start = k.period_start
      AND s.cost_centre_code = k.cost_centre_code
      AND s.statement_section = ANY (l.sections)
GROUP BY 1, 2, 3, 4, 5, 6;

-- -------------------------------------------------------------------------
-- Budget vs actual
-- -------------------------------------------------------------------------
-- Grain: one row per month x cost centre x P&L account.
-- variance = actual - budget. Favourable means revenue at or above budget,
-- or cost at or below budget.
CREATE VIEW reporting.budget_vs_actual AS
WITH keys AS (
    SELECT period_start, cost_centre_code, account_code FROM reporting.pnl_monthly
    UNION
    SELECT period_start, cost_centre_code, account_code FROM clean.budget
),
base AS (
    SELECT k.period_start, p.fiscal_year, k.cost_centre_code, k.account_code,
           acc.account_name, acc.account_type, acc.statement_section, acc.section_order,
           coalesce(a.amount, 0)
               * CASE WHEN acc.account_type = 'revenue' THEN 1 ELSE -1 END AS actual_amount,
           coalesce(b.amount, 0) AS budget_amount
    FROM keys k
    JOIN reporting.periods p USING (period_start)
    JOIN clean.accounts acc USING (account_code)
    LEFT JOIN reporting.pnl_monthly a USING (period_start, cost_centre_code, account_code)
    LEFT JOIN clean.budget b USING (period_start, cost_centre_code, account_code)
),
with_ytd AS (
    SELECT base.*,
           sum(actual_amount) OVER w AS ytd_actual_amount,
           sum(budget_amount) OVER w AS ytd_budget_amount
    FROM base
    WINDOW w AS (PARTITION BY fiscal_year, cost_centre_code, account_code ORDER BY period_start)
)
SELECT period_start, fiscal_year, cost_centre_code, account_code, account_name,
       account_type, statement_section, section_order,
       actual_amount, budget_amount,
       actual_amount - budget_amount                             AS variance_amount,
       reporting.variance_pct(actual_amount, budget_amount)      AS variance_pct,
       ytd_actual_amount, ytd_budget_amount,
       ytd_actual_amount - ytd_budget_amount                     AS ytd_variance_amount,
       reporting.variance_pct(ytd_actual_amount, ytd_budget_amount) AS ytd_variance_pct,
       CASE WHEN account_type = 'revenue' THEN actual_amount >= budget_amount
            ELSE actual_amount <= budget_amount END              AS is_favourable
FROM with_ytd;

-- Grain: one row per month x cost centre. Operating expenses only, which is
-- what a cost centre owner controls. is_overspent is true when year-to-date
-- costs are more than 5% over budget (small timing differences are not flagged).
CREATE VIEW reporting.budget_vs_actual_cost_centre AS
SELECT b.period_start, b.fiscal_year, b.cost_centre_code, cc.cost_centre_name,
       sum(b.actual_amount)   AS actual_amount,
       sum(b.budget_amount)   AS budget_amount,
       sum(b.variance_amount) AS variance_amount,
       reporting.variance_pct(sum(b.actual_amount), sum(b.budget_amount)) AS variance_pct,
       sum(b.ytd_actual_amount)   AS ytd_actual_amount,
       sum(b.ytd_budget_amount)   AS ytd_budget_amount,
       sum(b.ytd_variance_amount) AS ytd_variance_amount,
       reporting.variance_pct(sum(b.ytd_actual_amount), sum(b.ytd_budget_amount)) AS ytd_variance_pct,
       coalesce(reporting.variance_pct(sum(b.ytd_actual_amount), sum(b.ytd_budget_amount)), 0) > 5
           AS is_overspent
FROM reporting.budget_vs_actual b
JOIN clean.cost_centres cc USING (cost_centre_code)
WHERE b.statement_section = 'Operating expenses'
GROUP BY 1, 2, 3, 4;

-- -------------------------------------------------------------------------
-- Balance sheet
-- -------------------------------------------------------------------------
-- Grain: one row per month end x balance sheet line. A line is either a
-- balance sheet account or the one derived equity line holding profit
-- accumulated since the opening balance (the ledger has no year-end closing
-- entries, so retained earnings for the reporting window is computed here).
CREATE VIEW reporting.balance_sheet AS
WITH movements AS (
    SELECT jl.period_start, jl.account_code, sum(jl.amount) AS amount
    FROM clean.journal_lines jl
    GROUP BY 1, 2
),
account_lines AS (
    SELECT p.period_start, p.period_end, a.statement_section, a.section_order,
           a.account_code, a.account_name AS line_name, a.account_type,
           coalesce(sum(m.amount), 0) * a.balance_sign AS amount
    FROM reporting.periods p
    CROSS JOIN clean.accounts a
    LEFT JOIN movements m
           ON m.account_code = a.account_code AND m.period_start <= p.period_start
    WHERE a.is_balance_sheet
    GROUP BY p.period_start, p.period_end, a.statement_section, a.section_order,
             a.account_code, a.account_name, a.account_type, a.balance_sign
),
accumulated_profit AS (
    SELECT p.period_start, p.period_end, -coalesce(sum(m.amount), 0) AS amount
    FROM reporting.periods p
    LEFT JOIN (movements m JOIN clean.accounts a
               ON a.account_code = m.account_code AND a.is_pnl)
           ON m.period_start <= p.period_start
    GROUP BY 1, 2
)
SELECT period_start, period_end, statement_section, section_order,
       account_code AS line_code, account_code, line_name, account_type, amount
FROM account_lines
UNION ALL
SELECT period_start, period_end, 'Equity', 310,
       '3900', NULL, 'Accumulated profit since opening balance', 'equity', amount
FROM accumulated_profit;

-- Grain: one row per month end.
CREATE VIEW reporting.balance_sheet_totals AS
SELECT period_start, period_end,
       sum(amount) FILTER (WHERE account_type = 'asset')     AS total_assets,
       sum(amount) FILTER (WHERE account_type = 'liability') AS total_liabilities,
       sum(amount) FILTER (WHERE account_type = 'equity')    AS total_equity,
       sum(amount) FILTER (WHERE statement_section = 'Current assets')      AS current_assets,
       sum(amount) FILTER (WHERE statement_section = 'Current liabilities') AS current_liabilities,
       sum(amount) FILTER (WHERE account_type = 'asset')
         - sum(amount) FILTER (WHERE account_type IN ('liability', 'equity')) AS difference
FROM reporting.balance_sheet
GROUP BY 1, 2;

-- -------------------------------------------------------------------------
-- Cash flow (indirect method)
-- -------------------------------------------------------------------------
-- Grain: one row per month x cash flow line. Detail lines come from the
-- monthly movement on each non-cash balance sheet account, grouped by the
-- cash_flow_line set on the chart of accounts, plus net profit. Lines that
-- never move in the reporting window are left out. ytd_amount accumulates
-- within the fiscal year; for opening cash it is the balance at the start of
-- the year and for closing cash the balance at the end of the month.
CREATE VIEW reporting.cash_flow AS
WITH line_map (line_name, category, line_order) AS (
    VALUES ('Net profit',                  'Operating', 10),
           ('Depreciation',                'Operating', 20),
           ('Change in trade receivables', 'Operating', 30),
           ('Change in inventory',         'Operating', 40),
           ('Change in prepayments',       'Operating', 50),
           ('Change in trade payables',    'Operating', 60),
           ('Change in accrued expenses',  'Operating', 70),
           ('Purchase of fixed assets',    'Investing', 110),
           ('Loan repayments',             'Financing', 210),
           ('Share capital issued',        'Financing', 220),
           ('Other equity movements',      'Financing', 230)
),
movements AS (
    SELECT jl.period_start,
           CASE WHEN a.is_pnl THEN 'Net profit' ELSE a.cash_flow_line END AS line_name,
           -sum(jl.amount) AS amount       -- a credit movement is a source of cash
    FROM clean.journal_lines jl
    JOIN clean.accounts a USING (account_code)
    WHERE a.is_pnl OR a.cash_flow_line <> 'Cash'
    GROUP BY 1, 2
),
detail AS (
    SELECT p.period_start, p.fiscal_year, lm.category, lm.line_order, lm.line_name,
           coalesce(m.amount, 0) AS amount
    FROM reporting.periods p
    CROSS JOIN line_map lm
    LEFT JOIN movements m ON m.period_start = p.period_start AND m.line_name = lm.line_name
),
active_detail AS (
    SELECT * FROM (
        SELECT d.*, bool_or(amount <> 0) OVER (PARTITION BY line_name) AS ever_moves
        FROM detail d) x
    WHERE ever_moves
),
cash AS (
    SELECT period_start,
           sum(amount) FILTER (WHERE account_code IN
               (SELECT account_code FROM clean.accounts WHERE cash_flow_line = 'Cash')) AS closing_cash
    FROM reporting.balance_sheet
    GROUP BY 1
),
flows AS (
    SELECT period_start, fiscal_year, category, line_order, line_name, false AS is_subtotal, amount
    FROM active_detail
    UNION ALL
    SELECT period_start, fiscal_year, category,
           CASE category WHEN 'Operating' THEN 100 WHEN 'Investing' THEN 200 ELSE 300 END,
           'Net cash from ' || lower(category) || ' activities', true, sum(amount)
    FROM active_detail GROUP BY 1, 2, 3
    UNION ALL
    SELECT period_start, fiscal_year, 'Cash', 400, 'Net change in cash', true, sum(amount)
    FROM active_detail GROUP BY 1, 2
)
SELECT period_start, fiscal_year, category, line_order, line_name, is_subtotal, amount,
       sum(amount) OVER (PARTITION BY fiscal_year, line_name ORDER BY period_start) AS ytd_amount
FROM flows
UNION ALL
SELECT p.period_start, p.fiscal_year, 'Cash', 410, 'Opening cash', true,
       c.closing_cash - nc.amount,
       first_value(c.closing_cash - nc.amount)
           OVER (PARTITION BY p.fiscal_year ORDER BY p.period_start)
FROM reporting.periods p
JOIN cash c USING (period_start)
JOIN (SELECT period_start, sum(amount) AS amount FROM active_detail GROUP BY 1) nc USING (period_start)
UNION ALL
SELECT p.period_start, p.fiscal_year, 'Cash', 420, 'Closing cash', true,
       c.closing_cash, c.closing_cash
FROM reporting.periods p
JOIN cash c USING (period_start);

-- -------------------------------------------------------------------------
-- Aged receivables
-- -------------------------------------------------------------------------
-- Grain: one row per month end (as-of date) x invoice still open on that
-- date. Open amount = invoice amount less receipts dated on or before the
-- as-of date. Age is counted in days from the invoice date.
CREATE VIEW reporting.aged_receivables_invoices AS
SELECT p.period_start, p.period_end AS as_of_date,
       i.invoice_id, i.invoice_number, i.customer_id, c.customer_name,
       i.invoice_date, i.due_date,
       i.amount AS invoice_amount,
       i.amount - coalesce(paid.amount, 0) AS open_amount,
       p.period_end - i.invoice_date AS age_days,
       CASE WHEN p.period_end - i.invoice_date <= 30 THEN '0-30'
            WHEN p.period_end - i.invoice_date <= 60 THEN '31-60'
            WHEN p.period_end - i.invoice_date <= 90 THEN '61-90'
            ELSE '90+' END AS age_bucket,
       p.period_end > i.due_date AS is_overdue
FROM reporting.periods p
JOIN clean.invoices i ON i.invoice_date <= p.period_end
JOIN clean.customers c USING (customer_id)
LEFT JOIN LATERAL (
    SELECT sum(py.amount) AS amount
    FROM clean.payments py
    WHERE py.invoice_id = i.invoice_id AND py.payment_date <= p.period_end
) paid ON true
WHERE i.amount - coalesce(paid.amount, 0) <> 0;

-- Grain: one row per month end (as-of date) x customer with an open balance.
CREATE VIEW reporting.aged_receivables AS
SELECT period_start, as_of_date, customer_id, customer_name,
       coalesce(sum(open_amount) FILTER (WHERE age_bucket = '0-30'), 0)  AS bucket_0_30,
       coalesce(sum(open_amount) FILTER (WHERE age_bucket = '31-60'), 0) AS bucket_31_60,
       coalesce(sum(open_amount) FILTER (WHERE age_bucket = '61-90'), 0) AS bucket_61_90,
       coalesce(sum(open_amount) FILTER (WHERE age_bucket = '90+'), 0)   AS bucket_over_90,
       sum(open_amount) AS total_open,
       count(*)         AS open_invoices
FROM reporting.aged_receivables_invoices
GROUP BY 1, 2, 3, 4;

-- -------------------------------------------------------------------------
-- Key ratios
-- -------------------------------------------------------------------------
-- Grain: one row per month, whole company.
--   gross margin      = gross profit / revenue
--   operating margin  = operating profit / revenue
--   DSO               = closing receivables / revenue of the last three
--                       months (fewer at the start) x days in those months
--   current ratio     = current assets / current liabilities
CREATE VIEW reporting.key_ratios AS
WITH pnl AS (
    SELECT period_start,
           sum(amount) FILTER (WHERE line_name = 'Revenue')          AS revenue,
           sum(amount) FILTER (WHERE line_name = 'Gross profit')     AS gross_profit,
           sum(amount) FILTER (WHERE line_name = 'Operating profit') AS operating_profit,
           sum(amount) FILTER (WHERE line_name = 'Net profit')       AS net_profit
    FROM reporting.pnl_statement
    GROUP BY 1
),
receivables AS (
    SELECT period_start, sum(amount) AS trade_receivables
    FROM reporting.balance_sheet
    WHERE line_name = 'Trade receivables'
    GROUP BY 1
),
rolling AS (
    SELECT p.period_start, p.period_end, p.fiscal_year,
           sum(pnl.revenue) OVER w AS trailing_revenue,
           sum(p.period_end - p.period_start + 1) OVER w AS trailing_days
    FROM reporting.periods p
    JOIN pnl USING (period_start)
    WINDOW w AS (ORDER BY p.period_start ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)
)
SELECT t.period_start, t.period_end, t.fiscal_year,
       pnl.revenue, pnl.gross_profit, pnl.operating_profit, pnl.net_profit,
       reporting.pct_of(pnl.gross_profit, pnl.revenue)     AS gross_margin_pct,
       reporting.pct_of(pnl.operating_profit, pnl.revenue) AS operating_margin_pct,
       r.trade_receivables,
       round(r.trade_receivables / nullif(t.trailing_revenue, 0) * t.trailing_days, 1) AS dso_days,
       b.current_assets, b.current_liabilities,
       round(b.current_assets / nullif(b.current_liabilities, 0), 2) AS current_ratio
FROM rolling t
JOIN pnl USING (period_start)
JOIN receivables r USING (period_start)
JOIN reporting.balance_sheet_totals b USING (period_start);
