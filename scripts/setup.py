"""One command from empty database to verified reports:

  1. run migrations          (alembic upgrade head)
  2. generate the ledger     (fixed seed, so always the same figures)
  3. load it into raw.*      (full refresh, one transaction)
  4. create the app's read-only login
  5. run every control       (stops with exit code 1 if any fails)

Needs DATABASE_URL (owner login) and REPORTING_DB_PASSWORD.
Usage:  python -m scripts.setup
"""
import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

from datagen.generate import DEFAULT_SEED, generate, write_csvs
from scripts import run_checks
from scripts.create_app_login import create_login
from scripts.load_data import load

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    database_url = os.environ["DATABASE_URL"]
    print("1/5 migrations")
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    with tempfile.TemporaryDirectory() as tmp:
        seed = int(os.environ.get("DATA_SEED", DEFAULT_SEED))
        print(f"2/5 generating ledger (seed {seed})")
        write_csvs(generate(seed), Path(tmp))
        print("3/5 loading raw tables")
        load(Path(tmp), database_url)
    print("4/5 read-only login")
    create_login(database_url, os.environ.get("REPORTING_DB_USER", "reporting_app"),
                 os.environ["REPORTING_DB_PASSWORD"])
    print("5/5 controls")
    return run_checks.main()


if __name__ == "__main__":
    sys.exit(main())
