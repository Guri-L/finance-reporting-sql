"""The app's database login can read the reporting layer and nothing else."""
import psycopg
import pytest


def test_reader_can_read_reporting_views(reader):
    assert reader.execute("SELECT count(*) AS n FROM reporting.pnl_statement").fetchone()["n"] > 0


@pytest.mark.parametrize("table", ["raw.journal_lines", "clean.journal_lines",
                                   "controls.orphaned_keys"])
def test_reader_cannot_read_below_reporting_layer(reader, table):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute(f"SELECT 1 FROM {table} LIMIT 1")


@pytest.mark.parametrize("statement", [
    "UPDATE app.users SET is_active = true",
    "INSERT INTO app.user_groups VALUES ('x@halden.example', 'finance')",
    "CREATE TABLE reporting.sneaky (id int)",
])
def test_reader_cannot_write(reader, statement):
    with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction)):
        reader.execute(statement)


def test_reader_sessions_default_to_read_only(reader):
    assert reader.execute("SHOW default_transaction_read_only").fetchone()["default_transaction_read_only"] == "on"
