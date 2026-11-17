"""Web app access tables

Revision ID: 0005
Revises: 0004
"""
from alembic import op

from migrations.sqlfile import run_sql_file

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    run_sql_file("0005_app_access.sql")


def downgrade() -> None:
    op.execute("DROP SCHEMA app CASCADE")
