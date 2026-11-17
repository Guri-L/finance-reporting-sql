"""Database access for the web app: a small pool over the read-only login."""
from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool: ConnectionPool | None = None

    def open(self) -> None:
        # default_transaction_read_only is also set on the login itself; setting
        # it per connection means a misconfigured URL still cannot write.
        self.pool = ConnectionPool(
            self.url, min_size=1, max_size=5, open=False,
            kwargs={"row_factory": dict_row, "autocommit": True,
                    "options": "-c default_transaction_read_only=on -c statement_timeout=15000"})
        self.pool.open(wait=True, timeout=15)

    def close(self) -> None:
        if self.pool is not None:
            self.pool.close()
            self.pool = None

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        if self.pool is None:
            raise RuntimeError("Database pool is not open")
        with self.pool.connection() as conn:
            return conn.execute(sql, params or {}).fetchall()

    def one(self, sql: str, params: dict[str, Any] | None = None) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None
