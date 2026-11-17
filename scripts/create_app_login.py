"""Create (or update) the read-only database login the web app connects with.

Run once per environment by someone with CREATEROLE. The login gets its
privileges only through membership of finance_reporting_reader, which the
migrations define. Reads REPORTING_DB_USER and REPORTING_DB_PASSWORD.
Usage:  python -m scripts.create_app_login
"""
import os

import psycopg
from psycopg import sql


def create_login(database_url: str, user: str, password: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
        verb = sql.SQL("ALTER" if exists else "CREATE")
        conn.execute(sql.SQL(
            "{} ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
            verb, sql.Identifier(user), sql.Literal(password)))
        conn.execute(sql.SQL("GRANT finance_reporting_reader TO {}").format(sql.Identifier(user)))
        conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(conn.info.dbname), sql.Identifier(user)))
        # Belt and braces: even if someone later grants write privileges by
        # mistake, sessions of this login default to read-only transactions.
        conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(
            sql.Identifier(user)))
    print(f"login {user!r} is ready (member of finance_reporting_reader, read-only)")


if __name__ == "__main__":
    create_login(os.environ["DATABASE_URL"],
                 os.environ.get("REPORTING_DB_USER", "reporting_app"),
                 os.environ["REPORTING_DB_PASSWORD"])
