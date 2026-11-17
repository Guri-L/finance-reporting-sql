"""Monthly management summary: headline figures, a written commentary on the
largest variances, and the variance table behind it.

Every number quoted in the commentary is read from a reporting view (or
computed in SQL with the reporting.* functions). This module only chooses
which rows to mention and puts them into sentences.
"""
from ..formatting import money_compact
from .base import Column, Kpi, ReportContext, ReportView, Table


def _direction(value, up: str, down: str) -> str:
    return up if value >= 0 else down


def build(ctx: ReportContext) -> ReportView:
    db, p = ctx.db, ctx.params

    def _m(value) -> str:
        return money_compact(value, ctx.currency)

    ratios = db.one("SELECT * FROM reporting.key_ratios WHERE period_start = %(period)s", p)
    revenue = db.one(
        """SELECT sum(amount) AS amount, sum(prior_year_amount) AS prior_year_amount,
                  reporting.variance_pct(sum(amount), sum(prior_year_amount)) AS change_pct
           FROM reporting.pnl_statement
           WHERE period_start = %(period)s AND line_name = 'Revenue'""", p)
    revenue_budget = db.one(
        """SELECT sum(actual_amount) AS actual, sum(budget_amount) AS budget,
                  sum(variance_amount) AS variance,
                  reporting.variance_pct(sum(actual_amount), sum(budget_amount)) AS variance_pct
           FROM reporting.budget_vs_actual
           WHERE period_start = %(period)s AND account_type = 'revenue'""", p)
    opex = db.one(
        """SELECT sum(actual_amount) AS actual, sum(budget_amount) AS budget,
                  sum(variance_amount) AS variance,
                  reporting.variance_pct(sum(actual_amount), sum(budget_amount)) AS variance_pct
           FROM reporting.budget_vs_actual_cost_centre WHERE period_start = %(period)s""", p)
    variances = db.query(
        """SELECT b.cost_centre_code, cc.cost_centre_name, b.account_code, b.account_name,
                  b.statement_section, b.actual_amount, b.budget_amount, b.variance_amount,
                  b.variance_pct, b.is_favourable,
                  CASE WHEN b.is_favourable THEN 'Favourable' ELSE 'Adverse' END AS status
           FROM reporting.budget_vs_actual b
           JOIN reporting.cost_centres cc USING (cost_centre_code)
           WHERE b.period_start = %(period)s AND b.variance_amount <> 0
           ORDER BY abs(b.variance_amount) DESC LIMIT 8""", p)
    overspent = db.query(
        """SELECT cost_centre_name, ytd_actual_amount, ytd_budget_amount,
                  ytd_variance_amount, ytd_variance_pct
           FROM reporting.budget_vs_actual_cost_centre
           WHERE period_start = %(period)s AND is_overspent
           ORDER BY ytd_variance_amount DESC""", p)
    cash = {r["line_name"]: r["amount"] for r in db.query(
        """SELECT line_name, amount FROM reporting.cash_flow
           WHERE period_start = %(period)s AND is_subtotal""", p)}
    receivables = db.one(
        """SELECT sum(total_open) AS total_open, sum(bucket_over_90) AS over_90,
                  reporting.pct_of(sum(bucket_over_90), sum(total_open)) AS over_90_pct
           FROM reporting.aged_receivables WHERE period_start = %(period)s""", p)

    commentary = []

    # 1. Revenue against budget and last year.
    sentence = (f"Revenue for {ctx.period_label} was {_m(revenue['amount'])}, "
                f"{abs(revenue_budget['variance_pct'])}% "
                f"{_direction(revenue_budget['variance'], 'above', 'below')} budget "
                f"({_m(revenue_budget['variance'])})")
    if revenue["change_pct"] is not None:
        sentence += (f" and {abs(revenue['change_pct'])}% "
                     f"{_direction(revenue['change_pct'], 'up', 'down')} on the same month last year")
    commentary.append(sentence + ".")

    # 2. Profitability.
    commentary.append(
        f"Gross margin was {ratios['gross_margin_pct']}% and operating "
        f"{_direction(ratios['operating_profit'], 'profit', 'loss')} was "
        f"{_m(ratios['operating_profit'])}, an operating margin of "
        f"{ratios['operating_margin_pct']}%.")

    # 3. Operating costs against budget, naming the largest cost variances.
    cost_lines = [v for v in variances if v["statement_section"] == "Operating expenses"]
    sentence = (f"Operating costs were {_m(opex['actual'])}, {abs(opex['variance_pct'])}% "
                f"{_direction(opex['variance'], 'over', 'under')} budget.")
    adverse = [v for v in cost_lines if not v["is_favourable"]][:2]
    if adverse:
        parts = [f"{v['account_name']} in {v['cost_centre_name']} "
                 f"({_m(v['variance_amount'])} over, {v['variance_pct']}%)" for v in adverse]
        sentence += " The largest overspend" + ("s were " if len(parts) > 1 else " was ") \
            + " and ".join(parts) + "."
    favourable = [v for v in cost_lines if v["is_favourable"]][:1]
    if favourable:
        v = favourable[0]
        sentence += (f" The largest saving was {v['account_name']} in {v['cost_centre_name']} "
                     f"({_m(v['variance_amount'])} under budget).")
    commentary.append(sentence)

    # 4. Cost centres over budget for the year to date.
    if overspent:
        parts = [f"{o['cost_centre_name']} ({o['ytd_variance_pct']}%, {_m(o['ytd_variance_amount'])})"
                 for o in overspent]
        commentary.append("Over budget for the year to date by more than 5%: "
                          + "; ".join(parts) + ".")
    else:
        commentary.append("No cost centre is more than 5% over budget for the year to date.")

    # 5. Cash and receivables.
    commentary.append(
        f"Cash {_direction(cash['Net change in cash'], 'increased', 'decreased')} by "
        f"{_m(cash['Net change in cash'])} to {_m(cash['Closing cash'])}, with "
        f"{_m(cash['Net cash from operating activities'])} "
        f"{_direction(cash['Net cash from operating activities'], 'generated by', 'used in')} "
        f"operations. Days sales outstanding stand at {ratios['dso_days']} and "
        f"{receivables['over_90_pct']}% of receivables ({_m(receivables['over_90'])}) "
        f"are older than 90 days.")

    return ReportView(
        kpis=[
            Kpi("Revenue", revenue["amount"], "money",
                f"{revenue_budget['variance_pct']}% vs budget"),
            Kpi("Gross margin", ratios["gross_margin_pct"], "pct"),
            Kpi("Operating profit", ratios["operating_profit"], "money",
                f"{ratios['operating_margin_pct']}% margin"),
            Kpi("Net profit", ratios["net_profit"], "money"),
            Kpi("Closing cash", cash["Closing cash"], "money"),
            Kpi("Days sales outstanding", ratios["dso_days"], "days"),
        ],
        commentary=commentary,
        tables=[Table("Largest variances against budget this month",
                      [Column("cost_centre_name", "Cost centre"), Column("account_name", "Account"),
                       Column("actual_amount", "Actual", "money"),
                       Column("budget_amount", "Budget", "money"),
                       Column("variance_amount", "Variance", "money"),
                       Column("variance_pct", "Var %", "pct"), Column("status", "", "status")],
                      variances,
                      note="Revenue and cost lines, ranked by size of variance. Revenue above "
                           "budget and costs below budget are favourable.")],
    )
