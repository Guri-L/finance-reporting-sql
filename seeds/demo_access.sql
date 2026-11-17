-- Demo users, groups and grants for the portfolio version.
-- Idempotent: safe to run on every load. In a real deployment this file is
-- replaced by the organisation's own users and group memberships.
BEGIN;
DELETE FROM app.group_cost_centre_access;
DELETE FROM app.group_report_access;
DELETE FROM app.user_groups;
DELETE FROM app.groups;
DELETE FROM app.users WHERE is_demo;

INSERT INTO app.groups (group_key, group_name, all_cost_centres) VALUES
    ('executives',     'Executive team',            true),
    ('finance',        'Finance team',              true),
    ('credit_control', 'Credit control',            true),
    ('head_marketing', 'Department head: Marketing', false),
    ('head_it',        'Department head: IT',        false);

INSERT INTO app.group_cost_centre_access (group_key, cost_centre_code) VALUES
    ('head_marketing', 'CC200'),
    ('head_it',        'CC400');

INSERT INTO app.group_report_access (group_key, report_key)
SELECT g, r FROM (VALUES ('executives'), ('finance')) AS groups (g)
CROSS JOIN (SELECT report_key AS r FROM app.reports) AS reports;

INSERT INTO app.group_report_access (group_key, report_key) VALUES
    ('credit_control', 'aged_receivables'),
    ('head_marketing', 'pnl'), ('head_marketing', 'budget_vs_actual'),
    ('head_it',        'pnl'), ('head_it',        'budget_vs_actual');

INSERT INTO app.users (email, display_name, job_title, is_demo) VALUES
    ('cfo@halden.example',            'Ines Carvalho', 'Chief Financial Officer', true),
    ('analyst@halden.example',        'Sami Berg',     'Finance Analyst',         true),
    ('credit@halden.example',         'Lena Fors',     'Credit Controller',       true),
    ('head.marketing@halden.example', 'Jonas Akerman', 'Head of Marketing',       true),
    ('head.it@halden.example',        'Tomas Wolde',   'Head of IT',              true);

INSERT INTO app.user_groups (email, group_key) VALUES
    ('cfo@halden.example',            'executives'),
    ('analyst@halden.example',        'finance'),
    ('credit@halden.example',         'credit_control'),
    ('head.marketing@halden.example', 'head_marketing'),
    ('head.it@halden.example',        'head_it');
COMMIT;
