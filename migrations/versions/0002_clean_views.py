"""Cleaned layer views

Revision ID: 0002
Revises: 0001
"""
from alembic import op

from migrations.sqlfile import run_sql_file

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    run_sql_file("0002_clean_views.sql")


def downgrade() -> None:
    op.execute("DROP SCHEMA clean CASCADE")
