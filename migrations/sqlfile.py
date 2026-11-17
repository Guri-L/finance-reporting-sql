"""Helper so each migration is a thin wrapper around one readable SQL file."""
from pathlib import Path

from alembic import op

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def run_sql_file(name: str) -> None:
    # Executed through the driver cursor without parameters, so the SQL file is
    # sent exactly as written (a '%' in a comment needs no escaping). It runs on
    # the same connection, inside Alembic's migration transaction.
    cursor = op.get_bind().connection.driver_connection.cursor()
    cursor.execute(SQL_DIR.joinpath(name).read_text(encoding="utf-8"))
