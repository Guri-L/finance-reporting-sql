"""Load the generated CSVs into the raw tables and seed demo access.

The load is a full refresh in one transaction: either every raw table is
replaced or nothing changes. Usage:  python -m scripts.load_data [csv_dir]
"""
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
TABLES = ["chart_of_accounts", "cost_centres", "fiscal_periods", "customers",
          "journal_entries", "journal_lines", "invoices", "payments", "budget"]


def load(csv_dir: Path, database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE {}").format(sql.SQL(", ").join(
            sql.Identifier("raw", t) for t in TABLES)))
        for table in TABLES:
            path = csv_dir / f"{table}.csv"
            with open(path, encoding="utf-8") as fh:
                header = fh.readline().strip().split(",")
                copy_sql = sql.SQL(
                    "COPY {} ({}) FROM STDIN WITH (FORMAT csv, NULL '')").format(
                    sql.Identifier("raw", table),
                    sql.SQL(", ").join(map(sql.Identifier, header)))
                with cur.copy(copy_sql) as copy:
                    while chunk := fh.read(1 << 16):
                        copy.write(chunk)
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("raw", table)))
            print(f"loaded raw.{table:<20}{cur.fetchone()[0]:>8,} rows")
        cur.execute(sql.SQL("ANALYZE"))
        cur.execute(ROOT.joinpath("seeds", "demo_access.sql").read_text(encoding="utf-8")
                    .replace("BEGIN;", "").replace("COMMIT;", ""))
        print("seeded demo users, groups and grants")


if __name__ == "__main__":
    csv_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "generated"
    load(csv_dir, os.environ["DATABASE_URL"])
