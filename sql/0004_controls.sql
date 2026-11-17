-- =========================================================================
-- CONTROLS: one view per control. Every view returns the rows that VIOLATE
-- the control, so an empty result means the control passes. The runner
-- (scripts/run_checks.py) discovers every view in this schema, so adding a
-- control is just adding a view with a comment. Each control recomputes its
-- comparison figure from the raw tables, not from the views it is testing.
-- =========================================================================
CREATE SCHEMA controls;

CREATE VIEW controls.unbalanced_journal_entries AS
SELECT e.entry_id, e.entry_number, e.entry_date,
       sum(l.debit) AS total_debit, sum(l.credit) AS total_credit,
       sum(l.debit) - sum(l.credit) AS difference
FROM raw.journal_entries e
JOIN raw.journal_lines l USING (entry_id)
GROUP BY 1, 2, 3
HAVING sum(l.debit) <> sum(l.credit);
COMMENT ON VIEW controls.unbalanced_journal_entries IS
    'Every journal entry balances: total debits equal total credits.';

CREATE VIEW controls.invalid_journal_lines AS
SELECT l.line_id, l.entry_id, l.account_code, l.debit, l.credit,
       CASE WHEN l.debit < 0 OR l.credit < 0 THEN 'negative amount'
            WHEN l.debit <> 0 AND l.credit <> 0 THEN 'both debit and credit set'
            WHEN l.debit = 0 AND l.credit = 0 THEN 'zero-value line'
            ELSE 'P&L line without a cost centre' END AS problem
FROM raw.journal_lines l
LEFT JOIN raw.chart_of_accounts a USING (account_code)
WHERE l.debit < 0 OR l.credit < 0
   OR (l.debit <> 0 AND l.credit <> 0)
   OR (l.debit = 0 AND l.credit = 0)
   OR (a.account_type IN ('revenue', 'expense')
       AND nullif(btrim(l.cost_centre_code), '') IS NULL);
COMMENT ON VIEW controls.invalid_journal_lines IS
    'Each line is one-sided, non-negative and non-zero; every P&L line carries a cost centre.';

CREATE VIEW controls.balance_sheet_out_of_balance AS
SELECT period_end, total_assets, total_liabilities, total_equity, difference
FROM reporting.balance_sheet_totals
WHERE difference <> 0;
COMMENT ON VIEW controls.balance_sheet_out_of_balance IS
    'Assets equal liabilities plus equity at every month end.';

CREATE VIEW controls.pnl_not_tied_to_ledger AS
WITH ledger AS (
    SELECT date_trunc('month', e.entry_date)::date AS period_start,
           sum(l.credit) - sum(l.debit) AS net_profit
    FROM raw.journal_lines l
    JOIN raw.journal_entries e USING (entry_id)
    JOIN raw.chart_of_accounts a USING (account_code)
    WHERE a.account_type IN ('revenue', 'expense')
    GROUP BY 1
),
statement AS (
    SELECT period_start, sum(amount) AS net_profit
    FROM reporting.pnl_statement WHERE line_name = 'Net profit' GROUP BY 1
),
detail AS (
    SELECT period_start, sum(amount) AS net_profit
    FROM reporting.pnl_monthly GROUP BY 1
)
SELECT period_start,
       l.net_profit AS ledger_net_profit,
       s.net_profit AS statement_net_profit,
       d.net_profit AS detail_net_profit
FROM ledger l
FULL JOIN statement s USING (period_start)
FULL JOIN detail d USING (period_start)
WHERE l.net_profit IS DISTINCT FROM s.net_profit
   OR l.net_profit IS DISTINCT FROM d.net_profit;
COMMENT ON VIEW controls.pnl_not_tied_to_ledger IS
    'Monthly net profit in the P&L views ties to the raw ledger to the cent.';

CREATE VIEW controls.postings_in_closed_periods AS
SELECT e.entry_id, e.entry_number, e.entry_date, e.posted_at, p.closed_at
FROM raw.journal_entries e
JOIN raw.fiscal_periods p ON p.period_start = date_trunc('month', e.entry_date)::date
WHERE p.closed_at IS NOT NULL AND e.posted_at > p.closed_at;
COMMENT ON VIEW controls.postings_in_closed_periods IS
    'No journal entry was posted into a period after that period was closed.';

CREATE VIEW controls.entries_outside_fiscal_periods AS
SELECT e.entry_id, e.entry_number, e.entry_date
FROM raw.journal_entries e
LEFT JOIN raw.fiscal_periods p ON p.period_start = date_trunc('month', e.entry_date)::date
WHERE p.period_start IS NULL;
COMMENT ON VIEW controls.entries_outside_fiscal_periods IS
    'Every journal entry falls in a defined fiscal period.';

