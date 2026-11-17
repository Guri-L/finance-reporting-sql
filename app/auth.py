"""Sign-in. Two interchangeable modes, chosen by AUTH_MODE:

  demo    a clearly labelled page listing demo users (portfolio version)
  google  Google Workspace sign-in (OpenID Connect), restricted to one domain

Both end the same way: the verified email address is stored in a signed
session cookie. What that person may see is NOT stored in the session; it is
read from the app.* tables on every request (see access.py).
"""
from __future__ import annotations

import hmac
import logging
import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .access import BadRequest, Forbidden, load_access

audit = logging.getLogger("audit")
router = APIRouter()


class SignInRejected(Exception):
    pass


def validate_google_claims(claims: dict, allowed_domain: str) -> str:
    """Return the email from verified Google ID token claims, or raise.

    The `hd` (hosted domain) claim is what proves the account belongs to the
    Workspace domain; the email suffix is checked as well.
    """
    email = str(claims.get("email", "")).lower()
    if not email or claims.get("email_verified") is not True:
        raise SignInRejected("Google did not return a verified email address.")
    domain = allowed_domain.lower()
    if str(claims.get("hd", "")).lower() != domain or not email.endswith("@" + domain):
        raise SignInRejected(f"Only {domain} Google Workspace accounts can sign in.")
    return email


def safe_next(target: str | None) -> str:
    """Only ever redirect to a path on this site."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def check_csrf(request: Request, token: str) -> None:
    expected = request.session.get("csrf", "")
    if not expected or not hmac.compare_digest(expected, token or ""):
        raise BadRequest("Your session expired. Go back, reload the page and try again.")


def start_session(request: Request, email: str) -> None:
    request.session.clear()            # never reuse a pre-login session
    request.session["email"] = email
    csrf_token(request)
    audit.info("sign-in user=%s mode=%s", email, request.app.state.settings.auth_mode)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = ""):
    settings, db = request.app.state.settings, request.app.state.db
    if request.session.get("email") and load_access(db, request.session["email"],
                                                    settings.demo_mode):
        return RedirectResponse(safe_next(next), 303)
    demo_users = []
    if settings.demo_mode:
        demo_users = db.query(
            """SELECT u.email, u.display_name, u.job_title,
                      string_agg(g.group_name, ', ' ORDER BY g.group_name) AS groups
               FROM app.users u
               LEFT JOIN app.user_groups ug USING (email)
               LEFT JOIN app.groups g USING (group_key)
               WHERE u.is_demo AND u.is_active
               GROUP BY u.email, u.display_name, u.job_title ORDER BY u.display_name""")
    return request.app.state.templates.TemplateResponse(request, "login.html", {
        "demo_users": demo_users, "next": safe_next(next), "csrf": csrf_token(request),
        "error": error})


@router.post("/login/demo")
def demo_login(request: Request, email: str = Form(...), csrf: str = Form(""),
               next: str = Form("/")):
    settings, db = request.app.state.settings, request.app.state.db
    if not settings.demo_mode:
        raise Forbidden("Demo sign-in is switched off.")
    check_csrf(request, csrf)
    is_demo_user = db.one("SELECT 1 FROM app.users WHERE email = %(e)s AND is_demo AND is_active",
                          {"e": email.lower()})
    if not is_demo_user:
        raise Forbidden("That is not a demo user.")
    start_session(request, email.lower())
    return RedirectResponse(safe_next(next), 303)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    check_csrf(request, csrf)
    audit.info("sign-out user=%s", request.session.get("email"))
    request.session.clear()
    return RedirectResponse("/login", 303)


def google_router(settings) -> APIRouter:
    """Routes for Google Workspace sign-in. Only mounted when AUTH_MODE=google."""
    from authlib.integrations.starlette_client import OAuth, OAuthError

    oauth = OAuth()
    oauth.register(
        "google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"})
    google = APIRouter()

    @google.get("/login/google")
    async def google_start(request: Request, next: str = "/"):
        request.session["next"] = safe_next(next)
        return await oauth.google.authorize_redirect(
            request, str(request.url_for("google_callback")),
            hd=settings.google_allowed_domain, prompt="select_account")

    @google.get("/auth/google/callback", name="google_callback")
    async def google_callback(request: Request):
        try:
            token = await oauth.google.authorize_access_token(request)   # verifies the ID token
            email = validate_google_claims(token.get("userinfo") or {},
                                           settings.google_allowed_domain)
        except (OAuthError, SignInRejected) as exc:
            audit.warning("sign-in rejected reason=%s", exc)
            return RedirectResponse("/login?error=rejected", 303)
        # Being in the domain is not enough: the person must also have been
        # given access in app.users.
        if load_access(request.app.state.db, email, demo_mode=False) is None:
            audit.warning("sign-in rejected user=%s reason=not-provisioned", email)
            return RedirectResponse("/login?error=no-access", 303)
        target = request.session.get("next", "/")
        start_session(request, email)
        return RedirectResponse(safe_next(target), 303)

    return google
