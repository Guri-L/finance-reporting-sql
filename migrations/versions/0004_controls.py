"""Control check views

Revision ID: 0004
Revises: 0003
"""
from alembic import op

from migrations.sqlfile import run_sql_file

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    run_sql_file("0004_controls.sql")


def downgrade() -> None:
    op.execute("DROP SCHEMA controls CASCADE")