CREATE VIEW controls.orphaned_keys AS
SELECT 'journal_lines.entry_id' AS reference, l.line_id::text AS row_key, l.entry_id::text AS missing_key
FROM raw.journal_lines l LEFT JOIN raw.journal_entries e USING (entry_id) WHERE e.entry_id IS NULL
UNION ALL
SELECT 'journal_entries without lines', e.entry_id::text, NULL
FROM raw.journal_entries e WHERE NOT EXISTS (SELECT 1 FROM raw.journal_lines l WHERE l.entry_id = e.entry_id)
UNION ALL
SELECT 'journal_lines.account_code', l.line_id::text, l.account_code
FROM raw.journal_lines l LEFT JOIN raw.chart_of_accounts a USING (account_code) WHERE a.account_code IS NULL
UNION ALL
SELECT 'journal_lines.cost_centre_code', l.line_id::text, l.cost_centre_code
FROM raw.journal_lines l LEFT JOIN raw.cost_centres c USING (cost_centre_code)
WHERE nullif(btrim(l.cost_centre_code), '') IS NOT NULL AND c.cost_centre_code IS NULL
UNION ALL
SELECT 'journal_lines.customer_id', l.line_id::text, l.customer_id
FROM raw.journal_lines l LEFT JOIN raw.customers c USING (customer_id)
WHERE nullif(btrim(l.customer_id), '') IS NOT NULL AND c.customer_id IS NULL
UNION ALL
SELECT 'journal_entries.reverses_entry_id', e.entry_id::text, e.reverses_entry_id::text
FROM raw.journal_entries e LEFT JOIN raw.journal_entries o ON o.entry_id = e.reverses_entry_id
WHERE e.reverses_entry_id IS NOT NULL AND o.entry_id IS NULL
UNION ALL
SELECT 'invoices.customer_id', i.invoice_id::text, i.customer_id
FROM raw.invoices i LEFT JOIN raw.customers c USING (customer_id) WHERE c.customer_id IS NULL
UNION ALL
SELECT 'invoices.entry_id', i.invoice_id::text, i.entry_id::text
FROM raw.invoices i LEFT JOIN raw.journal_entries e USING (entry_id) WHERE e.entry_id IS NULL
UNION ALL
SELECT 'payments.invoice_id', p.payment_id::text, p.invoice_id::text
FROM raw.payments p LEFT JOIN raw.invoices i USING (invoice_id) WHERE i.invoice_id IS NULL
UNION ALL
SELECT 'payments.entry_id', p.payment_id::text, p.entry_id::text
FROM raw.payments p LEFT JOIN raw.journal_entries e USING (entry_id) WHERE e.entry_id IS NULL
UNION ALL
SELECT 'budget.cost_centre_code', b.period_start::text, b.cost_centre_code
FROM raw.budget b LEFT JOIN raw.cost_centres c USING (cost_centre_code) WHERE c.cost_centre_code IS NULL
UNION ALL
SELECT 'budget.account_code', b.period_start::text, b.account_code
FROM raw.budget b LEFT JOIN raw.chart_of_accounts a USING (account_code) WHERE a.account_code IS NULL
UNION ALL
SELECT 'budget.period_start', b.period_start::text, b.period_start::text
FROM raw.budget b LEFT JOIN raw.fiscal_periods p USING (period_start) WHERE p.period_start IS NULL;
COMMENT ON VIEW controls.orphaned_keys IS
    'No orphaned keys: every reference between raw tables resolves.';

CREATE VIEW controls.overpaid_invoices AS
SELECT i.invoice_id, i.invoice_number, i.amount AS invoice_amount, sum(p.amount) AS paid_amount
FROM raw.invoices i
JOIN raw.payments p USING (invoice_id)
GROUP BY 1, 2, 3
HAVING sum(p.amount) > i.amount;
COMMENT ON VIEW controls.overpaid_invoices IS
    'No invoice has receipts applied in excess of its amount.';

CREATE VIEW controls.receivables_not_tied_to_ledger AS
WITH ledger AS (
    SELECT p.period_start, coalesce(sum(l.debit - l.credit), 0) AS balance
    FROM raw.fiscal_periods p
    LEFT JOIN (raw.journal_lines l JOIN raw.journal_entries e USING (entry_id))
           ON e.entry_date <= p.period_end AND l.account_code = '1100'
    WHERE NOT p.is_opening_period
    GROUP BY 1
),
subledger AS (
    SELECT period_start, sum(total_open) AS balance
    FROM reporting.aged_receivables GROUP BY 1
)
SELECT period_start, l.balance AS ledger_receivables,
       coalesce(s.balance, 0) AS aged_receivables_total
FROM ledger l
LEFT JOIN subledger s USING (period_start)
WHERE l.balance <> coalesce(s.balance, 0);
COMMENT ON VIEW controls.receivables_not_tied_to_ledger IS
    'Aged receivables total equals the trade receivables control account at every month end.';

CREATE VIEW controls.cash_flow_not_tied_to_cash AS
WITH ledger AS (
    SELECT date_trunc('month', e.entry_date)::date AS period_start,
           sum(l.debit - l.credit) AS cash_movement
    FROM raw.journal_lines l
    JOIN raw.journal_entries e USING (entry_id)
    WHERE l.account_code = '1000'
    GROUP BY 1
),
statement AS (
    SELECT period_start, amount AS net_change
    FROM reporting.cash_flow WHERE line_name = 'Net change in cash'
)
SELECT period_start, s.net_change AS cash_flow_net_change,
       coalesce(l.cash_movement, 0) AS ledger_cash_movement
FROM statement s
LEFT JOIN ledger l USING (period_start)
WHERE s.net_change <> coalesce(l.cash_movement, 0);
COMMENT ON VIEW controls.cash_flow_not_tied_to_cash IS
    'Net change in cash on the cash flow statement equals the movement on the cash account.';
