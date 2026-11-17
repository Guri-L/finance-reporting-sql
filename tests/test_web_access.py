"""Sign-in and permissions are enforced on the server for every page and export."""
import csv
import io

import psycopg
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.auth import SignInRejected, safe_next, validate_google_claims
from app.main import create_app
from tests.conftest import OWNER_URL, make_settings

REPORTS = ["management_summary", "pnl", "budget_vs_actual", "balance_sheet", "cash_flow",
           "aged_receivables", "key_ratios"]
CFO = "cfo@halden.example"
HEAD_MARKETING = "head.marketing@halden.example"
CREDIT = "credit@halden.example"


# ---------------------------------------------------------------- sign-in
@pytest.mark.parametrize("path", ["/"] + [f"/reports/{r}" for r in REPORTS]
                         + [f"/reports/{r}/export?format=xlsx" for r in REPORTS]
                         + [f"/reports/{r}/export?format=csv" for r in REPORTS]
                         + ["/reports/does-not-exist"])
def test_every_page_and_export_requires_sign_in(client, path):
    response = client.get(path)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_demo_login_requires_csrf_token(client):
    client.get("/login")
    response = client.post("/login/demo", data={"csrf": "wrong", "email": CFO})
    assert response.status_code == 400
    assert client.get("/").status_code == 303


def test_demo_login_is_off_in_google_mode():
    settings = make_settings(auth_mode="google", google_client_id="id",
                             google_client_secret="secret", google_allowed_domain="halden.example")
    with TestClient(create_app(settings), follow_redirects=False) as c:
        page = c.get("/login")
        assert "Sign in with Google" in page.text and "Demo sign-in" not in page.text
        assert c.post("/login/demo", data={"email": CFO, "csrf": ""}).status_code == 403


def test_demo_users_cannot_sign_in_outside_demo_mode():
    from app.access import load_access
    from app.db import Database
    from tests.conftest import READER_URL
    db = Database(READER_URL)
    db.open()
    try:
        assert load_access(db, CFO, demo_mode=True) is not None
        assert load_access(db, CFO, demo_mode=False) is None
    finally:
        db.close()


@pytest.mark.parametrize("claims, ok", [
    ({"email": "a@halden.example", "email_verified": True, "hd": "halden.example"}, True),
    ({"email": "A@Halden.Example", "email_verified": True, "hd": "halden.example"}, True),
    ({"email": "a@gmail.com", "email_verified": True}, False),
    ({"email": "a@halden.example", "email_verified": True}, False),              # no hd claim
    ({"email": "a@halden.example", "email_verified": False, "hd": "halden.example"}, False),
    ({"email": "a@other.example", "email_verified": True, "hd": "halden.example"}, False),
])
def test_google_sign_in_is_restricted_to_one_workspace_domain(claims, ok):
    if ok:
        assert validate_google_claims(claims, "halden.example") == claims["email"].lower()
    else:
        with pytest.raises(SignInRejected):
            validate_google_claims(claims, "halden.example")


@pytest.mark.parametrize("target, expected", [
    ("/reports/pnl", "/reports/pnl"), ("https://evil.example", "/"),
    ("//evil.example", "/"), ("/\\evil.example", "/"), (None, "/")])
def test_redirect_after_sign_in_stays_on_site(target, expected):
    assert safe_next(target) == expected


# ------------------------------------------------------------ report access
def test_cfo_can_open_every_report(as_user):
    client = as_user(CFO)
    for report in REPORTS:
        assert client.get(f"/reports/{report}").status_code == 200, report


def test_department_head_sees_only_granted_reports(as_user):
    client = as_user(HEAD_MARKETING)
    assert client.get("/reports/pnl").status_code == 200
    assert client.get("/reports/budget_vs_actual").status_code == 200
    for report in ["management_summary", "balance_sheet", "cash_flow", "aged_receivables",
                   "key_ratios"]:
        assert client.get(f"/reports/{report}").status_code == 403, report
        assert client.get(f"/reports/{report}/export?format=xlsx").status_code == 403, report
        assert client.get(f"/reports/{report}/export?format=csv").status_code == 403, report


def test_menu_lists_only_permitted_reports(as_user):
    html = as_user(CREDIT).get("/").text
    assert "/reports/aged_receivables" in html
    assert "/reports/pnl" not in html


# ------------------------------------------------------- cost-centre access
@pytest.mark.parametrize("path", [
    "/reports/pnl?cost_centre=CC100",
    "/reports/budget_vs_actual?cost_centre=CC400",
    "/reports/pnl/export?format=xlsx&cost_centre=CC100",
    "/reports/budget_vs_actual/export?format=csv&cost_centre=CC300",
    "/reports/pnl/export?format=csv&cost_centre=CC999",
])
def test_department_head_cannot_ask_for_another_cost_centre(as_user, path):
    assert as_user(HEAD_MARKETING).get(path).status_code == 403


