"""Aged receivables: reads reporting.aged_receivables and
reporting.aged_receivables_invoices."""
from .base import Chart, Column, Kpi, ReportContext, ReportView, Table, month_label, series

BUCKETS = [Column("bucket_0_30", "0-30 days", "money"), Column("bucket_31_60", "31-60 days", "money"),
           Column("bucket_61_90", "61-90 days", "money"), Column("bucket_over_90", "90+ days", "money"),
           Column("total_open", "Total open", "money")]
BUCKET_SUMS = """sum(bucket_0_30) AS bucket_0_30, sum(bucket_31_60) AS bucket_31_60,
                 sum(bucket_61_90) AS bucket_61_90, sum(bucket_over_90) AS bucket_over_90,
                 sum(total_open) AS total_open"""


def build(ctx: ReportContext) -> ReportView:
    customers = ctx.db.query(
        f"""SELECT customer_id, customer_name, {BUCKET_SUMS},
                   sum(open_invoices) AS open_invoices,
                   reporting.pct_of(sum(bucket_over_90), sum(total_open)) AS over_90_pct,
                   grouping(customer_id) = 1 AS is_total
            FROM reporting.aged_receivables
            WHERE period_start = %(period)s
            GROUP BY GROUPING SETS ((customer_id, customer_name), ())
            ORDER BY grouping(customer_id), sum(total_open) DESC""", ctx.params)
    total = next((r for r in customers if r["is_total"]), None)
    if total:
        total.update(customer_name="Total", customer_id="", _class="total")

    old_invoices = ctx.db.query(
        """SELECT invoice_number, customer_name, invoice_date, due_date, age_days,
                  age_bucket, invoice_amount, open_amount
           FROM reporting.aged_receivables_invoices
           WHERE period_start = %(period)s AND age_days > 60
           ORDER BY age_days DESC, open_amount DESC""", ctx.params)

    trend = ctx.db.query(
        f"""SELECT period_start, {BUCKET_SUMS}
            FROM reporting.aged_receivables
            WHERE period_start <= %(period)s AND period_start > %(period)s - interval '12 months'
            GROUP BY period_start ORDER BY period_start""", ctx.params)

    kpis = []
    if total:
        kpis = [Kpi("Total open receivables", total["total_open"]),
                Kpi("Older than 90 days", total["bucket_over_90"]),
                Kpi("Share older than 90 days", total["over_90_pct"], "pct"),
                Kpi("Open invoices", total["open_invoices"], "int")]
    return ReportView(
        kpis=kpis,
        tables=[
            Table(f"By customer at end of {ctx.period_label}",
                  [Column("customer_id", "Customer"), Column("customer_name", "Name")] + BUCKETS
                  + [Column("open_invoices", "Invoices", "int")], customers),
            Table("Open invoices older than 60 days",
                  [Column("invoice_number", "Invoice"), Column("customer_name", "Customer"),
                   Column("invoice_date", "Invoice date", "date"), Column("due_date", "Due", "date"),
                   Column("age_days", "Age (days)", "int"), Column("age_bucket", "Bucket"),
                   Column("invoice_amount", "Invoice amount", "money"),
                   Column("open_amount", "Open amount", "money")], old_invoices),
        ],
        charts=[Chart("Open receivables by age at each month end, last 12 months", "bar",
                      [month_label(r["period_start"]) for r in trend],
                      [{"label": c.label, "data": series(trend, c.key)} for c in BUCKETS[:4]],
                      stacked=True)],
        notes=["Age is counted in days from the invoice date to the month end."],
    )
