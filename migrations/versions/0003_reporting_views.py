"""Reporting layer views

Revision ID: 0003
Revises: 0002
"""
from alembic import op

from migrations.sqlfile import run_sql_file

revision = "0003"
down_revision = "0002"


def upgrade() -> None:
    run_sql_file("0003_reporting_views.sql")


def downgrade() -> None:
    op.execute("DROP SCHEMA reporting CASCADE")
