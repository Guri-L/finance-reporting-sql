"""Run every control in the `controls` schema. Exit code 1 if any fails.

Each control is a view that returns the rows violating it, so a control
passes when its view is empty. Usage:  python -m scripts.run_checks
"""
import os
import sys

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

MAX_ROWS_SHOWN = 5


def run_checks(database_url: str) -> list[dict]:
    """Return one result dict per control: name, description, violations, sample."""
    results = []
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        controls = conn.execute("""
            SELECT c.relname AS name, obj_description(c.oid) AS description
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'controls' AND c.relkind = 'v'
            ORDER BY c.relname""").fetchall()
        if not controls:
            raise RuntimeError("No controls found: have the migrations been run?")
        for control in controls:
            rows = conn.execute(sql.SQL("SELECT * FROM {}").format(
                sql.Identifier("controls", control["name"]))).fetchall()
            results.append({**control, "violations": len(rows), "sample": rows[:MAX_ROWS_SHOWN]})
        entries = conn.execute("SELECT count(*) AS n FROM raw.journal_entries").fetchone()["n"]
    if entries == 0:
        raise RuntimeError("The ledger is empty: controls on no data prove nothing.")
    return results


def main() -> int:
    results = run_checks(os.environ["DATABASE_URL"])
    failed = [r for r in results if r["violations"]]
    for r in results:
        status = "FAIL" if r["violations"] else "PASS"
        print(f"[{status}] {r['name']}: {r['description']}")
        if r["violations"]:
            print(f"       {r['violations']} violating row(s); first {len(r['sample'])}:")
            for row in r["sample"]:
                print("       ", {k: str(v) for k, v in row.items()})
    print()
    if failed:
        print(f"CONTROLS FAILED: {len(failed)} of {len(results)} controls have violations.",
              file=sys.stderr)
        return 1
    print(f"All {len(results)} controls passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
