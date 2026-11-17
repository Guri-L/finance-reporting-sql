# Finance reporting on PostgreSQL

An end-to-end finance reporting system for **Halden Supply Co.**, a fictional
mid-sized distributor: a synthetic general ledger, a PostgreSQL reporting
layer written in SQL, automated accounting controls, and an internal web app
where each person sees only the reports and cost centres they are allowed to.

It is built the way finance reporting runs in a real company: the same SQL
runs on a laptop and on a company server, every figure has one definition in
a SQL view, the books are checked before anyone sees a number, and access is
enforced on the server.

![Management summary](docs/screenshots/management-summary.png)

## Run it

You need Docker.

```bash
git clone <this repository>
cd finance-reporting-sql
docker compose up --build
```

Open <http://localhost:8000> and pick a demo user. Setup takes about a
minute: it creates the database, generates and loads 24 months of ledger
data, creates a read-only login for the app and runs every control. If a
control fails, the app does not start.

If Docker reports that a port is not available, another program is using it.
Pick free ones, for example `DB_HOST_PORT=25432 APP_HOST_PORT=8080 docker compose up --build`
(PowerShell: `$env:DB_HOST_PORT=25432; docker compose up --build`).

| Demo user | Sees |
|---|---|
| Ines Carvalho, CFO | Every report, every cost centre |
| Sami Berg, Finance Analyst | Every report, every cost centre |
| Lena Fors, Credit Controller | Aged receivables only |
| Jonas Akerman, Head of Marketing | P&L and budget vs actual, **Marketing only** |
| Tomas Wolde, Head of IT | P&L and budget vs actual, **IT only** |

The demo sign-in is clearly labelled and exists because real Google
credentials must never be in a public repository. Switching to Google
Workspace sign-in is configuration only: see [deployment](docs/deployment.md).

## What is in it

```
datagen/       seeded generator for the synthetic ledger
sql/           the SQL: raw tables, cleaned views, reporting views, controls, access
migrations/    Alembic migrations, each a thin wrapper around one file in sql/
scripts/       setup, data load, controls runner, read-only login
seeds/         demo users, groups and grants
app/           the web reporting app (FastAPI, server-rendered HTML)
tests/         78 tests against a real PostgreSQL database
```

### 1. Data

`datagen/generate.py` builds two years (Jan 2024 to Dec 2025) of books for a
company with about EUR 15m revenue: chart of accounts, five cost centres, 45
customers, 3,500 sales invoices and their receipts, supplier invoices,
payroll, rent, depreciation, a bank loan, capital spend, and a monthly
budget. About 8,000 journal entries and 22,000 lines.

The seed is fixed, so everyone gets the same figures to the cent. Money is
handled as integer cents throughout, so nothing is lost to rounding.

It has the imperfections real ledgers have:

- **Late postings.** Supplier invoices dated at month end but keyed in early
  the next month, before the period closed. They land in the right month
  because periods follow the accounting date, not the posting date.
- **Reversals.** Monthly accruals reversed on the 1st, and invoices coded to
  the wrong cost centre, reversed and re-posted.
- **Unpaid invoices.** Slow payers, part payments, and disputed invoices that
  are never paid, which is what fills the 90+ day bucket.
- **An overspending cost centre.** Marketing runs 25 to 45% over its
  advertising budget from May 2025, which the reports and commentary pick up.

### 2. Database

Plain SQL in `sql/`, applied in order by Alembic migrations. One command does
the whole build against whatever `DATABASE_URL` points at:

```bash
python -m scripts.setup        # migrate, load, create read-only login, run controls
```

Locally that is the Docker database; on a server it is the company database.
Nothing else changes. See [deployment](docs/deployment.md).

The app connects as `reporting_app`, a login whose only privilege is
membership of `finance_reporting_reader`: read access to the `reporting` and
`app` schemas and nothing else. It cannot see the raw ledger, cannot write,
and its sessions are read-only by default. The tests prove each of these.

### 3. SQL reporting layer

Three layers, each a schema, every view with its grain stated in a comment:

| Layer | Schema | What it does |
|---|---|---|
| Raw | `raw` | Tables exactly as loaded. Typed, keyed, no foreign keys: a landing zone. |
| Cleaned | `clean` | Trims, NULLs, signs, accounting period from the entry date, late-posting and reversal flags. No aggregation. |
| Reporting | `reporting` | The single definition of every number the app shows. |

Reporting views:

| View | Grain | Report |
|---|---|---|
| `pnl_monthly` | month x cost centre x account | P&L detail with YTD, same month last year, last year to date |
| `pnl_statement` | month x cost centre x statement line | P&L with gross, operating and net profit |
| `budget_vs_actual` | month x cost centre x account | Variance in amount and percent, month and YTD |
| `budget_vs_actual_cost_centre` | month x cost centre | Operating costs vs budget, overspend flag |
| `balance_sheet`, `balance_sheet_totals` | month end x line | Balance sheet at every month end |
| `cash_flow` | month x line | Cash flow summary, indirect method, ties to cash |
| `aged_receivables_invoices`, `aged_receivables` | month end x invoice / customer | 0-30, 31-60, 61-90, 90+ days |
| `key_ratios` | month | Gross and operating margin, DSO, current ratio |

