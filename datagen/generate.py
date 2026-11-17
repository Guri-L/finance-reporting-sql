"""Synthetic general ledger generator for Halden Supply Co. (fictional).

Writes one CSV per raw table into the output directory. Everything is driven
by a single seeded random generator, so the same seed always produces
byte-identical files.

All money is handled as integer cents and written as two-decimal strings, so
no floating point rounding ever reaches the ledger.

Deliberate imperfections, the kind real ledgers have:
  * late postings   - supplier invoices dated in month M but posted in M+1,
                      before the period was closed
  * reversals       - month-end accruals reversed on the 1st of the next
                      month, and mis-coded invoices reversed and re-posted
  * unpaid invoices - slow payers, part payments, and a handful of disputed
                      invoices that are never paid
  * overspending    - Marketing (CC200) runs well over budget from May 2025

Usage:  python -m datagen.generate --out data/generated --seed 20240101
"""
from __future__ import annotations

import argparse
import calendar
import csv
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

DEFAULT_SEED = 20240101
FIRST_MONTH = date(2024, 1, 1)
N_MONTHS = 24
OPENING_DATE = date(2023, 12, 31)
DATA_END = date(2025, 12, 31)
CLOSE_DAY = 8  # periods are closed on the 8th of the following month

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
# code, name, type, statement section, cash-flow line (balance sheet only)
ACCOUNTS = [
    ("1000", "Cash at bank", "asset", "Current assets", "Cash"),
    ("1100", "Trade receivables", "asset", "Current assets", "Change in trade receivables"),
    ("1200", "Inventory", "asset", "Current assets", "Change in inventory"),
    ("1300", "Prepayments", "asset", "Current assets", "Change in prepayments"),
    ("1500", "Property, plant and equipment - cost", "asset", "Non-current assets", "Purchase of fixed assets"),
    ("1510", "Accumulated depreciation", "asset", "Non-current assets", "Depreciation"),
    ("2000", "Trade payables", "liability", "Current liabilities", "Change in trade payables"),
    ("2100", "Accrued expenses", "liability", "Current liabilities", "Change in accrued expenses"),
    ("2300", "Bank loan", "liability", "Non-current liabilities", "Loan repayments"),
    ("3000", "Share capital", "equity", "Equity", "Share capital issued"),
    ("3100", "Retained earnings brought forward", "equity", "Equity", "Other equity movements"),
    ("4000", "Product sales", "revenue", "Revenue", ""),
    ("4100", "Service revenue", "revenue", "Revenue", ""),
    ("5000", "Cost of goods sold", "expense", "Cost of sales", ""),
    ("5100", "Freight inwards", "expense", "Cost of sales", ""),
    ("6000", "Salaries and wages", "expense", "Operating expenses", ""),
    ("6100", "Rent and premises", "expense", "Operating expenses", ""),
    ("6200", "Marketing and advertising", "expense", "Operating expenses", ""),
    ("6300", "Software and IT services", "expense", "Operating expenses", ""),
    ("6400", "Travel and entertainment", "expense", "Operating expenses", ""),
    ("6500", "Professional fees", "expense", "Operating expenses", ""),
    ("6600", "Depreciation", "expense", "Operating expenses", ""),
    ("6900", "Other operating expenses", "expense", "Operating expenses", ""),
    ("7000", "Interest expense", "expense", "Finance costs", ""),
]

COST_CENTRES = [
    ("CC100", "Sales and Distribution", "Marta Lindqvist"),
    ("CC200", "Marketing", "Jonas Akerman"),
    ("CC300", "Operations and Warehouse", "Priya Raman"),
    ("CC400", "IT", "Tomas Wolde"),
    ("CC500", "Finance and Administration", "Ines Carvalho"),
]

SEASONALITY = [0.92, 0.94, 1.00, 1.00, 1.02, 1.04, 0.96, 0.90, 1.05, 1.08, 1.12, 0.97]
BASE_MONTHLY_REVENUE = 125_000_000  # cents
ACTUAL_GROWTH_2025 = 1.09
BUDGET_GROWTH_2025 = 1.10
SERVICE_SHARE = 0.15
COGS_RATE = 0.62

# Monthly 2024 operating cost plan in cents: (account, cost centre) -> amount.
PAYROLL = {"CC100": 9_500_000, "CC200": 4_500_000, "CC300": 11_000_000,
           "CC400": 5_500_000, "CC500": 6_000_000}
