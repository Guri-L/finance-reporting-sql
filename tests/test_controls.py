"""The controls pass on the loaded data, and fail loudly when data is broken."""


from scripts.run_checks import run_checks
from tests.conftest import OWNER_URL


def test_all_controls_pass_on_loaded_data():
    results = run_checks(OWNER_URL)
    assert len(results) >= 10
    assert [r["name"] for r in results if r["violations"]] == []


def violations(conn, control):
    return conn.execute(f"SELECT count(*) AS n FROM controls.{control}").fetchone()["n"]


def new_entry(conn, entry_date="2025-06-15", posted_at="2025-06-15 10:00"):
    entry_id = conn.execute("SELECT max(entry_id) + 1 AS id FROM raw.journal_entries").fetchone()["id"]
    conn.execute("""INSERT INTO raw.journal_entries VALUES
                    (%s, 'TEST', %s, %s, 'test entry', 'GL', NULL)""",
                 (entry_id, entry_date, posted_at))
    return entry_id


def add_line(conn, entry_id, account, debit, credit, cc=None):
    line_id = conn.execute("SELECT max(line_id) + 1 AS id FROM raw.journal_lines").fetchone()["id"]
    conn.execute("""INSERT INTO raw.journal_lines VALUES (%s, %s, 1, %s, %s, NULL, %s, %s)""",
                 (line_id, entry_id, account, cc, debit, credit))


def test_unbalanced_entry_is_caught(owner):
    entry = new_entry(owner)
    add_line(owner, entry, "6900", 100, 0, "CC500")
    add_line(owner, entry, "1000", 0, 99.99)
    assert violations(owner, "unbalanced_journal_entries") == 1
    assert violations(owner, "balance_sheet_out_of_balance") > 0


def test_posting_into_closed_period_is_caught(owner):
    entry = new_entry(owner, entry_date="2025-03-31", posted_at="2025-05-02 09:00")
    add_line(owner, entry, "6900", 100, 0, "CC500")
    add_line(owner, entry, "1000", 0, 100)
    assert violations(owner, "postings_in_closed_periods") == 1


def test_orphaned_keys_are_caught(owner):
    entry = new_entry(owner)
    add_line(owner, entry, "9999", 100, 0, "CC999")
    add_line(owner, entry, "1000", 0, 100)
    assert violations(owner, "orphaned_keys") == 2   # unknown account and cost centre


def test_pnl_line_without_cost_centre_is_caught(owner):
    entry = new_entry(owner)
    add_line(owner, entry, "6900", 100, 0, None)
    add_line(owner, entry, "1000", 0, 100)
    assert violations(owner, "invalid_journal_lines") == 1


def test_runner_exits_non_zero_on_failure(owner, monkeypatch):
    """The runner reads committed data, so break it in a committed way and undo it."""
    import psycopg

    from scripts import run_checks as runner
    with psycopg.connect(OWNER_URL, autocommit=True) as conn:
        conn.execute("UPDATE raw.journal_lines SET credit = credit + 0.01 WHERE line_id = 2")
        try:
            assert runner.main() == 1
        finally:
            conn.execute("UPDATE raw.journal_lines SET credit = credit - 0.01 WHERE line_id = 2")
    assert runner.main() == 0
