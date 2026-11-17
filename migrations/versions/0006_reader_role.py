"""Read-only role for the web app

Revision ID: 0006
Revises: 0005
"""
from alembic import op

from migrations.sqlfile import run_sql_file

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    run_sql_file("0006_reader_role.sql")


def downgrade() -> None:
    op.execute("""
        REVOKE ALL ON ALL TABLES IN SCHEMA reporting, app FROM finance_reporting_reader;
        REVOKE ALL ON ALL FUNCTIONS IN SCHEMA reporting FROM finance_reporting_reader;
        REVOKE ALL ON SCHEMA reporting, app FROM finance_reporting_reader;
        ALTER DEFAULT PRIVILEGES IN SCHEMA reporting, app
            REVOKE SELECT ON TABLES FROM finance_reporting_reader;
    """)
