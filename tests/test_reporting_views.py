"""Spot checks that the reporting views say what their comments promise."""
from decimal import Decimal


def one(conn, sql, *params):
    return conn.execute(sql, params).fetchone()


def test_pnl_ytd_is_sum_of_months(owner):
    row = one(owner, """
        SELECT sum(amount) FILTER (WHERE period_start <= '2025-06-01') AS months,
               sum(ytd_amount) FILTER (WHERE period_start = '2025-06-01') AS ytd
        FROM reporting.pnl_statement
        WHERE fiscal_year = 2025 AND line_name = 'Net profit'""")
    assert row["months"] == row["ytd"]


def test_prior_year_column_matches_last_year(owner):
    row = one(owner, """
        SELECT (SELECT sum(prior_year_amount) FROM reporting.pnl_statement
                WHERE period_start = '2025-03-01' AND line_name = 'Revenue') AS py,
               (SELECT sum(amount) FROM reporting.pnl_statement
                WHERE period_start = '2024-03-01' AND line_name = 'Revenue') AS actual""")
    assert row["py"] == row["actual"]


def test_marketing_is_the_overspending_cost_centre(owner):
    rows = owner.execute("""SELECT cost_centre_code FROM reporting.budget_vs_actual_cost_centre
                            WHERE period_start = '2025-12-01' AND is_overspent""").fetchall()
    assert [r["cost_centre_code"] for r in rows] == ["CC200"]


def test_aged_buckets_add_up(owner):
    row = one(owner, """SELECT sum(bucket_0_30 + bucket_31_60 + bucket_61_90 + bucket_over_90) AS b,
                               sum(total_open) AS t
                        FROM reporting.aged_receivables WHERE period_start = '2025-12-01'""")
    assert row["b"] == row["t"] > 0


def test_cash_flow_closing_equals_next_opening(owner):
    rows = owner.execute("""SELECT period_start, line_name, amount FROM reporting.cash_flow
                            WHERE line_name IN ('Opening cash', 'Closing cash')
                            ORDER BY period_start""").fetchall()
    closing = {r["period_start"]: r["amount"] for r in rows if r["line_name"] == "Closing cash"}
    opening = {r["period_start"]: r["amount"] for r in rows if r["line_name"] == "Opening cash"}
    months = sorted(closing)
    for previous, current in zip(months, months[1:]):
        assert closing[previous] == opening[current]


def test_ratio_formulas(owner):
    r = one(owner, "SELECT * FROM reporting.key_ratios WHERE period_start = '2025-12-01'")
    assert r["gross_margin_pct"] == round(r["gross_profit"] / r["revenue"] * 100, 1)
    assert r["current_ratio"] == round(r["current_assets"] / r["current_liabilities"], 2)
    assert Decimal(30) < r["dso_days"] < Decimal(120)


def test_late_postings_land_in_their_accounting_month(owner):
    row = one(owner, """SELECT count(*) AS n FROM clean.journal_lines
                        WHERE is_late_posting AND period_start <> date_trunc('month', entry_date)""")
    assert row["n"] == 0
    assert one(owner, "SELECT count(*) AS n FROM clean.journal_lines WHERE is_late_posting")["n"] > 0
