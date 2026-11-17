"""Excel and CSV exports, rendered from the same ReportView as the page."""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from .reports.base import ReportView, Table

NUMBER_FORMATS = {"money": "#,##0.00;(#,##0.00)", "pct": '0.0"%"', "days": "0.0",
                  "ratio": "0.00", "int": "#,##0", "date": "yyyy-mm-dd"}


def _safe_text(value):
    """Stop spreadsheet apps from treating exported text as a formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def to_xlsx(view: ReportView, meta: dict[str, str]) -> bytes:
    wb = Workbook()
    about = wb.active
    about.title = "About"
    for key, value in {**meta, "Generated (UTC)":
                       datetime.now(UTC).strftime("%Y-%m-%d %H:%M")}.items():
        about.append([key, value])
    for row in about.iter_rows(min_col=1, max_col=1):
        row[0].font = Font(bold=True)
    about.column_dimensions["A"].width = 22
    about.column_dimensions["B"].width = 60

    for index, table in enumerate(view.tables, start=1):
        ws = wb.create_sheet(_sheet_name(table.title, index))
        ws.append([c.label for c in table.columns])
        for header in ws[1]:
            header.font = Font(bold=True)
            header.alignment = Alignment(wrap_text=True, vertical="top")
        for row in table.rows:
            ws.append([_safe_text(row.get(c.key)) for c in table.columns])
            css = row.get("_class")
            for col, cell in zip(table.columns, ws[ws.max_row]):
                if col.kind in NUMBER_FORMATS:
                    cell.number_format = NUMBER_FORMATS[col.kind]
                if css in ("section", "subtotal", "total"):
                    cell.font = Font(bold=True)
        for i, col in enumerate(table.columns, start=1):
            ws.column_dimensions[get_column_letter(i)].width = 34 if col.kind == "text" else 18
        ws.freeze_panes = "A2"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def to_csv(table: Table) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([c.label for c in table.columns])
    for row in table.rows:
        writer.writerow(["" if row.get(c.key) is None else _safe_text(row.get(c.key))
                         for c in table.columns])
    return buffer.getvalue().encode("utf-8-sig")   # BOM so Excel reads UTF-8


def _sheet_name(title: str, index: int) -> str:
    cleaned = "".join(ch for ch in title if ch not in r"[]:*?/\\")
    return f"{index} {cleaned}"[:31]
