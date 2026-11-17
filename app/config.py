"""Settings, read once from environment variables (see .env.example)."""
from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass

log = logging.getLogger("app.config")


@dataclass(frozen=True)
class Settings:
    reporting_database_url: str
    auth_mode: str                 # "demo" or "google"
    session_secret: str
    cookie_secure: bool
    google_client_id: str
    google_client_secret: str
    google_allowed_domain: str
    company_name: str
    currency: str

    @property
    def demo_mode(self) -> bool:
        return self.auth_mode == "demo"


def load_settings() -> Settings:
    env = os.environ.get
    auth_mode = env("AUTH_MODE", "demo").lower()
    if auth_mode not in ("demo", "google"):
        raise RuntimeError("AUTH_MODE must be 'demo' or 'google'")

    database_url = env("REPORTING_DATABASE_URL")
    if not database_url:
        raise RuntimeError("REPORTING_DATABASE_URL is not set (see .env.example)")

    session_secret = env("SESSION_SECRET", "")
    if len(session_secret) < 32:
        if auth_mode == "google":
            raise RuntimeError("SESSION_SECRET must be set to at least 32 characters")
        # Demo only: a throwaway secret, so no secret needs to live in the repo.
        session_secret = secrets.token_urlsafe(48)
        log.warning("SESSION_SECRET not set: using a random one; sessions end on restart")

    settings = Settings(
        reporting_database_url=database_url,
        auth_mode=auth_mode,
        session_secret=session_secret,
        cookie_secure=env("COOKIE_SECURE", "true" if auth_mode == "google" else "false") == "true",
        google_client_id=env("GOOGLE_CLIENT_ID", ""),
        google_client_secret=env("GOOGLE_CLIENT_SECRET", ""),
        google_allowed_domain=env("GOOGLE_ALLOWED_DOMAIN", "").lower().lstrip("@"),
        company_name=env("COMPANY_NAME", "Halden Supply Co."),
        currency=env("REPORT_CURRENCY", "EUR"),
    )
    if auth_mode == "google" and not (settings.google_client_id and settings.google_client_secret
                                      and settings.google_allowed_domain):
        raise RuntimeError("AUTH_MODE=google needs GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET "
                           "and GOOGLE_ALLOWED_DOMAIN")
    return settings
