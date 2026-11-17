-- =========================================================================
-- APP ACCESS: who may see what. Permissions are data, not code: the web app
-- reads these tables on every request and holds no access rules of its own.
--
--   user  --member of-->  group  --granted-->  reports
--                          group  --granted-->  cost centres (or all of them)
--
-- A user's access is the union of their groups' grants.
-- =========================================================================
CREATE SCHEMA app;

-- Grain: one row per person who may sign in. is_demo users can only sign in
-- while the app runs in demo mode.
CREATE TABLE app.users (
    email         text PRIMARY KEY CHECK (email = lower(email)),
    display_name  text NOT NULL,
    job_title     text,
    is_active     boolean NOT NULL DEFAULT true,
    is_demo       boolean NOT NULL DEFAULT false
);

-- Grain: one row per access group.
CREATE TABLE app.groups (
    group_key         text PRIMARY KEY,
    group_name        text NOT NULL,
    all_cost_centres  boolean NOT NULL DEFAULT false
);

CREATE TABLE app.user_groups (
    email      text NOT NULL REFERENCES app.users ON DELETE CASCADE,
    group_key  text NOT NULL REFERENCES app.groups ON DELETE CASCADE,
    PRIMARY KEY (email, group_key)
);

-- Grain: one row per report in the web app. scope says whether the report
-- is split by cost centre ('cost_centre') or exists only for the whole
-- company ('company').
CREATE TABLE app.reports (
    report_key   text PRIMARY KEY,
    title        text NOT NULL,
    description  text NOT NULL,
    scope        text NOT NULL CHECK (scope IN ('cost_centre', 'company')),
    sort_order   integer NOT NULL
);

CREATE TABLE app.group_report_access (
    group_key   text NOT NULL REFERENCES app.groups ON DELETE CASCADE,
    report_key  text NOT NULL REFERENCES app.reports ON DELETE CASCADE,
    PRIMARY KEY (group_key, report_key)
);

-- cost_centre_code is validated against the ledger's cost centres by the
-- access seed and the test suite rather than a foreign key, because the raw
-- layer is reloadable.
CREATE TABLE app.group_cost_centre_access (
    group_key         text NOT NULL REFERENCES app.groups ON DELETE CASCADE,
    cost_centre_code  text NOT NULL,
    PRIMARY KEY (group_key, cost_centre_code)
);

INSERT INTO app.reports (report_key, title, description, scope, sort_order) VALUES
    ('management_summary', 'Management summary', 'Monthly headline figures with commentary on the largest variances.', 'company', 10),
    ('pnl',                'Profit and loss',    'Monthly P&L with year to date and prior-year comparison.', 'cost_centre', 20),
    ('budget_vs_actual',   'Budget vs actual',   'Operating costs against budget by cost centre.', 'cost_centre', 30),
    ('balance_sheet',      'Balance sheet',      'Financial position at each month end.', 'company', 40),
    ('cash_flow',          'Cash flow',          'Cash flow summary, indirect method.', 'company', 50),
    ('aged_receivables',   'Aged receivables',   'Open customer invoices by age bucket.', 'company', 60),
    ('key_ratios',         'Key ratios',         'Margins, days sales outstanding and current ratio.', 'company', 70);

-- Grain: one row per user x report they may open.
CREATE VIEW app.user_report_access AS
SELECT DISTINCT ug.email, r.report_key
FROM app.user_groups ug
JOIN app.group_report_access gra USING (group_key)
JOIN app.reports r USING (report_key);

-- Grain: one row per user x cost centre they may see.
CREATE VIEW app.user_cost_centre_access AS
SELECT ug.email, cc.cost_centre_code
FROM app.user_groups ug
JOIN app.groups g USING (group_key)
JOIN reporting.cost_centres cc ON g.all_cost_centres
UNION
SELECT ug.email, gcc.cost_centre_code
FROM app.user_groups ug
JOIN app.group_cost_centre_access gcc USING (group_key)
JOIN reporting.cost_centres cc USING (cost_centre_code);
