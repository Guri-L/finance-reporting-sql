"""Key ratios: reads reporting.key_ratios."""
from .base import Chart, Column, Kpi, ReportContext, ReportView, Table, month_label, series


def build(ctx: ReportContext) -> ReportView:
    rows = ctx.db.query(
        """SELECT period_start, to_char(period_start, 'Mon YYYY') AS period_label,
                  revenue, gross_profit, operating_profit,
                  gross_margin_pct, operating_margin_pct, dso_days, current_ratio
           FROM reporting.key_ratios
           WHERE period_start <= %(period)s AND period_start > %(period)s - interval '12 months'
           ORDER BY period_start""", ctx.params)
    current = rows[-1]
    labels = [month_label(r["period_start"]) for r in rows]
    return ReportView(
        kpis=[Kpi("Gross margin", current["gross_margin_pct"], "pct"),
              Kpi("Operating margin", current["operating_margin_pct"], "pct"),
              Kpi("Days sales outstanding", current["dso_days"], "days"),
              Kpi("Current ratio", current["current_ratio"], "ratio")],
        tables=[Table("Last 12 months",
                      [Column("period_label", "Month"), Column("revenue", "Revenue", "money"),
                       Column("gross_profit", "Gross profit", "money"),
                       Column("operating_profit", "Operating profit", "money"),
                       Column("gross_margin_pct", "Gross margin", "pct"),
                       Column("operating_margin_pct", "Operating margin", "pct"),
                       Column("dso_days", "DSO (days)", "days"),
                       Column("current_ratio", "Current ratio", "ratio")], rows)],
        charts=[
            Chart("Gross and operating margin", "line", labels,
                  [{"label": "Gross margin %", "data": series(rows, "gross_margin_pct")},
                   {"label": "Operating margin %", "data": series(rows, "operating_margin_pct")}],
                  unit="pct"),
            Chart("Days sales outstanding", "line", labels,
                  [{"label": "DSO (days)", "data": series(rows, "dso_days")}], unit="days"),
            Chart("Current ratio", "line", labels,
                  [{"label": "Current ratio", "data": series(rows, "current_ratio")}], unit="ratio"),
        ],
        notes=["DSO is closing receivables divided by revenue for the last three months, "
               "multiplied by the days in those months.",
               "Current ratio is current assets divided by current liabilities."],
    )