**One definition of each number.** The app only filters these views and adds
up their additive columns. Where a percentage must be recalculated for a
filtered total (for example variance % across two cost centres), it calls the
same SQL function the views use, `reporting.variance_pct`. The commentary on
the management summary is written from the same views, and the tests check
that exported figures equal the views to the cent.

More detail, including sign conventions and formulas:
[docs/architecture.md](docs/architecture.md).

### 4. Controls

Each control is a view in the `controls` schema that returns the rows breaking
it, so an empty result is a pass. `python -m scripts.run_checks` runs them all
and exits with code 1 on any failure; setup, Docker Compose and CI all stop
there.

| Control | Checks |
|---|---|
| `unbalanced_journal_entries` | Every entry: debits = credits |
| `invalid_journal_lines` | Lines one-sided, non-negative, non-zero; every P&L line has a cost centre |
| `balance_sheet_out_of_balance` | Assets = liabilities + equity at every month end |
| `pnl_not_tied_to_ledger` | P&L views tie to the raw ledger to the cent, every month |
| `postings_in_closed_periods` | Nothing posted into a period after it closed |
| `entries_outside_fiscal_periods` | Every entry falls in a defined period |
| `orphaned_keys` | Every reference between raw tables resolves (13 relationships) |
| `overpaid_invoices` | No invoice receives more than its amount |
| `receivables_not_tied_to_ledger` | Aged receivables total = receivables control account |
| `cash_flow_not_tied_to_cash` | Cash flow net change = movement on the cash account |

Each control recomputes its comparison from the raw tables, not from the view
under test. The tests also break the data on purpose (an entry 1 cent out, a
posting into a closed month, an unknown account) and check the right control
fails.

### 5. Web reporting app

One page per report, filters for period and cost centre, charts, tables,
Excel export of the whole report and CSV export of each table, and a monthly
management summary with written commentary on the largest variances.

![Department head view](docs/screenshots/department-head-view.png)

*The Head of Marketing sees Marketing only. Asking for another cost centre by
editing the URL returns 403, for the page and for every export.*

**Sign-in** is required on every page and export. `AUTH_MODE=demo` shows the
labelled demo users; `AUTH_MODE=google` uses Google Workspace (OpenID Connect)
restricted to one domain, checked with the `hd` claim and the email address.
Being in the domain is not enough: the person must also exist in `app.users`.

**Permissions live in the database**, not in code:

```
user --member of--> group --granted--> reports
                    group --granted--> cost centres (or all of them)
```

They are read from `app.*` on every request, so granting or removing access
takes effect on the user's next click, and a deactivated user is signed out
immediately. Pages and exports go through one function that checks the
report grant, reduces the cost centre filter to what the user may see, and
only then runs SQL. Details and how to manage access:
[docs/permissions.md](docs/permissions.md).

Also: CSRF tokens on every form, signed session cookies that expire after 8
hours, redirects that never leave the site, `Cache-Control: no-store` so
figures never sit in a shared cache, a strict Content Security Policy, spreadsheet
formula injection blocked in exports, and an audit log line for every
sign-in, view, export and refused request.

## Tests

```bash
export DATABASE_URL=postgresql://finance_owner:change-me-local-only@localhost:15432/finance
export REPORTING_DATABASE_URL=postgresql://reporting_app:change-me-too@localhost:15432/finance
python -m pytest
```

78 tests, run in CI against PostgreSQL 16 on every push, after lint, a full
setup, and a downgrade-to-empty-and-rebuild of every migration.

- the generator is deterministic and has its imperfections
- every control passes, and each fails on deliberately broken data
- the reporting views do what their comments say (YTD, prior year, buckets, ratio formulas)
- the app login cannot read raw data or write anything
- every page and export needs sign-in
- department heads cannot reach other reports or cost centres, by page or export, and their exports contain only their own figures
- permission changes in the tables apply on the next request
- Google sign-in rejects other domains, unverified emails and missing `hd`

## Stack

PostgreSQL 16 · SQL · Python 3.13 · Alembic · FastAPI · Jinja templates ·
Chart.js (vendored, MIT) · openpyxl · Docker Compose · GitHub Actions

## Not in scope

This is a portfolio stand-in for a real setup, so a few things are left out
on purpose: multi-currency, intercompany, year-end closing entries (profit
since the opening balance is shown on its own equity line), and an admin
screen for permissions (they are managed in SQL, as a DBA would).

All data is synthetic. Halden Supply Co., its people, customers and
suppliers are invented.
