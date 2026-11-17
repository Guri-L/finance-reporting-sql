# Permissions

All access is data in the `app` schema. The app holds no access rules of its
own and reads these tables on every request.

| Table | Meaning |
|---|---|
| `app.users` | People who may sign in. `is_active = false` locks someone out at once. `is_demo` users only work in demo mode. |
| `app.groups` | Access groups. `all_cost_centres = true` sees every cost centre. |
| `app.user_groups` | Who is in which group. |
| `app.reports` | Reports in the app. `scope` is `cost_centre` (split by cost centre) or `company` (whole company only). |
| `app.group_report_access` | Which groups may open which reports. |
| `app.group_cost_centre_access` | Which cost centres a group may see, when it does not see all. |

A user's access is the union of their groups. Views
`app.user_report_access` and `app.user_cost_centre_access` show the result.

## How it is enforced

Every report page and every export goes through one function
(`prepare` in `app/main.py`), in this order:

1. No signed-in session: redirect to sign-in.
2. Load the user's access from the tables. User missing or inactive: session ended.
3. Report not granted to any of their groups: 403.
4. Cost centre filter: "all" becomes the user's permitted cost centres; any
   other value must be one of them, otherwise 403. Never silently widened.
5. Only then is SQL run, with the permitted cost centres as a parameter.

Exports are rendered from the same object as the page, so a user can never
export more than they can see. Company-wide reports cannot be split by cost
centre, so a department head is simply not granted them.

## Common changes

```sql
-- New department head for Operations
INSERT INTO app.users (email, display_name, job_title)
VALUES ('k.ng@yourcompany.com', 'Kim Ng', 'Head of Operations');
INSERT INTO app.groups VALUES ('head_operations', 'Department head: Operations', false);
INSERT INTO app.group_cost_centre_access VALUES ('head_operations', 'CC300');
INSERT INTO app.group_report_access VALUES ('head_operations', 'pnl'), ('head_operations', 'budget_vs_actual');
INSERT INTO app.user_groups VALUES ('k.ng@yourcompany.com', 'head_operations');

-- Someone leaves
UPDATE app.users SET is_active = false WHERE email = 'k.ng@yourcompany.com';

-- Who can see Marketing's figures?
SELECT email FROM app.user_cost_centre_access WHERE cost_centre_code = 'CC200';
```

These changes are made with the owner login; the app's own login cannot
write to these tables.
