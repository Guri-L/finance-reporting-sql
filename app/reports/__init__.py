"""Registry of report builders. Which reports exist for a user, their titles
and their scope come from the app.reports table; this maps a report key to
the code that renders it."""
from . import aged_receivables, balance_sheet, budget_vs_actual, cash_flow, key_ratios, management_summary, pnl

BUILDERS = {
    "management_summary": management_summary.build,
    "pnl": pnl.build,
    "budget_vs_actual": budget_vs_actual.build,
    "balance_sheet": balance_sheet.build,
    "cash_flow": cash_flow.build,
    "aged_receivables": aged_receivables.build,
    "key_ratios": key_ratios.build,
}
