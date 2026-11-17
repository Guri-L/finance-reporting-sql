"""Finance reporting web app.

Request flow for every report page and every export (they share one code
path, `prepare`):
  1. the session must hold a signed-in email                -> else /login
  2. that user's access is loaded fresh from the database
  3. the report must be granted to one of their groups      -> else 403
  4. the cost centre filter is reduced to permitted centres -> else 403
  5. only then is SQL run, always against reporting.* views
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import auth
from .access import Access, BadRequest, Forbidden, NotSignedIn, load_access
from .config import Settings, load_settings
from .db import Database
from .export import to_csv, to_xlsx
from .formatting import cell, is_negative
from .reports import BUILDERS
from .reports.base import ReportContext, ReportView

HERE = Path(__file__).resolve().parent
audit = logging.getLogger("audit")

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                               "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.reporting_database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.open()
        yield
        db.close()

    app = FastAPI(title="Finance reporting", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["cell"] = cell
    templates.env.tests["negative"] = is_negative
    templates.env.globals.update(company_name=settings.company_name, currency=settings.currency,
                                 demo_mode=settings.demo_mode, auth_mode=settings.auth_mode)
    app.state.settings, app.state.db, app.state.templates = settings, db, templates

    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                       session_cookie="finrep_session", max_age=8 * 3600,
                       same_site="lax", https_only=settings.cookie_secure)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(auth.router)
    if settings.auth_mode == "google":
        app.include_router(auth.google_router(settings))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if not request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"   # figures never sit in shared caches
        return response

    # ------------------------------------------------------------------ helpers
    def current_user(request: Request) -> Access:
        email = request.session.get("email")
        if not email:
            raise NotSignedIn()
        access = load_access(db, email, settings.demo_mode)
        if access is None:          # removed or deactivated since they signed in
            request.session.clear()
            raise NotSignedIn()
        return access

    def page(request: Request, template: str, user: Access | None, status: int = 200, **ctx):
        return templates.TemplateResponse(request, template, {
            "user": user, "csrf": auth.csrf_token(request), **ctx}, status_code=status)

    def prepare(request: Request, report_key: str, period: str | None,
                cost_centre: str | None):
        """Authenticate, authorise and build a report. Used by pages and exports alike."""
        user = current_user(request)
        if report_key not in BUILDERS:
            raise HTTPException(404)
        info = user.require_report(report_key)
        periods = db.query("""SELECT period_key, period_label, period_start, fiscal_year
                              FROM reporting.periods ORDER BY period_start DESC""")
        chosen = periods[0] if not period else next(
            (p for p in periods if p["period_key"] == period), None)
        if chosen is None:
            raise BadRequest("That period does not exist.")
        if info.scope == "cost_centre":
            codes, label = user.resolve_cost_centres(cost_centre)
        else:
            codes, label = [], "Whole company"
        ctx = ReportContext(db, chosen["period_start"], chosen["period_label"],
                            chosen["fiscal_year"], codes, label, settings.currency)
        view: ReportView = BUILDERS[report_key](ctx)
        selected_cc = cost_centre if cost_centre in user.cost_centres else "all"
        return user, info, periods, chosen, ctx, view, selected_cc

    # ------------------------------------------------------------------- routes
    @app.get("/healthz")
    def healthz():
        db.query("SELECT 1")
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        user = current_user(request)
        return page(request, "home.html", user, active=None)

    @app.get("/reports/{report_key}", response_class=HTMLResponse)
    def report_page(request: Request, report_key: str, period: str | None = None,
                    cost_centre: str | None = None):
        user, info, periods, chosen, ctx, view, selected_cc = prepare(
            request, report_key, period, cost_centre)
        audit.info("view user=%s report=%s period=%s cost_centres=%s", user.email, report_key,
                   chosen["period_key"], ",".join(ctx.cost_centres) or "company")
        charts = [{"title": c.title, "kind": c.kind, "labels": c.labels, "datasets": c.datasets,
                   "stacked": c.stacked, "unit": c.unit} for c in view.charts]
        return page(request, "report.html", user, active=report_key, report=info, view=view,
                    periods=periods, period=chosen, selected_cc=selected_cc, ctx=ctx,
                    charts=charts)

    @app.get("/reports/{report_key}/export")
    def report_export(request: Request, report_key: str, format: str = "xlsx",
                      period: str | None = None, cost_centre: str | None = None,
                      table: int = 0):
        user, info, _, chosen, ctx, view, _ = prepare(request, report_key, period, cost_centre)
        if format not in ("xlsx", "csv") or not 0 <= table < len(view.tables):
            raise BadRequest("Unknown export format or table.")
        audit.info("export user=%s report=%s format=%s period=%s cost_centres=%s", user.email,
                   report_key, format, chosen["period_key"],
                   ",".join(ctx.cost_centres) or "company")
        name = f"{report_key}_{chosen['period_key']}"
        if info.scope == "cost_centre":
            name += "_" + ("_".join(ctx.cost_centres) if len(ctx.cost_centres) == 1 else "permitted")
        if format == "csv":
            body, media = to_csv(view.tables[table]), "text/csv; charset=utf-8"
        else:
            body = to_xlsx(view, {
                "Report": info.title, "Company": settings.company_name,
                "Period": chosen["period_label"], "Cost centre": ctx.cost_centre_label,
                "Currency": settings.currency, "Exported by": user.email})
            media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return Response(body, media_type=media, headers={
            "Content-Disposition": f'attachment; filename="{name}.{format}"'})

    # ----------------------------------------------------------- error handling
    @app.exception_handler(NotSignedIn)
    async def not_signed_in(request: Request, exc: NotSignedIn):
        target = request.url.path + ("?" + request.url.query if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target, safe='')}", 303)

    def error_page(request: Request, status: int, title: str, message: str):
        user = None
        if request.session.get("email"):
            user = load_access(db, request.session["email"], settings.demo_mode)
        return page(request, "error.html", user, status, active=None, title=title, message=message)

    @app.exception_handler(Forbidden)
    async def forbidden(request: Request, exc: Forbidden):
        audit.warning("denied user=%s path=%s query=%s", request.session.get("email"),
                      request.url.path, request.url.query)
        return error_page(request, 403, "No access", str(exc))

    @app.exception_handler(BadRequest)
    async def bad_request(request: Request, exc: BadRequest):
        return error_page(request, 400, "That did not work", str(exc))

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        if not request.session.get("email"):
            return RedirectResponse("/login", 303)   # do not reveal which pages exist
        return error_page(request, 404, "Page not found", "There is nothing at this address.")

    return app