def test_department_head_page_only_offers_own_cost_centre(as_user):
    html = as_user(HEAD_MARKETING).get("/reports/budget_vs_actual").text
    assert "CC200" in html
    for other in ["CC100", "CC300", "CC400", "CC500"]:
        assert other not in html


def test_department_head_exports_contain_only_own_figures(as_user, owner):
    client = as_user(HEAD_MARKETING)
    response = client.get("/reports/budget_vs_actual/export?format=csv&period=2025-12")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert {r["Code"] for r in rows} == {"CC200", ""}           # CC200 and the total row
    expected = owner.execute("""SELECT ytd_actual_amount FROM reporting.budget_vs_actual_cost_centre
                                WHERE period_start = '2025-12-01' AND cost_centre_code = 'CC200'""").fetchone()
    total = next(r for r in rows if r["Cost centre"] == "Total")
    assert total["YTD actual"] == str(expected["ytd_actual_amount"])

    workbook = load_workbook(io.BytesIO(client.get(
        "/reports/pnl/export?format=xlsx&period=2025-12").content))
    pnl_total = owner.execute("""SELECT sum(amount) AS a FROM reporting.pnl_statement
                                 WHERE period_start = '2025-12-01' AND cost_centre_code = 'CC200'
                                   AND line_name = 'Net profit'""").fetchone()["a"]
    statement = workbook.worksheets[1]
    net = next(row for row in statement.iter_rows(values_only=True) if row[0] == "Net profit")
    assert round(net[1], 2) == float(pnl_total)
    about = {row[0]: row[1] for row in workbook["About"].iter_rows(values_only=True)}
    assert about["Cost centre"] == "Marketing" and about["Exported by"] == HEAD_MARKETING


def test_company_figures_match_reporting_view(as_user, owner):
    response = as_user(CFO).get("/reports/pnl/export?format=csv&period=2025-12&cost_centre=all")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    net = next(r for r in rows if r["Line"] == "Net profit")
    expected = owner.execute("""SELECT sum(amount) AS a, sum(ytd_amount) AS y FROM reporting.pnl_statement
                                WHERE period_start = '2025-12-01' AND line_name = 'Net profit'""").fetchone()
    assert net["Month"] == str(expected["a"]) and net["Year to date"] == str(expected["y"])


# ------------------------------------------- permissions live in the database
@pytest.fixture
def committed():
    """Owner connection that commits, for changes the app must see."""
    with psycopg.connect(OWNER_URL, autocommit=True) as conn:
        yield conn


def test_granting_access_in_the_table_takes_effect_on_next_request(as_user, committed):
    client = as_user(HEAD_MARKETING)
    assert client.get("/reports/pnl?cost_centre=CC400").status_code == 403
    committed.execute("INSERT INTO app.group_cost_centre_access VALUES ('head_marketing', 'CC400')")
    try:
        assert client.get("/reports/pnl?cost_centre=CC400").status_code == 200
    finally:
        committed.execute("""DELETE FROM app.group_cost_centre_access
                             WHERE group_key = 'head_marketing' AND cost_centre_code = 'CC400'""")
    assert client.get("/reports/pnl?cost_centre=CC400").status_code == 403


def test_deactivated_user_is_signed_out_immediately(as_user, committed):
    client = as_user(CREDIT)
    assert client.get("/reports/aged_receivables").status_code == 200
    committed.execute("UPDATE app.users SET is_active = false WHERE email = %s", (CREDIT,))
    try:
        assert client.get("/reports/aged_receivables").status_code == 303
        assert client.get("/reports/aged_receivables/export?format=csv").status_code == 303
    finally:
        committed.execute("UPDATE app.users SET is_active = true WHERE email = %s", (CREDIT,))


# ----------------------------------------------------------------- hygiene
def test_bad_filters_are_rejected(as_user):
    client = as_user(CFO)
    assert client.get("/reports/pnl?period=1999-01").status_code == 400
    assert client.get("/reports/pnl/export?format=pdf").status_code == 400
    assert client.get("/reports/pnl/export?format=csv&table=9").status_code == 400


def test_responses_are_not_cached_and_carry_security_headers(as_user):
    response = as_user(CFO).get("/reports/pnl")
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_sign_out_ends_the_session(as_user):
    client = as_user(CFO)
    csrf = client.get("/").text.split('name="csrf" value="')[1].split('"')[0]
    assert client.post("/logout", data={"csrf": csrf}).status_code == 303
    assert client.get("/reports/pnl").status_code == 303
