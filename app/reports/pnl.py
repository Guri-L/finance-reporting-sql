"""Profit and loss: reads reporting.pnl_statement and reporting.pnl_monthly."""
from .base import Chart, Column, ReportContext, ReportView, Table, month_label, series

AMOUNT_COLUMNS = [
    Column("amount", "Month", "money"),
    Column("prior_year_amount", "Same month last year", "money"),
    Column("ytd_amount", "Year to date", "money"),
    Column("prior_year_ytd_amount", "Last year to date", "money"),
]


def build(ctx: ReportContext) -> ReportView:
    statement = ctx.db.query(
        """SELECT line_name, is_subtotal,
                  sum(amount) AS amount, sum(prior_year_amount) AS prior_year_amount,
                  sum(ytd_amount) AS ytd_amount, sum(prior_year_ytd_amount) AS prior_year_ytd_amount
           FROM reporting.pnl_statement
           WHERE period_start = %(period)s AND cost_centre_code = ANY(%(ccs)s)
           GROUP BY line_order, line_name, is_subtotal
           ORDER BY line_order""", ctx.params)
    for row in statement:
        row["_class"] = "subtotal" if row["is_subtotal"] else ""

    accounts = ctx.db.query(
        """SELECT statement_section, account_code, account_name,
                  sum(amount) AS amount, sum(prior_year_amount) AS prior_year_amount,
                  sum(ytd_amount) AS ytd_amount, sum(prior_year_ytd_amount) AS prior_year_ytd_amount
           FROM reporting.pnl_monthly
           WHERE period_start = %(period)s AND cost_centre_code = ANY(%(ccs)s)
           GROUP BY section_order, statement_section, account_code, account_name
           ORDER BY section_order, account_code""", ctx.params)

    trend = ctx.db.query(
        """SELECT period_start,
                  sum(amount) FILTER (WHERE line_name = 'Revenue') AS revenue,
                  sum(amount) FILTER (WHERE line_name = 'Operating expenses') AS operating_expenses,
                  sum(amount) FILTER (WHERE line_name = 'Operating profit') AS operating_profit
           FROM reporting.pnl_statement
           WHERE cost_centre_code = ANY(%(ccs)s)
             AND period_start <= %(period)s
             AND period_start > %(period)s - interval '12 months'
           GROUP BY period_start ORDER BY period_start""", ctx.params)

    return ReportView(
        tables=[
            Table("Statement", [Column("line_name", "Line")] + AMOUNT_COLUMNS, statement),
            Table("By account",
                  [Column("statement_section", "Section"), Column("account_code", "Account"),
                   Column("account_name", "Name")] + AMOUNT_COLUMNS, accounts),
        ],
        charts=[Chart(
            "Revenue, operating expenses and operating profit, last 12 months", "bar",
            [month_label(r["period_start"]) for r in trend],
            [{"label": "Revenue", "data": series(trend, "revenue")},
             {"label": "Operating expenses", "data": series(trend, "operating_expenses")},
             {"label": "Operating profit", "data": series(trend, "operating_profit"),
              "type": "line"}])],
        notes=["Amounts are signed by their effect on profit: costs are shown in brackets."],
    )
