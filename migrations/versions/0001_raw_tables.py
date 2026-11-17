"""Raw layer: ledger tables as delivered

Revision ID: 0001
Revises: None
"""
from alembic import op

from migrations.sqlfile import run_sql_file

revision = "0001"
down_revision = None


def upgrade() -> None:
    run_sql_file("0001_raw_tables.sql")


def downgrade() -> None:
    op.execute("DROP SCHEMA raw CASCADE")
