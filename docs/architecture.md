# Architecture and number definitions

## Flow

```
datagen  ->  CSV  ->  raw.*  ->  clean.*  ->  reporting.*  ->  web app  ->  browser / Excel / CSV
                         \___________________________________/
                                    controls.*  (must be empty)
```

The app's database login can read `reporting` and `app` only.

## Layers

**raw.** One table per source extract, loaded by a full refresh in one
transaction. Primary keys and types, no foreign keys: integrity is proven by
`controls.orphaned_keys` rather than assumed, which is how a landing zone
behaves when the source system is not yours.

**clean.** One view per raw table. Trims text, turns empty strings into NULL,
adds `amount = debit - credit`, derives `period_start` from the accounting
date, and flags late postings and reversals. No aggregation, so it never
changes the number of rows.

**reporting.** Every measure the app shows. The app may filter and sum
additive columns; it may not compute a measure.

## Sign conventions

| Area | Convention |
|---|---|
| Ledger (`clean.journal_lines.amount`) | debit positive, credit negative; every entry sums to 0 |
| P&L views | signed by effect on profit: revenue positive, costs negative, so lines add to subtotals |
| Budget vs actual | natural sign: revenue and costs both positive; variance = actual - budget |
| Balance sheet | assets, liabilities, equity positive in their natural direction; accumulated depreciation negative |
| Cash flow | cash in positive, cash out negative |

**Favourable** means revenue at or above budget, or a cost at or below budget.

## Definitions

| Measure | Definition | Where |
|---|---|---|
| Year to date | Sum of months from January of the same fiscal year to the selected month | `pnl_monthly`, `budget_vs_actual` |
| Prior year | Same month, and same year-to-date, one year earlier; NULL when there is no prior year | `pnl_monthly` |
| Variance % | (actual - budget) / abs(budget) x 100, one decimal; NULL when budget is 0 | `reporting.variance_pct()` |
| Overspent | Year-to-date operating costs more than 5% over budget | `budget_vs_actual_cost_centre` |
| Gross margin | Gross profit / revenue | `key_ratios` |
| Operating margin | Operating profit / revenue | `key_ratios` |
| DSO | Closing trade receivables / revenue of the last 3 months x days in those months | `key_ratios` |
| Current ratio | Current assets / current liabilities | `key_ratios` |
| Invoice age | Days from invoice date to the month end | `aged_receivables_invoices` |
| Open amount | Invoice amount less receipts dated on or before the month end | `aged_receivables_invoices` |

## Why the balance sheet has an "accumulated profit" line

The ledger has no year-end closing entries (posting P&L to retained
earnings). The balance sheet therefore shows profit since the opening balance
on its own equity line, computed in `reporting.balance_sheet`. That is what
makes assets = liabilities + equity hold at every month end, and the control
`balance_sheet_out_of_balance` checks it.

## Cash flow

Indirect method. Each balance sheet account carries a `cash_flow_line` in the
chart of accounts; the monthly movement on every non-cash account is grouped
by that line and added to net profit. The result must equal the movement on
the cash account, which `controls.cash_flow_not_tied_to_cash` checks.

## Adding a report

1. Add a view to a new SQL file in `sql/` with its grain in a comment.
2. Add a migration in `migrations/versions/` that runs the file.
3. Add a row to `app.reports` (in the same migration) and a builder in
   `app/reports/`, registered in `app/reports/__init__.py`.
4. Grant it to groups in `app.group_report_access`.

## Adding a control

Add a view to the `controls` schema that returns violating rows, with a
`COMMENT ON VIEW` describing the rule. The runner finds it automatically.
