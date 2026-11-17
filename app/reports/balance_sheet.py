"""Balance sheet: reads reporting.balance_sheet and reporting.balance_sheet_totals."""
from .base import Chart, Column, ReportContext, ReportView, Table, month_label, series

SECTION_ORDER = ["Current assets", "Non-current assets", "Current liabilities",
                 "Non-current liabilities", "Equity"]


def build(ctx: ReportContext) -> ReportView:
    rows = ctx.db.query(
        """SELECT statement_section, line_code, line_name, account_type,
                  CASE WHEN account_type = 'asset' THEN 'assets' ELSE 'funding' END AS side,
                  grouping(line_code) = 1 AS is_rollup,
                  sum(amount) FILTER (WHERE period_start = %(period)s) AS amount,
                  sum(amount) FILTER (WHERE period_start = %(period)s - interval '1 month') AS previous_month,
                  sum(amount) FILTER (WHERE period_start = %(period)s - interval '1 year') AS prior_year
           FROM reporting.balance_sheet
           WHERE period_start IN (%(period)s, %(period)s - interval '1 month',
                                  %(period)s - interval '1 year')
           GROUP BY GROUPING SETS (
               (statement_section, section_order, line_code, line_name, account_type),
               (statement_section, section_order, account_type),
               (account_type),
               (CASE WHEN account_type = 'asset' THEN 'assets' ELSE 'funding' END))
           ORDER BY section_order, line_code""", ctx.params)

    lines = [r for r in rows if not r["is_rollup"]]
    section_totals = {r["statement_section"]: r for r in rows
                      if r["is_rollup"] and r["statement_section"]}
    type_totals = {r["account_type"]: r for r in rows
                   if r["is_rollup"] and not r["statement_section"] and r["account_type"]}
    side_totals = {r["side"]: r for r in rows if r["is_rollup"] and not r["account_type"]}

    def total(label: str, source: dict, css: str = "subtotal") -> dict:
        return {**source, "line_name": label, "line_code": "", "_class": css}

    table_rows: list[dict] = []
    for section in SECTION_ORDER:
        table_rows.append({"line_name": section, "_class": "section"})
        table_rows += [r for r in lines if r["statement_section"] == section]
        table_rows.append(total(f"Total {section.lower()}", section_totals[section]))
        if section == "Non-current assets":
            table_rows.append(total("Total assets", type_totals["asset"], "total"))
        if section == "Non-current liabilities":
            table_rows.append(total("Total liabilities", type_totals["liability"]))
        if section == "Equity":
            table_rows.append(total("Total liabilities and equity", side_totals["funding"], "total"))

    trend = ctx.db.query(
        """SELECT period_start, total_assets, total_liabilities, total_equity
           FROM reporting.balance_sheet_totals
           WHERE period_start <= %(period)s ORDER BY period_start""", ctx.params)

    return ReportView(
        tables=[Table(f"Position at end of {ctx.period_label}",
                      [Column("line_code", "Account"), Column("line_name", "Line"),
                       Column("amount", ctx.period_label, "money"),
                       Column("previous_month", "Previous month end", "money"),
                       Column("prior_year", "Same month last year", "money")], table_rows)],
        charts=[Chart("Assets, liabilities and equity at each month end", "line",
                      [month_label(r["period_start"]) for r in trend],
                      [{"label": "Total assets", "data": series(trend, "total_assets")},
                       {"label": "Total liabilities", "data": series(trend, "total_liabilities")},
                       {"label": "Total equity", "data": series(trend, "total_equity")}])],
        notes=["The ledger has no year-end closing entries, so profit since the opening "
               "balance is shown on its own equity line."],
    )
