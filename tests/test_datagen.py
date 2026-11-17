from collections import Counter, defaultdict
from decimal import Decimal

from datagen.generate import generate


def test_same_seed_same_ledger():
    assert generate(7) == generate(7)


def test_different_seed_different_ledger():
    assert generate(7)["journal_lines"] != generate(8)["journal_lines"]


def test_every_generated_entry_balances():
    lines = generate()["journal_lines"][1]
    totals = defaultdict(Decimal)
    for _, entry_id, _, _, _, _, debit, credit in lines:
        totals[entry_id] += Decimal(debit) - Decimal(credit)
    assert set(totals.values()) == {Decimal("0")}


def test_ledger_has_the_imperfections_real_ledgers_have():
    tables = generate()
    entries = tables["journal_entries"][1]
    late = [e for e in entries if e[3].date() > e[2].replace(day=28) and e[3].month != e[2].month]
    reversals = [e for e in entries if e[6] != ""]
    assert len(late) >= 20, "late postings"
    assert len(reversals) >= 25, "accrual reversals and corrections"

    paid = Counter()
    for _, invoice_id, _, amount, _ in tables["payments"][1]:
        paid[invoice_id] += Decimal(amount)
    unpaid = [i for i in tables["invoices"][1] if paid[i[0]] < Decimal(i[5])
              and i[3].year == 2024]
    assert len(unpaid) >= 5, "some old invoices are never fully paid"
