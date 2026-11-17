"""Tests run against a real PostgreSQL database that has been migrated and
loaded (make setup, or the CI workflow). Two connections are used:

  DATABASE_URL            owner login: used to arrange test data
  REPORTING_DATABASE_URL  the app's read-only login: used by the app itself
"""
import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.config import Settings
from app.main import create_app

OWNER_URL = os.environ.get("DATABASE_URL")
READER_URL = os.environ.get("REPORTING_DATABASE_URL")

if not (OWNER_URL and READER_URL):
    pytest.skip("DATABASE_URL and REPORTING_DATABASE_URL must be set", allow_module_level=True)


@pytest.fixture
def owner():
    """Owner connection inside a transaction that is always rolled back."""
    with psycopg.connect(OWNER_URL, row_factory=dict_row) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def reader():
    with psycopg.connect(READER_URL, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def make_settings(**overrides) -> Settings:
    values = dict(reporting_database_url=READER_URL, auth_mode="demo",
                  session_secret="test-secret-" + "x" * 32, cookie_secure=False,
                  google_client_id="", google_client_secret="", google_allowed_domain="",
                  company_name="Halden Supply Co.", currency="EUR")
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="session")
def app():
    return create_app(make_settings())


@pytest.fixture
def client(app):
    with TestClient(app, follow_redirects=False) as c:
        yield c


def sign_in(client: TestClient, email: str) -> TestClient:
    page = client.get("/login")
    csrf = page.text.split('name="csrf" value="')[1].split('"')[0]
    response = client.post("/login/demo", data={"csrf": csrf, "email": email, "next": "/"})
    assert response.status_code == 303, response.text
    return client


@pytest.fixture
def as_user(client):
    return lambda email: sign_in(client, email)
