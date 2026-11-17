"""Who is this user and what may they see? Answered from the database.

Nothing in this module (or anywhere in the app) names a user, group or cost
centre. Access is loaded from the app.* tables on every request, so a change
in those tables takes effect on the user's next click.
"""
from __future__ import annotations

from dataclasses import dataclass

from .db import Database


class NotSignedIn(Exception):
    """No valid session: send the browser to the sign-in page."""


class Forbidden(Exception):
    """Signed in, but not allowed to see what was asked for."""


class BadRequest(Exception):
    """A filter value that does not exist."""


@dataclass(frozen=True)
class ReportInfo:
    key: str
    title: str
    description: str
    scope: str            # "cost_centre" or "company"


@dataclass(frozen=True)
class Access:
    email: str
    display_name: str
    job_title: str | None
    reports: dict[str, ReportInfo]     # reports this user may open, in menu order
    cost_centres: dict[str, str]       # cost centre code -> name this user may see

    def require_report(self, report_key: str) -> ReportInfo:
        if report_key not in self.reports:
            raise Forbidden("You do not have access to this report.")
        return self.reports[report_key]

    def resolve_cost_centres(self, requested: str | None) -> tuple[list[str], str]:
        """Turn the cost centre filter into the list of codes to query.

        Returns (codes, label). The result is always a subset of what the user
        is permitted to see; asking for anything else is refused, not ignored.
        """
        if not self.cost_centres:
            raise Forbidden("You have not been given access to any cost centre.")
        if requested in (None, "", "all"):
            codes = sorted(self.cost_centres)
            label = (self.cost_centres[codes[0]] if len(codes) == 1
                     else "All permitted cost centres")
            return codes, label
        if requested not in self.cost_centres:
            raise Forbidden("You do not have access to this cost centre.")
        return [requested], self.cost_centres[requested]


def load_access(db: Database, email: str, demo_mode: bool) -> Access | None:
    """Load a user's current access, or None if they may not sign in."""
    user = db.one(
        """SELECT email, display_name, job_title FROM app.users
           WHERE email = %(email)s AND is_active AND (NOT is_demo OR %(demo)s)""",
        {"email": email.lower(), "demo": demo_mode})
    if user is None:
        return None
    reports = db.query(
        """SELECT r.report_key, r.title, r.description, r.scope
           FROM app.user_report_access a JOIN app.reports r USING (report_key)
           WHERE a.email = %(email)s ORDER BY r.sort_order""", user)
    cost_centres = db.query(
        """SELECT cc.cost_centre_code, cc.cost_centre_name
           FROM app.user_cost_centre_access a
           JOIN reporting.cost_centres cc USING (cost_centre_code)
           WHERE a.email = %(email)s ORDER BY cc.cost_centre_code""", user)
    return Access(
        email=user["email"], display_name=user["display_name"], job_title=user["job_title"],
        reports={r["report_key"]: ReportInfo(r["report_key"], r["title"], r["description"],
                                             r["scope"]) for r in reports},
        cost_centres={c["cost_centre_code"]: c["cost_centre_name"] for c in cost_centres})
