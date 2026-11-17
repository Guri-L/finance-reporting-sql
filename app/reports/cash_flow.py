"""Cash flow summary: reads reporting.cash_flow."""
from .base import Chart, Column, ReportContext, ReportView, Table, month_label, series


def build(ctx: ReportContext) -> ReportView:
    rows = ctx.db.query(
        """SELECT category, line_name, is_subtotal, amount, ytd_amount
           FROM reporting.cash_flow WHERE period_start = %(period)s
           ORDER BY line_order""", ctx.params)
    table_rows, last_category = [], None
    for row in rows:
        if row["category"] != last_category and row["category"] != "Cash":
            table_rows.append({"line_name": f"{row['category']} activities", "_class": "section"})
        last_category = row["category"]
        row["_class"] = ("total" if row["category"] == "Cash" else "subtotal") \
            if row["is_subtotal"] else ""
        table_rows.append(row)

    trend = ctx.db.query(
        """SELECT period_start,
                  sum(amount) FILTER (WHERE line_name = 'Net cash from operating activities') AS operating,
                  sum(amount) FILTER (WHERE line_name = 'Net cash from investing activities') AS investing,
                  sum(amount) FILTER (WHERE line_name = 'Net cash from financing activities') AS financing,
                  sum(amount) FILTER (WHERE line_name = 'Closing cash') AS closing_cash
           FROM reporting.cash_flow
           WHERE period_start <= %(period)s AND period_start > %(period)s - interval '12 months'
           GROUP BY period_start ORDER BY period_start""", ctx.params)

    return ReportView(
        tables=[Table("Cash flow summary",
                      [Column("line_name", "Line"), Column("amount", "Month", "money"),
                       Column("ytd_amount", "Year to date", "money")], table_rows,
                      note="Year to date for opening cash is the balance at the start of the "
                           "fiscal year.")],
        charts=[Chart("Cash flow by activity and closing cash, last 12 months", "bar",
                      [month_label(r["period_start"]) for r in trend],
                      [{"label": "Operating", "data": series(trend, "operating")},
                       {"label": "Investing", "data": series(trend, "investing")},
                       {"label": "Financing", "data": series(trend, "financing")},
                       {"label": "Closing cash", "data": series(trend, "closing_cash"),
                        "type": "line"}], stacked=True)],
        notes=["Indirect method: net profit adjusted for non-cash items and working capital "
               "movements. Cash out is shown in brackets."],
    )
