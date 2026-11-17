"""Budget vs actual: reads reporting.budget_vs_actual_cost_centre and
reporting.budget_vs_actual. Totals and their percentages are computed in SQL
with the same reporting.variance_pct function the views use."""
from .base import Chart, Column, ReportContext, ReportView, Table, month_label, series

VARIANCE_COLUMNS = [
    Column("actual_amount", "Actual", "money"), Column("budget_amount", "Budget", "money"),
    Column("variance_amount", "Variance", "money"), Column("variance_pct", "Var %", "pct"),
    Column("ytd_actual_amount", "YTD actual", "money"),
    Column("ytd_budget_amount", "YTD budget", "money"),
    Column("ytd_variance_amount", "YTD variance", "money"),
    Column("ytd_variance_pct", "YTD var %", "pct"),
]
SUMS = """sum(actual_amount) AS actual_amount, sum(budget_amount) AS budget_amount,
          sum(variance_amount) AS variance_amount,
          reporting.variance_pct(sum(actual_amount), sum(budget_amount)) AS variance_pct,
          sum(ytd_actual_amount) AS ytd_actual_amount, sum(ytd_budget_amount) AS ytd_budget_amount,
          sum(ytd_variance_amount) AS ytd_variance_amount,
          reporting.variance_pct(sum(ytd_actual_amount), sum(ytd_budget_amount)) AS ytd_variance_pct"""


def build(ctx: ReportContext) -> ReportView:
    by_cc = ctx.db.query(
        f"""SELECT cost_centre_code, cost_centre_name, {SUMS},
                   bool_or(is_overspent) AS is_overspent,
                   grouping(cost_centre_code) = 1 AS is_total
            FROM reporting.budget_vs_actual_cost_centre
            WHERE period_start = %(period)s AND cost_centre_code = ANY(%(ccs)s)
            GROUP BY GROUPING SETS ((cost_centre_code, cost_centre_name), ())
            ORDER BY grouping(cost_centre_code), cost_centre_code""", ctx.params)
    for row in by_cc:
        if row["is_total"]:
            row.update(cost_centre_name="Total", status="", _class="total")
        else:
            row["status"] = "Over budget" if row["is_overspent"] else "Within budget"

    by_account = ctx.db.query(
        f"""SELECT account_code, account_name, {SUMS}
            FROM reporting.budget_vs_actual
            WHERE period_start = %(period)s AND cost_centre_code = ANY(%(ccs)s)
              AND statement_section = 'Operating expenses'
            GROUP BY account_code, account_name ORDER BY account_code""", ctx.params)

    trend = ctx.db.query(
        """SELECT period_start, sum(actual_amount) AS actual_amount,
                  sum(budget_amount) AS budget_amount
           FROM reporting.budget_vs_actual_cost_centre
           WHERE fiscal_year = %(fiscal_year)s AND period_start <= %(period)s
             AND cost_centre_code = ANY(%(ccs)s)
           GROUP BY period_start ORDER BY period_start""", ctx.params)

    cc_rows = [r for r in by_cc if not r["is_total"]]
    return ReportView(
        tables=[
            Table("By cost centre",
                  [Column("cost_centre_code", "Code"), Column("cost_centre_name", "Cost centre")]
                  + VARIANCE_COLUMNS + [Column("status", "Year to date", "status")], by_cc,
                  note="Over budget means year-to-date operating costs are more than 5% above budget."),
            Table("By account",
                  [Column("account_code", "Account"), Column("account_name", "Name")]
                  + VARIANCE_COLUMNS, by_account),
        ],
        charts=[
            Chart("Year to date: actual vs budget by cost centre", "bar",
                  [r["cost_centre_name"] for r in cc_rows],
                  [{"label": "Actual", "data": series(cc_rows, "ytd_actual_amount")},
                   {"label": "Budget", "data": series(cc_rows, "ytd_budget_amount")}]),
            Chart(f"Monthly operating costs vs budget, {ctx.fiscal_year}", "bar",
                  [month_label(r["period_start"]) for r in trend],
                  [{"label": "Actual", "data": series(trend, "actual_amount")},
                   {"label": "Budget", "data": series(trend, "budget_amount"), "type": "line"}]),
        ],
        notes=["Operating expenses only. Variance is actual less budget, "
               "so a positive variance is an overspend."],
    )