RENT = {"CC100": 420_000, "CC200": 420_000, "CC300": 2_520_000,
        "CC400": 420_000, "CC500": 420_000}
SUPPLIER_OPEX = {  # paid through accounts payable
    ("6200", "CC200"): 5_500_000,
    ("6300", "CC400"): 2_200_000, ("6300", "CC100"): 400_000, ("6300", "CC500"): 300_000,
    ("6400", "CC100"): 1_200_000, ("6400", "CC200"): 300_000, ("6400", "CC300"): 200_000,
    ("6500", "CC500"): 1_200_000,
    ("6900", "CC100"): 200_000, ("6900", "CC200"): 200_000, ("6900", "CC300"): 200_000,
    ("6900", "CC400"): 200_000, ("6900", "CC500"): 200_000,
}
VENDORS = {
    "6200": ["Brightline Media", "Fjord Creative", "AdNordic", "PrintWorks"],
    "6300": ["Cloudspan", "Ledgerly SaaS", "NetGuard", "Helpdesk One"],
    "6400": ["Skyway Travel", "Harbour Hotels", "CityCab"],
    "6500": ["Pell & Morrow LLP", "Castor Audit", "Tidewater Legal"],
    "6900": ["Office Depot Nord", "CleanCo", "Parcel Express"],
}
INSURANCE_ANNUAL = {2024: 6_000_000, 2025: 6_300_000}
CAPEX = {date(2024, 6, 15): 18_000_000, date(2025, 3, 10): 24_000_000}
DEPRECIATION_STEPS = [(date(2024, 1, 1), 1_400_000), (date(2024, 7, 1), 1_700_000),
                      (date(2025, 4, 1), 2_100_000)]
LOAN_OPENING = 90_000_000
LOAN_RATE = 0.055
LOAN_QUARTERLY_REPAYMENT = 4_500_000

OPENING_BALANCES = [  # account, debit, credit (cents)
    ("1000", 240_000_000, 0), ("1200", 90_000_000, 0), ("1500", 150_000_000, 0),
    ("1510", 0, 40_000_000), ("2300", 0, LOAN_OPENING),
    ("3000", 0, 200_000_000), ("3100", 0, 150_000_000),
]

NAME_A = ["Nordic", "Harbour", "Summit", "Atlas", "Vega", "Cedar", "Granite", "Polar",
          "Meridian", "Falcon", "Orchard", "Beacon", "Sterling", "Juniper", "Corvid"]
NAME_B = ["Hardware", "Building Supplies", "Tools", "Industrial", "Trading",
          "Fittings", "Wholesale", "Components", "Depot"]
NAME_C = ["AB", "Ltd", "GmbH", "BV", "AS", "Oy"]
SEGMENTS = ["Retail chain", "Contractor", "Industrial", "Online reseller"]
COUNTRIES = ["SE", "NO", "DK", "FI", "DE", "NL"]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def month_start(i: int) -> date:
    y, m = divmod(FIRST_MONTH.month - 1 + i, 12)
    return date(FIRST_MONTH.year + y, m + 1, 1)


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def split_amount(rng: random.Random, total: int, parts: int) -> list[int]:
    """Split total cents into `parts` random positive pieces that sum exactly."""
    weights = [rng.uniform(0.6, 1.4) for _ in range(parts)]
    scale = total / sum(weights)
    pieces = [int(w * scale) for w in weights]
    pieces[-1] += total - sum(pieces)
    return pieces


@dataclass
class Line:
    account: str
    debit: int = 0
    credit: int = 0
    cost_centre: str = ""
    customer_id: str = ""


@dataclass
class Entry:
    entry_date: date
    posted_at: datetime
    description: str
    source: str
    lines: list[Line]
    reverses: Entry | None = None
    entry_id: int = 0
    key: int = field(default=0)  # creation order, tie-breaker for sorting


