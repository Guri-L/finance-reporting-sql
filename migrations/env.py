"""Alembic environment. Migrations are plain SQL files in sql/, run in order.

The database is chosen by DATABASE_URL alone, which is what lets the same
migrations run against local Docker and a company server unchanged.
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def run_migrations() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline mode is not supported; set DATABASE_URL and run online.")
run_migrations()
