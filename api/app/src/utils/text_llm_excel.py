"""
Build a styled multi-sheet XLSX from ``text_llm_by_schema`` LLM extraction payload.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from src.constants.variables import (
    EXCEL_COLUMN_ID_KEYS,
    EXCEL_FIELD_LABELS,
    EXCEL_WORKBOOK_SHEETS,
    FINANCIAL_EXPENSE_ROWS,
    FINANCIAL_REVENUE_ROWS,
    FINANCIAL_ROW_ORDER,
    FINANCIAL_TOTAL_ROWS,
    RENT_ROLL_BLOCKS,
)

logger = logging.getLogger(__name__)

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    Workbook = None  # type: ignore[misc, assignment]

# Theme
_ACCENT = "0D3B66"
_WHITE = PatternFill("solid", fgColor="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor=_ACCENT)
_PROVENANCE_FILL = PatternFill("solid", fgColor="F7F9FC")
_SECTION_FILL = PatternFill("solid", fgColor="E8EEF4")
_TABLE_HEADER_FILL = PatternFill("solid", fgColor="D6E4F0")
_REVENUE_FILL = PatternFill("solid", fgColor="E8F5E9")
_EXPENSE_FILL = PatternFill("solid", fgColor="FFF8E1")
_TOTAL_FILL = PatternFill("solid", fgColor="E3F2FD")
_DATA_ZEBRA = PatternFill("solid", fgColor="FAFBFC")
_RENT_DESC_FILL = PatternFill("solid", fgColor="E8F4FC")
_RENT_FIN_FILL = PatternFill("solid", fgColor="E8F5E9")
_RENT_LEASE_TENANT_FILL = PatternFill("solid", fgColor="F3E8FF")

_RENT_ROLL_BLOCK_FILLS: dict[str, PatternFill] = {
    "Unit description": _RENT_DESC_FILL,
    "Unit financials": _RENT_FIN_FILL,
    "Lease & tenant": _RENT_LEASE_TENANT_FILL,
}

_VACANT_FONT = Font(name="Calibri", size=10, color="C00000")
_VACANT_FONT_BOLD = Font(name="Calibri", size=10, bold=True, color="C00000")

_HEADER_FONT = Font(name="Calibri", color="FFFFFF", bold=True, size=11)
_SECTION_FONT = Font(name="Calibri", bold=True, size=11, color=_ACCENT)
_BODY_FONT = Font(name="Calibri", size=10, color="1A1A1A")
_BODY_BOLD = Font(name="Calibri", size=10, bold=True, color="1A1A1A")
_TOTAL_FONT = Font(name="Calibri", size=10, bold=True, color=_ACCENT)
_THIN = Side(style="thin", color="D0D7DE")
_MEDIUM = Side(style="medium", color="9EB4C8")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_TOTAL_BORDER = Border(left=_THIN, right=_THIN, top=_MEDIUM, bottom=_MEDIUM)
_WRAP = Alignment(wrapText=True, vertical="top")
_LEFT = Alignment(vertical="top", horizontal="left")
_CENTER = Alignment(vertical="center", horizontal="center")
_RIGHT = Alignment(vertical="center", horizontal="right")

_FMT_CURRENCY = '"$"#,##0.00'
_FMT_CURRENCY_INT = '"$"#,##0'
_FMT_PERCENT = "0.00%"
_FMT_DATE = "mm/dd/yyyy"
_FMT_NUMBER = "#,##0.##"

_SHEET_WHITE_ROWS = 120
_SHEET_WHITE_COLS = 20

_METAINFO_KEY = "page_number"
_YEAR_LABEL_KEYS = frozenset({"kpi_year", "revenue_year", "year"})
_HOTEL_TOKENS = frozenset(
    ("hotel", "hospitality", "lodging", "resort", "motel", "inn", "hostel", "casino")
)

_PERCENT_RE = re.compile(
    r"(^|_)(cap_rate|occupancy|percentage|percent|_pct|growth_percentage|revpar_change)(_|$)",
    re.I,
)
_DATE_RE = re.compile(r"date", re.I)
_CURRENCY_RE = re.compile(
    r"(price|rent|income|revenue|expense|fee|tax|noi|egi|gpr|adr|revpar|bid|reserve|"
    r"population|household_income|operating|profit|ebitda|miscellaneous|departmental|"
    r"undistributed|replacement|utilities|insurance|electric|gas|trash|water)",
    re.I,
)
_DATE_PARSE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%y",
    "%b %d, %Y",
    "%B %d, %Y",
)
# Control chars illegal in XLSX/XML (openpyxl); tab/newline/CR are allowed.
_ILLEGAL_XLSX_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _excel_value(value: Any) -> Any:
    """Strip characters that openpyxl rejects (common in PDF-extracted text)."""
    if value is None:
        return value
    if isinstance(value, str):
        return _ILLEGAL_XLSX_CHARS.sub("", value)
    if isinstance(value, (datetime, date, int, float, bool)):
        return value
    return _ILLEGAL_XLSX_CHARS.sub("", str(value))


class CellKind(str, Enum):
    TEXT = "text"
    CURRENCY = "currency"
    PERCENT = "percent"
    DATE = "date"
    INTEGER = "integer"
    NUMBER = "number"


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _has_meaningful_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_meaningful_value(v) for k, v in value.items() if k != _METAINFO_KEY)
    if isinstance(value, list):
        return any(_has_meaningful_value(v) for v in value)
    return not _is_blank(value)


def _dict_all_values_blank(d: dict[str, Any]) -> bool:
    return all(_is_blank(v) for v in d.values())


def _flatten_item(item: dict[str, Any], *, depth: int = 0) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in item.items():
        if key == _METAINFO_KEY:
            continue
        if isinstance(value, dict):
            if "in_place_t12" in value or "pro_forma_year1" in value:
                for period in ("in_place_t12", "pro_forma_year1"):
                    if value.get(period) is not None:
                        flat[f"{key}.{period}"] = value[period]
            elif depth < 2:
                for sub_k, sub_v in value.items():
                    flat[f"{key}.{sub_k}"] = sub_v
            else:
                flat[key] = value
        else:
            flat[key] = value
    return flat


def _filter_list_columns(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        flat = _flatten_item(raw)
        if flat and not _dict_all_values_blank(flat):
            out.append(flat)
    return out


def _infer_cell_kind(field_key: str, value: Any) -> CellKind:
    if field_key in _YEAR_LABEL_KEYS:
        return CellKind.TEXT
    if _DATE_RE.search(field_key):
        return CellKind.DATE
    if _PERCENT_RE.search(field_key):
        return CellKind.PERCENT
    if isinstance(value, bool):
        return CellKind.TEXT
    if isinstance(value, int) and not _CURRENCY_RE.search(field_key):
        if "year" in field_key.lower() and "founded" not in field_key.lower():
            return CellKind.INTEGER
        if _CURRENCY_RE.search(field_key):
            return CellKind.CURRENCY
        return CellKind.INTEGER
    if isinstance(value, float):
        if _PERCENT_RE.search(field_key):
            return CellKind.PERCENT
        if _CURRENCY_RE.search(field_key):
            return CellKind.CURRENCY
        return CellKind.NUMBER
    if isinstance(value, str) and _parse_date(value) is not None:
        return CellKind.DATE
    return CellKind.TEXT


def _parse_date(value: Any) -> date | datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = _excel_value(value).strip()
    if not text:
        return None
    for fmt in _DATE_PARSE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _coerce_numeric(value: Any) -> float | int | None:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        cleaned = _excel_value(value).strip().replace(",", "").replace("$", "").replace("%", "")
        if not cleaned:
            return None
        try:
            num = float(cleaned)
            return int(num) if num == int(num) else num
        except ValueError:
            return None
    return None


def _prepare_cell(field_key: str, value: Any) -> tuple[Any, CellKind]:
    if _is_blank(value):
        return "", CellKind.TEXT

    kind = _infer_cell_kind(field_key, value)

    if kind == CellKind.DATE:
        parsed = _parse_date(value)
        return (parsed if parsed is not None else value), CellKind.DATE

    if kind == CellKind.PERCENT:
        num = _coerce_numeric(value)
        if num is None:
            return value, CellKind.TEXT
        # Values like 10.43 (percent points) vs 0.1043 (fraction).
        if abs(num) > 1.5:
            num = num / 100.0
        return num, CellKind.PERCENT

    if kind in (CellKind.CURRENCY, CellKind.INTEGER, CellKind.NUMBER):
        num = _coerce_numeric(value)
        if num is None:
            return value, CellKind.TEXT
        return num, kind

    if isinstance(value, bool):
        return ("Yes" if value else "No"), CellKind.TEXT

    if isinstance(value, float) and value == int(value):
        return int(value), CellKind.INTEGER

    if isinstance(value, str):
        return _excel_value(value), CellKind.TEXT

    return value, CellKind.TEXT


def _unit_is_vacant(unit: dict[str, Any]) -> bool:
    status = str(unit.get("unit_rent_status") or "").strip().lower()
    if "vacant" in status:
        return True
    tenant = str(unit.get("tenant_name") or "").strip().lower()
    return tenant in ("vacant", "empty", "available", "-")


def _apply_cell_style(
    cell: Any,
    *,
    kind: CellKind,
    row_fill: PatternFill | None = None,
    bold_label: bool = False,
    bold_value: bool = False,
    is_total_row: bool = False,
    vacant: bool = False,
) -> None:
    cell.border = _TOTAL_BORDER if is_total_row else _BORDER
    cell.alignment = _RIGHT if kind in (
        CellKind.CURRENCY,
        CellKind.PERCENT,
        CellKind.INTEGER,
        CellKind.NUMBER,
    ) else _WRAP
    if kind == CellKind.CURRENCY:
        v = cell.value
        if isinstance(v, (int, float)) and v == int(v):
            cell.number_format = _FMT_CURRENCY_INT
        else:
            cell.number_format = _FMT_CURRENCY
    elif kind == CellKind.PERCENT:
        cell.number_format = _FMT_PERCENT
    elif kind == CellKind.DATE:
        cell.number_format = _FMT_DATE
    elif kind == CellKind.INTEGER:
        cell.number_format = "#,##0"
    elif kind == CellKind.NUMBER:
        cell.number_format = _FMT_NUMBER

    if vacant and not is_total_row:
        cell.font = _VACANT_FONT_BOLD if (bold_value or bold_label) else _VACANT_FONT
        cell.fill = row_fill or _WHITE
    elif is_total_row:
        cell.font = _TOTAL_FONT
        cell.fill = _TOTAL_FILL
    elif bold_value:
        cell.font = _BODY_BOLD
        cell.fill = row_fill or _WHITE
    else:
        cell.font = _BODY_FONT
        cell.fill = row_fill or _WHITE

    if bold_label and cell.column == 1:
        if vacant and not is_total_row:
            cell.font = _VACANT_FONT_BOLD
        else:
            cell.font = _TOTAL_FONT if is_total_row else _BODY_BOLD
        cell.alignment = _LEFT


def _ordered_row_keys(
    columns: list[dict[str, Any]],
    label_section: str,
    *,
    custom_order: tuple[str, ...] | None = None,
) -> list[str]:
    skip = EXCEL_COLUMN_ID_KEYS.get(label_section, frozenset())
    seen: set[str] = set()
    keys: list[str] = []
    order = custom_order or tuple(EXCEL_FIELD_LABELS.get(label_section, {}).keys())
    for k in order:
        if k in skip or k in seen:
            continue
        if any(k in col for col in columns):
            keys.append(k)
            seen.add(k)
    for col in columns:
        for k in col:
            if k in skip or k in seen:
                continue
            keys.append(k)
            seen.add(k)
    return keys


def _row_label(label_section: str, field_key: str) -> str:
    return EXCEL_FIELD_LABELS.get(label_section, {}).get(
        field_key,
        EXCEL_FIELD_LABELS.get("_common", {}).get(
            field_key, field_key.replace("_", " ").replace(".", " — ").title()
        ),
    )


def _collect_page_numbers(*sections: Any) -> str:
    parts: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        if raw is None:
            return
        text = str(raw).strip()
        if not text or text in seen:
            return
        seen.add(text)
        parts.append(text)

    for section in sections:
        if isinstance(section, dict):
            _add(section.get(_METAINFO_KEY))
        elif isinstance(section, list):
            for item in section:
                if isinstance(item, dict):
                    _add(item.get(_METAINFO_KEY))
    return ", ".join(parts)


def _merge_flat_dicts(*dicts: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for d in dicts:
        if not isinstance(d, dict):
            continue
        for k, v in d.items():
            if k == _METAINFO_KEY:
                continue
            if not _is_blank(v):
                merged[k] = v
    return merged


def _is_hotel_asset(data: dict[str, Any]) -> bool:
    meta = data.get("metadata_from_text")
    if not isinstance(meta, dict):
        return False
    asset = (meta.get("asset_type") or "").strip().lower()
    return any(tok in asset for tok in _HOTEL_TOKENS)


def _pick_financial_key(data: dict[str, Any]) -> str | None:
    hotel = data.get("financial_statement_hotel")
    standard = data.get("financial_statement")
    hotel_ok = _has_meaningful_value(hotel)
    standard_ok = _has_meaningful_value(standard)
    if hotel_ok and (not standard_ok or _is_hotel_asset(data)):
        return "financial_statement_hotel"
    if standard_ok:
        return "financial_statement"
    if hotel_ok:
        return "financial_statement_hotel"
    return None


def _financial_row_fill(fin_key: str, row_key: str) -> PatternFill | None:
    if row_key in FINANCIAL_TOTAL_ROWS.get(fin_key, frozenset()):
        return _TOTAL_FILL
    if row_key in FINANCIAL_REVENUE_ROWS.get(fin_key, frozenset()):
        return _REVENUE_FILL
    if row_key in FINANCIAL_EXPENSE_ROWS.get(fin_key, frozenset()):
        return _EXPENSE_FILL
    return None


def _financial_is_total(fin_key: str, row_key: str) -> bool:
    return row_key in FINANCIAL_TOTAL_ROWS.get(fin_key, frozenset())


# ---------------------------------------------------------------------------
# Sheet canvas
# ---------------------------------------------------------------------------


def _init_sheet_canvas(ws: Any) -> None:
    ws.sheet_view.showGridLines = False
    for r in range(1, _SHEET_WHITE_ROWS + 1):
        for c in range(1, _SHEET_WHITE_COLS + 1):
            cell = ws.cell(row=r, column=c)
            cell.fill = _WHITE
            cell.font = _BODY_FONT


def _autosize_columns(ws: Any, max_col: int, min_width: int = 12, max_width: int = 44) -> None:
    for col in range(1, max_col + 1):
        letter = get_column_letter(col)
        best = min_width
        for row in ws.iter_rows(min_col=col, max_col=col):
            for cell in row:
                if cell.value is not None and str(cell.value):
                    best = max(best, min(len(str(cell.value)) + 2, max_width))
        ws.column_dimensions[letter].width = best


def _style_table_header(ws: Any, row: int, col_start: int, col_end: int) -> None:
    for c in range(col_start, col_end + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.border = _BORDER
        cell.alignment = _CENTER


def _write_page_block(ws: Any, row: int, pages: str) -> int:
    ws.cell(row=row, column=1, value="Pages (OM)").font = _BODY_BOLD
    ws.cell(row=row, column=1).fill = _PROVENANCE_FILL
    ws.cell(row=row, column=1).border = _BORDER
    val_cell = ws.cell(row=row, column=2, value=_excel_value(pages or "—"))
    val_cell.font = _BODY_FONT
    val_cell.fill = _PROVENANCE_FILL
    val_cell.border = _BORDER
    val_cell.alignment = _WRAP
    return row + 2


def _write_section_banner(ws: Any, row: int, title: str, last_col: int) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(last_col, 2))
    cell = ws.cell(row=row, column=1, value=_excel_value(title))
    cell.font = _SECTION_FONT
    cell.fill = _SECTION_FILL
    cell.alignment = _LEFT
    cell.border = _BORDER
    return row + 1


def _write_single_column_table(
    ws: Any,
    start_row: int,
    data: dict[str, Any],
    *,
    label_section: str,
) -> int:
    rows = [(k, v) for k, v in data.items() if k != _METAINFO_KEY and not _is_blank(v)]
    if not rows:
        return start_row

    _style_table_header(ws, start_row, 1, 2)
    ws.cell(row=start_row, column=1, value="Field")
    ws.cell(row=start_row, column=2, value="Value")
    r = start_row + 1
    for idx, (key, raw_val) in enumerate(rows):
        display, kind = _prepare_cell(key, raw_val)
        label_cell = ws.cell(row=r, column=1, value=_excel_value(_row_label(label_section, key)))
        _apply_cell_style(label_cell, kind=CellKind.TEXT, row_fill=_DATA_ZEBRA if idx % 2 else _WHITE, bold_label=True)
        val_cell = ws.cell(row=r, column=2, value=_excel_value(display))
        _apply_cell_style(val_cell, kind=kind, row_fill=_DATA_ZEBRA if idx % 2 else _WHITE)
        r += 1
    return r + 1


def _column_header(item: dict[str, Any], index: int, label_section: str) -> str:
    """Build column title from schema id fields (year, unit name, area, etc.)."""
    if label_section == "rent_roll_report":
        parts: list[str] = []
        unit = item.get("unit_name")
        tenant = item.get("tenant_name")
        if not _is_blank(unit):
            parts.append(_excel_value(str(unit)).strip())
        if not _is_blank(tenant):
            parts.append(_excel_value(str(tenant)).strip())
        if parts:
            return _excel_value(" — ".join(parts)[:40])

    for key in EXCEL_COLUMN_ID_KEYS.get(label_section, frozenset()):
        val = item.get(key)
        if not _is_blank(val):
            return _excel_value(str(val).strip()[:40])

    for key in (
        "kpi_year",
        "revenue_year",
        "year",
        "area_type",
        "unit_name",
        "tenant_name",
        "name",
    ):
        val = item.get(key)
        if not _is_blank(val):
            return _excel_value(str(val).strip()[:40])
    return f"Column {index + 1}"


def _row_keys_for_allowed(
    columns: list[dict[str, Any]],
    allowed_keys: tuple[str, ...],
) -> list[str]:
    keys: list[str] = []
    for k in allowed_keys:
        if any(not _is_blank(col.get(k)) for col in columns):
            keys.append(k)
    return keys


def _block_has_data(columns: list[dict[str, Any]], allowed_keys: tuple[str, ...]) -> bool:
    return bool(_row_keys_for_allowed(columns, allowed_keys))


def _write_list_matrix(
    ws: Any,
    start_row: int,
    items: list[Any],
    *,
    label_section: str,
    custom_order: tuple[str, ...] | None = None,
    allowed_keys: tuple[str, ...] | None = None,
    default_row_fill: PatternFill | None = None,
    columns: list[dict[str, Any]] | None = None,
    row_fill_fn: Any = None,
    row_is_total_fn: Any = None,
    repeat_column_headers: bool = True,
    vacant_columns: list[bool] | None = None,
) -> int:
    if columns is None:
        columns = _filter_list_columns([x for x in items if isinstance(x, dict)])
    if not columns:
        return start_row

    if allowed_keys is not None:
        row_keys = _row_keys_for_allowed(columns, allowed_keys)
    else:
        row_keys = _ordered_row_keys(columns, label_section, custom_order=custom_order)
    if not row_keys:
        return start_row

    last_col = 1 + len(columns)
    header_row = start_row
    if repeat_column_headers:
        _style_table_header(ws, header_row, 1, last_col)
        ws.cell(row=header_row, column=1, value="Field")
        for j, col_data in enumerate(columns):
            is_vacant = bool(vacant_columns[j]) if vacant_columns else False
            hdr = ws.cell(
                row=header_row,
                column=j + 2,
                value=_excel_value(_column_header(col_data, j, label_section)),
            )
            if is_vacant:
                hdr.font = _VACANT_FONT_BOLD
                hdr.fill = PatternFill("solid", fgColor="FDECEA")
            else:
                hdr.font = _HEADER_FONT
                hdr.fill = _HEADER_FILL
            hdr.border = _BORDER
            hdr.alignment = _CENTER
        data_start = header_row + 1
    else:
        data_start = start_row

    r = data_start
    prev_block: str | None = None

    for key in row_keys:
        if default_row_fill is not None:
            row_fill = default_row_fill
        elif row_fill_fn:
            row_fill = row_fill_fn(key)
        else:
            row_fill = _DATA_ZEBRA if (r - data_start) % 2 else _WHITE
        is_total = row_is_total_fn(key) if row_is_total_fn else False

        # Visual separator between revenue and expense blocks (financial sheets).
        block: str | None = None
        if row_fill_fn:
            if row_fill == _REVENUE_FILL:
                block = "revenue"
            elif row_fill == _EXPENSE_FILL:
                block = "expense"
            if block and prev_block and block != prev_block:
                r += 1  # blank white spacer row
            prev_block = block

        label_cell = ws.cell(row=r, column=1, value=_excel_value(_row_label(label_section, key)))
        _apply_cell_style(
            label_cell,
            kind=CellKind.TEXT,
            row_fill=row_fill,
            bold_label=True,
            is_total_row=is_total,
        )
        for j, col_data in enumerate(columns):
            is_vacant = bool(vacant_columns[j]) if vacant_columns else False
            raw = col_data.get(key)
            display, kind = _prepare_cell(key, raw)
            cell = ws.cell(row=r, column=j + 2, value=_excel_value(display))
            _apply_cell_style(
                cell,
                kind=kind,
                row_fill=row_fill,
                bold_value=is_total,
                is_total_row=is_total,
                vacant=is_vacant,
            )
        r += 1

    ws.freeze_panes = ws.cell(row=data_start, column=2)
    return r + 1


def _write_financial_matrix(
    ws: Any,
    start_row: int,
    items: list[Any],
    *,
    fin_key: str,
) -> int:
    return _write_list_matrix(
        ws,
        start_row,
        items,
        label_section=fin_key,
        custom_order=FINANCIAL_ROW_ORDER.get(fin_key),
        row_fill_fn=lambda k: _financial_row_fill(fin_key, k) or _WHITE,
        row_is_total_fn=lambda k: _financial_is_total(fin_key, k),
    )


def _write_rent_roll_blocks(
    ws: Any,
    start_row: int,
    rows: list[Any],
) -> int:
    """Rent roll: description, financials, lease & tenant blocks."""
    label_section = "rent_roll_report"
    columns = _filter_list_columns([x for x in rows if isinstance(x, dict)])
    if not columns:
        return start_row

    vacant_columns = [_unit_is_vacant(c) for c in columns]
    last_col = max(1 + len(columns), 2)
    r = start_row
    wrote_any = False

    for block_title, field_keys in RENT_ROLL_BLOCKS:
        if not _block_has_data(columns, field_keys):
            continue
        if wrote_any:
            r += 1  # white spacer between blocks
        wrote_any = True

        r = _write_section_banner(ws, r, block_title, last_col)
        block_fill = _RENT_ROLL_BLOCK_FILLS.get(block_title, _DATA_ZEBRA)
        r = _write_list_matrix(
            ws,
            r,
            rows,
            label_section=label_section,
            allowed_keys=field_keys,
            default_row_fill=block_fill,
            columns=columns,
            vacant_columns=vacant_columns,
        )

    if wrote_any:
        ws.freeze_panes = ws.cell(row=start_row + 1, column=2)
    return r


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------


def _build_summary_sheet(ws: Any, data: dict[str, Any]) -> bool:
    _init_sheet_canvas(ws)
    meta = data.get("metadata_from_text") if isinstance(data.get("metadata_from_text"), dict) else {}
    kpis = data.get("meta_key_kpis") if isinstance(data.get("meta_key_kpis"), dict) else {}
    meta_flat = {k: v for k, v in meta.items() if k != _METAINFO_KEY}
    kpi_rows = kpis.get("cap_noi_per_year") if isinstance(kpis.get("cap_noi_per_year"), list) else []

    if not _has_meaningful_value(meta_flat) and not _has_meaningful_value(kpi_rows):
        return False

    row = _write_page_block(ws, 1, _collect_page_numbers(meta, kpis))
    if _has_meaningful_value(meta_flat):
        row = _write_section_banner(ws, row, "Property summary", 2)
        row = _write_single_column_table(ws, row, meta_flat, label_section="metadata_from_text")
    if _has_meaningful_value(kpi_rows):
        ncol = 1 + max(len(_filter_list_columns(kpi_rows)), 1)
        row = _write_section_banner(ws, row, "Key financial KPIs", ncol)
        row = _write_list_matrix(ws, row, kpi_rows, label_section="meta_key_kpis")
    _autosize_columns(ws, max(ws.max_column, 2))
    return True


def _build_financial_sheet(ws: Any, data: dict[str, Any]) -> bool:
    _init_sheet_canvas(ws)
    fin_key = _pick_financial_key(data)
    if not fin_key:
        return False
    section = data.get(fin_key)
    if not isinstance(section, dict):
        return False
    years = section.get("historical_and_proforma_years")
    if not isinstance(years, list) or not _has_meaningful_value(years):
        return False

    ncol = 1 + len(_filter_list_columns(years))
    row = _write_page_block(ws, 1, _collect_page_numbers(section))
    row = _write_section_banner(ws, row, "Operating statement", max(ncol, 2))
    row = _write_financial_matrix(ws, row, years, fin_key=fin_key)
    _autosize_columns(ws, max(ws.max_column, 2))
    return True


def _build_rent_roll_sheet(ws: Any, data: dict[str, Any]) -> bool:
    _init_sheet_canvas(ws)
    rr = data.get("rent_roll_report")
    if not isinstance(rr, dict):
        return False
    rows = rr.get("rows")
    if not isinstance(rows, list) or not _has_meaningful_value(rows):
        return False

    columns = _filter_list_columns(rows)
    ncol = 1 + max(len(columns), 1)
    row = _write_page_block(ws, 1, _collect_page_numbers(rr))
    row = _write_section_banner(ws, row, "Rent roll", max(ncol, 2))
    _write_rent_roll_blocks(ws, row, rows)
    _autosize_columns(ws, max(ws.max_column, 2))
    return True


def _build_property_sheet(ws: Any, data: dict[str, Any]) -> bool:
    _init_sheet_canvas(ws)
    building = data.get("building_report") if isinstance(data.get("building_report"), dict) else {}
    hotel = data.get("hotel_specific_report") if isinstance(data.get("hotel_specific_report"), dict) else {}
    amenities = data.get("amenities_report") if isinstance(data.get("amenities_report"), dict) else {}
    property_flat = _merge_flat_dicts(building, hotel)
    amen_list = amenities.get("amenities") if isinstance(amenities.get("amenities"), list) else []

    if not _has_meaningful_value(property_flat) and not _has_meaningful_value(amen_list):
        return False

    row = _write_page_block(ws, 1, _collect_page_numbers(building, hotel, amenities))
    if _has_meaningful_value(property_flat):
        row = _write_section_banner(ws, row, "Building & property", 2)
        row = _write_single_column_table(ws, row, property_flat, label_section="building_report")
    if _has_meaningful_value(amen_list):
        ncol = 1 + len(_filter_list_columns([x for x in amen_list if isinstance(x, dict)]))
        row = _write_section_banner(ws, row, "Amenities", max(ncol, 2))
        _write_list_matrix(ws, row, amen_list, label_section="amenities_report")
    _autosize_columns(ws, max(ws.max_column, 2))
    return True


def _build_area_sheet(ws: Any, data: dict[str, Any]) -> bool:
    _init_sheet_canvas(ws)
    demo = data.get("demographics_report") if isinstance(data.get("demographics_report"), dict) else {}
    attr = data.get("attractiveness_report") if isinstance(data.get("attractiveness_report"), dict) else {}
    catchment = demo.get("catchment_areas") if isinstance(demo.get("catchment_areas"), list) else []
    poi = attr.get("zone_attractiveness") if isinstance(attr.get("zone_attractiveness"), list) else []

    if not _has_meaningful_value(catchment) and not _has_meaningful_value(poi):
        return False

    row = _write_page_block(ws, 1, _collect_page_numbers(demo, attr))
    if _has_meaningful_value(catchment):
        ncol = 1 + len(_filter_list_columns([x for x in catchment if isinstance(x, dict)]))
        row = _write_section_banner(ws, row, "Demographics", max(ncol, 2))
        row = _write_list_matrix(ws, row, catchment, label_section="demographics_report")
    if _has_meaningful_value(poi):
        ncol = 1 + len(_filter_list_columns([x for x in poi if isinstance(x, dict)]))
        row = _write_section_banner(ws, row, "Points of interest", max(ncol, 2))
        _write_list_matrix(ws, row, poi, label_section="attractiveness_report")
    _autosize_columns(ws, max(ws.max_column, 2))
    return True


def _build_auction_sheet(ws: Any, data: dict[str, Any]) -> bool:
    _init_sheet_canvas(ws)
    auction = data.get("auction_information")
    if not isinstance(auction, dict) or not _has_meaningful_value(auction):
        return False

    row = _write_page_block(ws, 1, _collect_page_numbers(auction))
    flat = {k: v for k, v in auction.items() if k != _METAINFO_KEY}
    row = _write_section_banner(ws, row, "Auction details", 2)
    _write_single_column_table(ws, row, flat, label_section="auction_information")
    _autosize_columns(ws, 2)
    return True


_SHEET_BUILDERS = {
    "Summary": _build_summary_sheet,
    "Financial statement": _build_financial_sheet,
    "Rent roll": _build_rent_roll_sheet,
    "Property information": _build_property_sheet,
    "Area attractiveness": _build_area_sheet,
    "Auction": _build_auction_sheet,
}


def build_text_llm_workbook(text_llm_by_schema: Optional[dict[str, Any]]) -> Any:
    if Workbook is None:
        raise ImportError("openpyxl is required — pip install openpyxl")

    data = text_llm_by_schema or {}
    wb = Workbook()
    wb.remove(wb.active)

    for sheet_name in EXCEL_WORKBOOK_SHEETS:
        builder = _SHEET_BUILDERS.get(sheet_name)
        if builder is None:
            continue
        ws = wb.create_sheet(title=sheet_name[:31])
        if not builder(ws, data):
            wb.remove(ws)

    if not wb.sheetnames:
        ws = wb.create_sheet(title="Summary")
        _init_sheet_canvas(ws)
        ws.cell(row=1, column=1, value="No extraction data available.")

    return wb


def write_text_llm_excel(
    text_llm_by_schema: Optional[dict[str, Any]],
    output_path: Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = build_text_llm_workbook(text_llm_by_schema)
    wb.save(str(path))
    return path.resolve()


def save_parse_excel_export(
    *,
    text_llm_by_schema: Optional[dict[str, Any]],
    source_pdf_path: Path,
) -> Optional[Path]:
    try:
        out = source_pdf_path.resolve().parent / f"{source_pdf_path.stem}_extraction.xlsx"
        return write_text_llm_excel(text_llm_by_schema, out)
    except ImportError:
        logger.warning("openpyxl not installed — skipping Excel export.")
        return None
    except Exception as exc:
        logger.exception("Excel export failed: %s", exc)
        return None
