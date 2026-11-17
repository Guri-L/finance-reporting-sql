"""Shared shapes for reports. A report builder returns a ReportView; the HTML
page and both exports are rendered from that same object, so what a user can
export is exactly what they were allowed to see."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..db import Database


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = "text"     # text | money | pct | days | ratio | int | date | status


@dataclass
class Table:
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]      # optional "_class": section | subtotal | total
    note: str = ""


@dataclass
class Chart:
    title: str
    kind: str                       # bar | line
    labels: list[str]
    datasets: list[dict[str, Any]]  # {label, data, type?}
    stacked: bool = False
    unit: str = "money"             # money | pct | days | ratio


@dataclass
class Kpi:
    label: str
    value: Any
    kind: str = "money"
    detail: str = ""


@dataclass
class ReportView:
    tables: list[Table] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    kpis: list[Kpi] = field(default_factory=list)
    commentary: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReportContext:
    """Everything a builder may use. cost_centres is already restricted to
    what the signed-in user is permitted to see."""
    db: Database
    period_start: date
    period_label: str
    fiscal_year: int
    cost_centres: list[str]
    cost_centre_label: str
    currency: str = "EUR"

    @property
    def params(self) -> dict[str, Any]:
        return {"period": self.period_start, "ccs": self.cost_centres,
                "fiscal_year": self.fiscal_year}


def month_label(d: date) -> str:
    return d.strftime("%b %y")


def series(rows: list[dict], key: str) -> list[float | None]:
    return [None if r[key] is None else float(r[key]) for r in rows]