class Ledger:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.entries: list[Entry] = []

    def post(self, entry_date: date, description: str, source: str, lines: list[Line],
             posted_at: datetime | None = None, reverses: Entry | None = None) -> Entry:
        lines = [ln for ln in lines if ln.debit or ln.credit]
        assert sum(ln.debit for ln in lines) == sum(ln.credit for ln in lines), description
        assert all(ln.debit >= 0 and ln.credit >= 0 for ln in lines), description
        if posted_at is None:
            posted_at = datetime.combine(
                entry_date, time(self.rng.randint(8, 17), self.rng.randint(0, 59)))
        entry = Entry(entry_date, posted_at, description, source, lines, reverses,
                      key=len(self.entries))
        self.entries.append(entry)
        return entry

    def reverse(self, original: Entry, entry_date: date, description: str) -> Entry:
        lines = [Line(ln.account, ln.credit, ln.debit, ln.cost_centre, ln.customer_id)
                 for ln in original.lines]
        return self.post(entry_date, description, original.source, lines, reverses=original)

    def finalise(self) -> None:
        self.entries.sort(key=lambda e: (e.posted_at, e.key))
        for i, entry in enumerate(self.entries, start=1):
            entry.entry_id = i


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------
def generate(seed: int = DEFAULT_SEED) -> dict[str, tuple[list[str], list[list]]]:
    rng = random.Random(seed)
    gl = Ledger(rng)

    # ---- customers --------------------------------------------------------
    customers = []
    used = set()
    while len(customers) < 45:
        name = f"{rng.choice(NAME_A)} {rng.choice(NAME_B)} {rng.choice(NAME_C)}"
        if name in used:
            continue
        used.add(name)
        roll = rng.random()
        profile = "good" if roll < 0.70 else ("slow" if roll < 0.92 else "poor")
        customers.append({
            "id": f"C{len(customers) + 1:04d}", "name": name,
            "segment": rng.choice(SEGMENTS), "country": rng.choice(COUNTRIES),
            "terms": rng.choice([30, 30, 30, 45, 60]),
            "weight": rng.paretovariate(1.6), "profile": profile,
        })
    cust_weights = [c["weight"] for c in customers]

    # ---- opening balances -------------------------------------------------
    gl.post(OPENING_DATE, "Opening balances brought forward", "GL",
            [Line(a, d, c) for a, d, c in OPENING_BALANCES],
            posted_at=datetime.combine(OPENING_DATE, time(12, 0)))

    invoices: list[dict] = []
    payments: list[dict] = []
    budget: list[list] = []
    ap_by_month: dict[int, int] = {}
    loan_balance = LOAN_OPENING
    miscoded_months = set(rng.sample(range(N_MONTHS), 6))
    disputed_invoice_slots = set(rng.sample(range(1200, 2900), 8))
    accrual: Entry | None = None  # last month's accrual, reversed on the 1st

    def cost_plan(year: int) -> dict[tuple[str, str], int]:
        """Monthly budget for every (account, cost centre) operating cost."""
        uplift, pay_uplift = (1.0, 1.0) if year == 2024 else (1.03, 1.04)
        plan = {("6000", cc): round(v * pay_uplift) for cc, v in PAYROLL.items()}
        plan.update({("6100", cc): round(v * uplift) for cc, v in RENT.items()})
        plan.update({k: round(v * uplift) for k, v in SUPPLIER_OPEX.items()})
        plan[("6900", "CC500")] += INSURANCE_ANNUAL[year] // 12
        return plan

    for i in range(N_MONTHS):
        first = month_start(i)
        last = month_end(first)
        year, days = first.year, last.day
        plan = cost_plan(year)
        ap_by_month[i] = 0

        # The helpers below are only called inside this iteration, so binding
        # the loop variables late is intended.
        def day(lo: int = 1, hi: int = days) -> date:
            return first.replace(day=rng.randint(lo, min(hi, days)))

        def ap_invoice(account: str, cc: str, amount: int, vendor: str,
                       allow_late: bool = True) -> Entry:
            entry_date, posted_at = day(), None
            if allow_late and rng.random() < 0.05:
                # Late posting: dated in the last days of the month, keyed in
                # early the following month before the period was closed.
                entry_date = first.replace(day=rng.randint(days - 2, days))
                posted_at = datetime.combine(
                    last + timedelta(days=rng.randint(2, 5)),
                    time(rng.randint(8, 17), rng.randint(0, 59)))
            ap_by_month[i] += amount
            return gl.post(entry_date, f"Supplier invoice - {vendor}", "AP",
                           [Line(account, debit=amount, cost_centre=cc),
                            Line("2000", credit=amount)], posted_at=posted_at)

        # ---- reverse last month's accrual on the 1st ----------------------
        if accrual is not None:
            gl.reverse(accrual, first, f"Reversal of accrual - {accrual.description[10:]}")

        # ---- sales invoices ----------------------------------------------
        growth = ACTUAL_GROWTH_2025 if year == 2025 else 1.0
        target = round(BASE_MONTHLY_REVENUE * SEASONALITY[first.month - 1] * growth
                       * rng.uniform(0.97, 1.03))
        n_inv = round(140 * SEASONALITY[first.month - 1] * growth * rng.uniform(0.95, 1.05))
        raw = [rng.lognormvariate(0, 0.7) for _ in range(n_inv)]
        scale = target / sum(raw)
        for r in raw:
            amount = max(15_000, round(r * scale))
            cust = rng.choices(customers, weights=cust_weights)[0]
            inv_date = day()
            is_service = rng.random() < SERVICE_SHARE
            lines = [Line("1100", debit=amount, customer_id=cust["id"]),
                     Line("4100" if is_service else "4000", credit=amount, cost_centre="CC100")]
            if not is_service:
                cogs = round(amount * rng.uniform(COGS_RATE - 0.02, COGS_RATE + 0.02))
                lines += [Line("5000", debit=cogs, cost_centre="CC100"),
                          Line("1200", credit=cogs)]
            number = f"INV-{len(invoices) + 1:06d}"
            entry = gl.post(inv_date, f"Sales invoice {number} - {cust['name']}", "AR", lines)
            inv = {"number": number, "customer": cust, "date": inv_date,
                   "due": inv_date + timedelta(days=cust["terms"]), "amount": amount,
                   "account": "4100" if is_service else "4000", "entry": entry}
            invoices.append(inv)

            # ---- how (and whether) this invoice gets paid ----------------
            if len(invoices) in disputed_invoice_slots:
                continue  # disputed: never paid
            mean, sd = {"good": (-2, 6), "slow": (22, 14), "poor": (50, 25)}[cust["profile"]]
            pay_date = inv_date + timedelta(
                days=max(3, cust["terms"] + round(rng.gauss(mean, sd))))
            if rng.random() < 0.03:  # part payment, remainder a month later or never
                first_part = round(amount * rng.uniform(0.4, 0.7))
                schedule = [(pay_date, first_part)]
                if rng.random() < 0.6:
                    schedule.append((pay_date + timedelta(days=rng.randint(20, 45)),
                                     amount - first_part))
            else:
                schedule = [(pay_date, amount)]
            for when, paid in schedule:
                if when <= DATA_END:
                    payments.append({"invoice": inv, "date": when, "amount": paid})

        # ---- inventory purchases and freight ------------------------------
        month_cogs = sum(ln.debit for e in gl.entries if e.entry_date >= first
                         and e.source == "AR" for ln in e.lines if ln.account == "5000")
        purchases = round(month_cogs * rng.uniform(0.97, 1.05))
        for amount in split_amount(rng, purchases, rng.randint(6, 10)):
            ap_by_month[i] += amount
            gl.post(day(), "Goods received - inventory purchase", "AP",
                    [Line("1200", debit=amount), Line("2000", credit=amount)])
        ap_invoice("5100", "CC100", round(purchases * rng.uniform(0.016, 0.020)),
                   "Baltic Freight Lines", allow_late=False)

        # ---- supplier-paid operating costs --------------------------------
        miscoded_done = False
        for account, cc in SUPPLIER_OPEX:
            planned = plan[(account, cc)] - (INSURANCE_ANNUAL[year] // 12
                                             if (account, cc) == ("6900", "CC500") else 0)
            factor = rng.uniform(0.95, 1.05)
            if cc == "CC400":
                factor = rng.uniform(0.90, 0.98)       # IT runs slightly under
            if cc == "CC200" and first >= date(2025, 5, 1):
                factor = rng.uniform(1.25, 1.45) if account == "6200" else rng.uniform(1.3, 1.6)
            total = round(planned * factor)
            for amount in split_amount(rng, total, rng.randint(1, 4)):
                vendor = rng.choice(VENDORS[account])
                if i in miscoded_months and not miscoded_done and account == "6300" and cc == "CC400":
                    # Mis-coded to the wrong cost centre, then reversed and re-posted.
                    miscoded_done = True
                    d0 = day(2, 18)
                    wrong = gl.post(d0, f"Supplier invoice - {vendor}", "AP",
                                    [Line(account, debit=amount, cost_centre="CC300"),
                                     Line("2000", credit=amount)])
                    fix_date = d0 + timedelta(days=rng.randint(2, 6))
                    gl.reverse(wrong, fix_date, f"Reversal - {vendor} coded to wrong cost centre")
                    gl.post(fix_date, f"Supplier invoice - {vendor} (re-posted)", "AP",
                            [Line(account, debit=amount, cost_centre=cc),
                             Line("2000", credit=amount)])
                    ap_by_month[i] += amount
                else:
                    ap_invoice(account, cc, amount, vendor)

        # ---- payroll, rent, insurance, depreciation -----------------------
        pay = {cc: round(plan[("6000", cc)] * rng.uniform(0.99, 1.01)) for cc in PAYROLL}
        gl.post(first.replace(day=25), f"Payroll {first:%B %Y}", "PAY",
                [Line("6000", debit=v, cost_centre=cc) for cc, v in pay.items()]
                + [Line("1000", credit=sum(pay.values()))])
        rent = {cc: plan[("6100", cc)] for cc in RENT}
        gl.post(first, f"Rent {first:%B %Y}", "CASH",
                [Line("6100", debit=v, cost_centre=cc) for cc, v in rent.items()]
                + [Line("1000", credit=sum(rent.values()))])
        if first.month == 1:
            gl.post(first.replace(day=10), f"Annual insurance premium {year}", "CASH",
                    [Line("1300", debit=INSURANCE_ANNUAL[year]),
                     Line("1000", credit=INSURANCE_ANNUAL[year])])
        gl.post(last, f"Insurance expense {first:%B %Y}", "GL",
                [Line("6900", debit=INSURANCE_ANNUAL[year] // 12, cost_centre="CC500"),
                 Line("1300", credit=INSURANCE_ANNUAL[year] // 12)])
        dep = [amt for start, amt in DEPRECIATION_STEPS if start <= first][-1]
        dep_ops = round(dep * 0.7)
        gl.post(last, f"Depreciation {first:%B %Y}", "GL",
                [Line("6600", debit=dep_ops, cost_centre="CC300"),
                 Line("6600", debit=dep - dep_ops, cost_centre="CC400"),
                 Line("1510", credit=dep)])

        # ---- capital expenditure ------------------------------------------
        for when, amount in CAPEX.items():
            if first <= when <= last:
                gl.post(when, "Warehouse racking and equipment", "CASH",
                        [Line("1500", debit=amount), Line("1000", credit=amount)])

        # ---- loan interest and repayment ----------------------------------
        interest = round(loan_balance * LOAN_RATE / 12)
        loan_lines = [Line("7000", debit=interest, cost_centre="CC500")]
        repay = LOAN_QUARTERLY_REPAYMENT if first.month % 3 == 0 else 0
        if repay:
            loan_lines.append(Line("2300", debit=repay))
            loan_balance -= repay
        gl.post(first.replace(day=28), f"Bank loan interest {first:%B %Y}", "CASH",
                loan_lines + [Line("1000", credit=interest + repay)])

        # ---- pay last month's suppliers -----------------------------------
        if i > 0 and ap_by_month[i - 1]:
            gl.post(first.replace(day=20), f"Supplier payment run {first:%B %Y}", "AP",
                    [Line("2000", debit=ap_by_month[i - 1]),
                     Line("1000", credit=ap_by_month[i - 1])])

        # ---- month-end accrual (reversed on the 1st of next month) --------
        accrued = rng.randint(500_000, 900_000)
        accrual = gl.post(last, f"Accrual - audit and legal fees {first:%B %Y}", "GL",
                          [Line("6500", debit=accrued, cost_centre="CC500"),
                           Line("2100", credit=accrued)])

        # ---- budget -------------------------------------------------------
        bgrowth = BUDGET_GROWTH_2025 if year == 2025 else 1.0
        rev = round(BASE_MONTHLY_REVENUE * SEASONALITY[first.month - 1] * bgrowth)
        product = round(rev * (1 - SERVICE_SHARE))
        budget.append([first, "CC100", "4000", money(product)])
        budget.append([first, "CC100", "4100", money(rev - product)])
        budget.append([first, "CC100", "5000", money(round(product * COGS_RATE))])
        budget.append([first, "CC100", "5100", money(round(product * COGS_RATE * 0.018))])
        for (account, cc), amount in sorted(plan.items()):
            budget.append([first, cc, account, money(amount)])
        dep_plan = [amt for start, amt in DEPRECIATION_STEPS if start <= first][-1]
        budget.append([first, "CC300", "6600", money(round(dep_plan * 0.7))])
        budget.append([first, "CC400", "6600", money(dep_plan - round(dep_plan * 0.7))])
        budget.append([first, "CC500", "7000", money(round(LOAN_OPENING * LOAN_RATE / 12))])

    # ---- customer receipts ------------------------------------------------
    for p in payments:
        inv = p["invoice"]
        p["entry"] = gl.post(p["date"], f"Customer receipt {inv['number']}", "AR",
                             [Line("1000", debit=p["amount"]),
                              Line("1100", credit=p["amount"], customer_id=inv["customer"]["id"])])
    payments.sort(key=lambda p: (p["date"], p["invoice"]["number"]))

    gl.finalise()

    # ---- assemble tables --------------------------------------------------
    periods = [[date(2023, 12, 1), OPENING_DATE, 2023, "closed",
                datetime(2024, 1, 2, 9, 0), "true"]]
    for i in range(N_MONTHS):
        first = month_start(i)
        last = month_end(first)
        is_open = i == N_MONTHS - 1
        closed_at = "" if is_open else datetime.combine(
            last + timedelta(days=CLOSE_DAY), time(18, 0))
        periods.append([first, last, first.year, "open" if is_open else "closed",
                        closed_at, "false"])

    entry_rows, line_rows = [], []
    line_id = 0
    for e in gl.entries:
        entry_rows.append([e.entry_id, f"JE-{e.entry_id:06d}", e.entry_date, e.posted_at,
                           e.description, e.source,
                           e.reverses.entry_id if e.reverses else ""])
        for n, ln in enumerate(e.lines, start=1):
            line_id += 1
            line_rows.append([line_id, e.entry_id, n, ln.account, ln.cost_centre,
                              ln.customer_id, money(ln.debit), money(ln.credit)])

    return {
        "chart_of_accounts": (
            ["account_code", "account_name", "account_type", "statement_section", "cash_flow_line"],
            [list(a) for a in ACCOUNTS]),
        "cost_centres": (["cost_centre_code", "cost_centre_name", "manager_name"],
                         [list(c) for c in COST_CENTRES]),
        "fiscal_periods": (["period_start", "period_end", "fiscal_year", "status",
                            "closed_at", "is_opening_period"], periods),
        "customers": (["customer_id", "customer_name", "segment", "country", "payment_terms_days"],
                      [[c["id"], c["name"], c["segment"], c["country"], c["terms"]]
                       for c in customers]),
        "journal_entries": (["entry_id", "entry_number", "entry_date", "posted_at",
                             "description", "source", "reverses_entry_id"], entry_rows),
        "journal_lines": (["line_id", "entry_id", "line_number", "account_code",
                           "cost_centre_code", "customer_id", "debit", "credit"], line_rows),
        "invoices": (["invoice_id", "invoice_number", "customer_id", "invoice_date",
                      "due_date", "amount", "revenue_account_code", "entry_id"],
                     [[n, inv["number"], inv["customer"]["id"], inv["date"], inv["due"],
                       money(inv["amount"]), inv["account"], inv["entry"].entry_id]
                      for n, inv in enumerate(invoices, start=1)]),
        "payments": (["payment_id", "invoice_id", "payment_date", "amount", "entry_id"],
                     [[n, int(p["invoice"]["number"][4:]), p["date"], money(p["amount"]),
                       p["entry"].entry_id] for n, p in enumerate(payments, start=1)]),
        "budget": (["period_start", "cost_centre_code", "account_code", "amount"], budget),
    }


def write_csvs(tables: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (header, rows) in tables.items():
        with open(out_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default="data/generated", type=Path)
    parser.add_argument("--seed", default=DEFAULT_SEED, type=int)
    args = parser.parse_args()
    tables = generate(args.seed)
    write_csvs(tables, args.out)
    for name, (_, rows) in tables.items():
        print(f"{name:<20}{len(rows):>8,} rows")


if __name__ == "__main__":
    main()
