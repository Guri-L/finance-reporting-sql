-- =========================================================================
-- READ-ONLY ACCESS for the web app.
-- finance_reporting_reader is a role without login. The app's own login
-- (created per environment by scripts/create_app_login.py, or by a DBA on a
-- server) is made a member of it. It can read the reporting layer and the
-- access tables and nothing else: no raw or cleaned data, no writes.
-- =========================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finance_reporting_reader') THEN
        CREATE ROLE finance_reporting_reader NOLOGIN;
    END IF;
END
$$;

REVOKE ALL ON SCHEMA raw, clean, controls, reporting, app FROM PUBLIC;
GRANT USAGE ON SCHEMA reporting, app TO finance_reporting_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA reporting, app TO finance_reporting_reader;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA reporting TO finance_reporting_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting, app
    GRANT SELECT ON TABLES TO finance_reporting_reader;
