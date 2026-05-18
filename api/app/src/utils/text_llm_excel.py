"""Build a styled multi-sheet XLSX from ``text_llm_by_schema`` LLM extraction payload."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, get_args, get_origin

from pydantic import BaseModel

from src.constants.variables import (
    EXCEL_FIELD_LABELS,
    EXCEL_SCHEMA_SHEET_TITLES,
    schemas_dict,
)
from src.schemas.parse_pipeline import (
    AuctionInformation,
    DemographicColumn,
    FinancialLineItem,
    FinancialStatementExtraction,
    MarketDemographicsReport,
    MetadataFromText,
    Metainfo,
    RentRollRow,
    RentRollTableExtraction,
)

logger = logging.getLogger(__name__)

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    Workbook = None  # type: ignore[misc, assignment]

_METAINFO_FIELD_NAMES = frozenset(Metainfo.model_fields.keys())

# Metadata sheet: show cap_rate / total_net_operating_income as a mini grid, not flat rows.
_METADATA_CAP_NOI_KEYS = frozenset({"cap_rate", "total_net_operating_income"})
# Present in ``schemas_dict`` for LLM parsing, but workbook sheet is created last — only if non-empty.
_AUCTION_SCHEMA_KEY = "auction_information"
# Shown only in dedicated pivot tables below the main rent-roll grid.
_RENT_ROLL_PRICE_PIVOT_FIELD_KEYS = frozenset({"unit_rent_price_monthly", "unit_rent_price_yearly"})

# --- Visual theme (CRE / professional) ---
_ACCENT = "0D3B66"
_ACCENT_LIGHT = "1B6F93"
_HEADER_FILL = PatternFill("solid", fgColor=_ACCENT)
_SUBHEADER_FILL = PatternFill("solid", fgColor=_ACCENT_LIGHT)
_PROVENANCE_FILL = PatternFill("solid", fgColor="E8F0F7")
_SECTION_FILL = PatternFill("solid", fgColor="B8D4E3")
_ZEBRA = PatternFill("solid", fgColor="F3F6F9")
_HEADER_FONT = Font(name="Calibri", color="FFFFFF", bold=True, size=11)
_SUB_FONT = Font(name="Calibri", color="FFFFFF", bold=True, size=10)
_TITLE_FONT = Font(name="Calibri", bold=True, size=12, color=_ACCENT)
_BODY_FONT = Font(name="Calibri", size=10)
_BODY_BOLD = Font(name="Calibri", size=10, bold=True)
_PROVENANCE_TITLE_FONT = Font(name="Calibri", bold=True, size=11, color=_ACCENT)
_THIN = Side(style="thin", color="C5D5E4")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_WRAP = Alignment(wrapText=True, vertical="top")
_LEFT = Alignment(vertical="top", horizontal="left", indent=0)
_CENTER = Alignment(vertical="center", horizontal="center")

_DATE_FORMATS = (
    "%m/%d/%Y",
    "%Y-%m-%d",
    "%m-%d-%Y",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%y",
)

def _is_nonempty_auction_payload(section: Any) -> bool:
    """True when ``auction_information`` has at least one non-empty value."""
    if not isinstance(section, dict):
        return False

    def _meaningful(v: Any) -> bool:
        if v is None:
            return False
        if isinstance(v, str) and not v.strip():
            return False
        if isinstance(v, (list, dict)) and len(v) == 0:
            return False
        return True

    return any(_meaningful(v) for v in section.values())


def _sanitize_sheet_title(name: str) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", name).strip() or "sheet"
    return cleaned[:31]


def _unique_sheet_title(base: str, used: set[str]) -> str:
    title = _sanitize_sheet_title(base)
    if title not in used:
        used.add(title)
        return title
    i = 1
    while True:
        suffix = f"_{i}"
        room = 31 - len(suffix)
        candidate = (title[:room] + suffix)[:31]
        if candidate not in used:
            used.add(candidate)
            return candidate
        i += 1


def _short_label(text: str, max_len: int = 48) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    first = re.split(r"[.\n]", text, maxsplit=1)[0].strip()
    if len(first) > max_len:
        return first[: max_len - 3] + "..."
    return first


def _title_key(label: str) -> str:
    s = label.replace("_", " ").strip()
    return s[:1].upper() + s[1:] if s else label


def _hard_wrap_text(text: str, width: int = 44) -> str:
    """Insert newlines at word boundaries so long paragraphs fit narrow Excel cells."""
    text = (text or "").strip()
    if not text:
        return ""
    out_paras: list[str] = []
    for para in text.replace("\r\n", "\n").split("\n"):
        para = para.strip()
        if not para:
            out_paras.append("")
            continue
        words = para.split()
        lines: list[str] = []
        cur: list[str] = []
        cur_len = 0
        for w in words:
            extra = len(w) + (1 if cur else 0)
            if cur and cur_len + extra > width:
                lines.append(" ".join(cur))
                cur = [w]
                cur_len = len(w)
            else:
                cur.append(w)
                cur_len += extra
        if cur:
            lines.append(" ".join(cur))
        out_paras.append("\n".join(lines))
    return "\n".join(out_paras)


def _field_row_label(model_cls: type[BaseModel], field_name: str) -> str:
    info = model_cls.model_fields.get(field_name)
    if info and info.description:
        return _short_label(info.description, max_len=56) or _title_key(field_name)
    return _title_key(field_name)


def _path_base_segments(field_path: str) -> list[str]:
    """e.g. rows[0].tenant_name -> ['rows', 'tenant_name']."""
    return [p.split("[", 1)[0] for p in field_path.split(".") if p and p.split("[", 1)[0]]


def _inner_model_from_field(model: type[BaseModel], fname: str) -> type[BaseModel] | None:
    fld = model.model_fields.get(fname)
    if not fld:
        return None
    ann = fld.annotation
    args = tuple(a for a in get_args(ann) if a is not type(None))
    target = args[0] if args else ann
    origin = get_origin(target)
    if origin is list:
        elargs = get_args(target)
        el = elargs[0] if elargs else None
        if isinstance(el, type) and issubclass(el, BaseModel):
            return el
    if isinstance(target, type) and issubclass(target, BaseModel):
        return target
    return None


def _resolve_model_for_path(
    root_model: type[BaseModel], field_path: str
) -> tuple[type[BaseModel], str]:
    segs = _path_base_segments(field_path)
    if not segs:
        return root_model, field_path
    cur = root_model
    for seg in segs[:-1]:
        nxt = _inner_model_from_field(cur, seg)
        if nxt is None:
            return root_model, segs[-1]
        cur = nxt
    return cur, segs[-1]


def _flatten_to_rows(path: str, val: Any, out: list[tuple[str, Any]]) -> None:
    """Expand dicts and lists of dicts into dotted / indexed paths (leaf scalars only)."""
    if val is None:
        return
    if isinstance(val, dict):
        if not val:
            out.append((path, "—"))
            return
        for k, v in val.items():
            sub = f"{path}.{k}" if path else k
            if isinstance(v, dict):
                _flatten_to_rows(sub, v, out)
            elif isinstance(v, list):
                _flatten_to_rows(sub, v, out)
            else:
                out.append((sub, v))
    elif isinstance(val, list):
        if not val:
            return
        if all(isinstance(x, dict) for x in val):
            for i, item in enumerate(val):
                if not isinstance(item, dict):
                    continue
                for k, v in item.items():
                    sub = f"{path}[{i}].{k}" if path else f"[{i}].{k}"
                    if isinstance(v, dict):
                        _flatten_to_rows(sub, v, out)
                    elif isinstance(v, list):
                        _flatten_to_rows(sub, v, out)
                    else:
                        out.append((sub, v))
        else:
            out.append((path, ", ".join(str(x) for x in val if x is not None)))
    else:
        out.append((path, val))


def _excel_row_label(
    schema_key: str,
    root_model: type[BaseModel],
    field_path: str,
) -> str:
    meta = EXCEL_FIELD_LABELS.get("_metainfo", {})
    if field_path in meta:
        return meta[field_path]
    per = EXCEL_FIELD_LABELS.get(schema_key, {})
    if field_path in per:
        return per[field_path]
    # Normalize list indices: rows[0].unit_rent_price_monthly.in_place_t12 -> rows.*...
    norm = re.sub(r"\[\d+\]", "", field_path)
    norm = norm.replace("..", ".").strip(".")
    parts = [p for p in norm.split(".") if p]
    for i in range(len(parts)):
        suf = ".".join(parts[i:])
        if suf in per:
            return per[suf]
    leaf = parts[-1] if parts else field_path
    if leaf in per:
        return per[leaf]
    demo = EXCEL_FIELD_LABELS.get("demographics_report", {})
    if leaf in demo:
        return demo[leaf]
    vmod, vleaf = _resolve_model_for_path(root_model, field_path)
    if vleaf in vmod.model_fields:
        return _field_row_label(vmod, vleaf)
    return _title_key(norm.replace(".", " — ").replace("_", " "))


def _leaf_name(field_path: str) -> str:
    return field_path.rsplit(".", 1)[-1].rsplit("].", 1)[-1]


def _unwrap_optional_union(ann: Any) -> Any:
    """Strip Optional / Union[..., None] wrappers; leave List[...] and bare types."""
    cur: Any = ann
    for _ in range(8):
        origin = get_origin(cur)
        if origin is list:
            return cur
        args = get_args(cur)
        non_none = tuple(a for a in args if a is not type(None))
        if len(non_none) == 1 and len(args) >= 1:
            cur = non_none[0]
            continue
        return cur
    return cur


def _py_type_for_schema_field(model: type[BaseModel] | None, name: str) -> Any:
    if not model or name not in model.model_fields:
        return None
    t = _unwrap_optional_union(model.model_fields[name].annotation)
    if t in (int, float, bool, str):
        return t
    return None


def _financial_line_item_parent(field_path: str | None) -> str | None:
    if not field_path or "." not in field_path:
        return None
    return field_path.split(".", 1)[0].split("[", 1)[0]


def _coerce_int_for_excel(raw: Any) -> int:
    if isinstance(raw, bool):
        raise TypeError
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(round(raw))
    if isinstance(raw, str):
        stem = raw.strip().replace(",", "")
        if not stem:
            raise ValueError
        return int(round(float(stem)))
    raise TypeError


def _is_cap_rate_fli_cell(
    field_path: str | None,
    field_name: str | None,
    field_model: type[BaseModel] | None,
) -> bool:
    if field_model is not FinancialLineItem or field_name not in (
        "in_place_t12",
        "pro_forma_year1",
    ):
        return False
    return _financial_line_item_parent(field_path) == "cap_rate"


def _metadata_cap_noi_summary_table(
    ws: Any,
    start_r: int,
    payload: dict[str, Any],
) -> int:
    """Cap as one row, NOI as one row; T-12 and Y1 columns — only for metadata sheet."""
    r = start_r
    r = _section_title_row(ws, r, "Summary — cap & NOI", last_col=4)
    ws.cell(row=r, column=1, value="")
    t12_lbl = EXCEL_FIELD_LABELS.get("metadata_from_text", {}).get(
        "summary_col_t12", "T-12"
    )
    y1_lbl = EXCEL_FIELD_LABELS.get("metadata_from_text", {}).get("summary_col_y1", "Y1")
    ws.cell(row=r, column=2, value=t12_lbl).font = _SUB_FONT
    ws.cell(row=r, column=3, value=y1_lbl).font = _SUB_FONT
    _style_header_row(ws, r, 3)
    r += 1

    cap = payload.get("cap_rate")
    noi = payload.get("total_net_operating_income")
    cap_lbl = EXCEL_FIELD_LABELS.get("metadata_from_text", {}).get(
        "summary_cap_rate", "Cap (%)"
    )
    noi_lbl = EXCEL_FIELD_LABELS.get("metadata_from_text", {}).get(
        "summary_noi", "NOI ($)"
    )

    ws.cell(row=r, column=1, value=cap_lbl)
    ws.cell(row=r, column=1).font = _BODY_BOLD
    ws.cell(row=r, column=1).border = _BORDER
    ws.cell(row=r, column=1).alignment = _LEFT
    cap_dict = cap if isinstance(cap, dict) else None
    for c_idx, fk in enumerate(("in_place_t12", "pro_forma_year1"), start=2):
        cell = ws.cell(row=r, column=c_idx)
        raw_v = cap_dict.get(fk) if cap_dict else None
        _apply_typed_cell(
            cell,
            raw_v,
            field_name=fk,
            field_path=f"cap_rate.{fk}",
            field_model=FinancialLineItem,
        )
    r += 1

    ws.cell(row=r, column=1, value=noi_lbl)
    ws.cell(row=r, column=1).font = _BODY_BOLD
    ws.cell(row=r, column=1).border = _BORDER
    ws.cell(row=r, column=1).alignment = _LEFT
    noi_dict = noi if isinstance(noi, dict) else None
    for c_idx, fk in enumerate(("in_place_t12", "pro_forma_year1"), start=2):
        cell = ws.cell(row=r, column=c_idx)
        raw_v = noi_dict.get(fk) if noi_dict else None
        _apply_typed_cell(
            cell,
            raw_v,
            field_name=fk,
            field_path=f"total_net_operating_income.{fk}",
            field_model=FinancialLineItem,
        )
    r += 1

    r += 1
    return r


def _is_percentage_field(model_cls: type[BaseModel] | None, field_name: str) -> bool:
    if field_name.startswith("percentage_"):
        return True
    if field_name in ("population_growth_percentage", "submarket_vacancy_rate"):
        return True
    if model_cls and field_name in model_cls.model_fields:
        desc = (model_cls.model_fields[field_name].description or "").lower()
        if "percentage" in desc or ("rate" in desc and "growth" in field_name):
            return True
    return False


def _is_date_field(field_name: str) -> bool:
    return "date" in field_name.lower()


def _parse_date_value(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or s.upper() in ("N/A", "MTM", "—", "-"):
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _excel_percent_value(raw: float) -> float:
    """Store fraction 0–1 for Excel percentage number_format."""
    if raw is None:
        return raw  # type: ignore[return-value]
    x = float(raw)
    if x == 0:
        return 0.0
    if -1.0 <= x <= 1.0:
        return x
    return x / 100.0


def _page_number_cell_text(raw: Any) -> str:
    if raw is None or raw == "":
        return "—"
    if isinstance(raw, list):
        return ", ".join(str(x) for x in raw if x is not None)
    return str(raw)


def _apply_typed_cell(
    cell: Any,
    raw: Any,
    *,
    field_name: str | None = None,
    field_path: str | None = None,
    field_model: type[BaseModel] | None = None,
) -> None:
    """Set cell from raw using Pydantic field types (int/float/str/bool/date/%)."""
    cell.font = _BODY_FONT
    cell.border = _BORDER
    path = field_path if field_path is not None else field_name
    leaf = _leaf_name(path) if path else (field_name or "")
    if leaf == "page_number":
        cell.value = _page_number_cell_text(raw)
        cell.number_format = "@"
        cell.alignment = _WRAP if "," in str(cell.value) else _LEFT
        return
    if raw is None or raw == "":
        cell.value = "—"
        cell.alignment = _CENTER
        return

    py_t = _py_type_for_schema_field(field_model, field_name or "")

    if py_t is bool or isinstance(raw, bool):
        if isinstance(raw, bool):
            b = raw
        else:
            s = str(raw).strip().lower()
            b = s in ("1", "true", "yes", "y")
        cell.value = "Yes" if b else "No"
        cell.alignment = _CENTER
        return

    if field_name and _is_date_field(field_name):
        dt = _parse_date_value(raw)
        if dt is not None:
            cell.value = dt
            cell.number_format = "mm/dd/yyyy"
            cell.alignment = _CENTER
            return

    if _is_cap_rate_fli_cell(field_path, field_name, field_model):
        try:
            x = float(raw)
        except (TypeError, ValueError):
            cell.value = _format_value_plain(raw)
            cell.alignment = _LEFT
            return
        cell.value = _excel_percent_value(x)
        cell.number_format = "0.00%"
        cell.alignment = _CENTER
        return

    if field_name and field_model and _is_percentage_field(field_model, field_name):
        try:
            x = float(raw)
        except (TypeError, ValueError):
            cell.value = _format_value_plain(raw)
            cell.alignment = _LEFT
            return
        cell.value = _excel_percent_value(x)
        cell.number_format = "0.00%"
        cell.alignment = _CENTER
        return

    if py_t is int:
        try:
            cell.value = _coerce_int_for_excel(raw)
        except (TypeError, ValueError):
            cell.value = _format_value_plain(raw)
            cell.alignment = _LEFT
            return
        cell.number_format = "#,##0"
        cell.alignment = _CENTER
        return

    if py_t is float:
        try:
            x = float(raw) if not isinstance(raw, (int, float)) else float(raw)
        except (TypeError, ValueError):
            cell.value = _format_value_plain(raw)
            cell.alignment = _LEFT
            return
        parent = _financial_line_item_parent(field_path)
        if parent == "total_net_operating_income" and abs(x - round(x)) < 1e-6:
            cell.value = int(round(x))
            cell.number_format = "#,##0"
        else:
            cell.value = x
            if abs(x - round(x)) < 1e-9:
                cell.number_format = "#,##0"
            else:
                cell.number_format = "#,##0.00"
        cell.alignment = _CENTER
        return

    if py_t is str:
        s = str(raw)
        if field_name == "tenant_description":
            s = _hard_wrap_text(s, width=44)
            cell.value = s
            cell.number_format = "@"
            cell.alignment = _WRAP
            return
        cell.value = s
        cell.number_format = "@"
        cell.alignment = _WRAP if "\n" in s else _LEFT
        return

    if field_name == "cap_rate" and isinstance(raw, dict):
        parts: list[str] = []
        for k, sub in raw.items():
            if sub is None:
                continue
            fi = FinancialLineItem.model_fields.get(k)
            sub_l = (
                _short_label(fi.description, 28) if fi and fi.description else _title_key(str(k))
            )
            try:
                fv = float(sub)
                parts.append(f"{sub_l}: {fv:.2f}%")
            except (TypeError, ValueError):
                parts.append(f"{sub_l}: {sub}")
        cell.value = "\n".join(parts) if parts else _format_value_plain(raw)
        cell.alignment = _WRAP
        return

    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        x = float(raw)
        cell.value = int(round(x)) if abs(x - round(x)) < 1e-9 else x
        cell.number_format = "#,##0" if isinstance(cell.value, int) else "#,##0.00"
        cell.alignment = _CENTER
        return

    cell.value = _format_value_plain(raw)
    cell.alignment = _WRAP if "\n" in str(raw) else _LEFT


def _format_value_plain(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        parts = []
        for k, sub in v.items():
            if sub is None:
                continue
            fi = FinancialLineItem.model_fields.get(k)
            sub_l = (
                _short_label(fi.description, 28) if fi and fi.description else _title_key(str(k))
            )
            parts.append(f"{sub_l}: {sub}")
        return "\n".join(parts) if parts else json.dumps(v, default=str)
    if isinstance(v, (list, tuple)):
        if not v:
            return ""
        if all(isinstance(x, (str, int, float, bool)) or x is None for x in v):
            return ", ".join(str(x) for x in v if x is not None)
        return json.dumps(v, default=str, indent=2)
    return str(v)


def _ordered_payload_keys(
    model_cls: type[BaseModel], data: dict[str, Any], *, exclude_metainfo: bool = False
) -> list[str]:
    declared = list(model_cls.model_fields.keys())
    ordered: list[str] = []
    seen: set[str] = set()
    for k in declared:
        if exclude_metainfo and k in _METAINFO_FIELD_NAMES:
            continue
        if k in data:
            ordered.append(k)
            seen.add(k)
    for k in data:
        if exclude_metainfo and k in _METAINFO_FIELD_NAMES:
            continue
        if k not in seen:
            ordered.append(k)
            seen.add(k)
    if not exclude_metainfo:
        tail = [k for k in ordered if k in _METAINFO_FIELD_NAMES]
        head = [k for k in ordered if k not in _METAINFO_FIELD_NAMES]
        return head + tail
    return ordered


def _style_header_row(ws: Any, row: int, ncol: int, *, subheader: bool = False) -> None:
    fill = _SUBHEADER_FILL if subheader else _HEADER_FILL
    font = _SUB_FONT if subheader else _HEADER_FONT
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = fill
        cell.font = font
        cell.border = _BORDER
        cell.alignment = _CENTER


def _autosize_columns(ws: Any, max_width: int = 52) -> None:
    for col_idx in range(1, ws.max_column + 1):
        max_len = 10
        letter = get_column_letter(col_idx)
        for row_idx in range(1, min(ws.max_row + 1, 250)):
            v = ws.cell(row=row_idx, column=col_idx).value
            if v is None:
                continue
            lines = str(v).split("\n")
            max_len = max(max_len, min(max(len(line) for line in lines) + 2, max_width))
        ws.column_dimensions[letter].width = float(min(max_len, max_width))


def _apply_zebra(ws: Any, start_row: int, ncol: int) -> None:
    for r in range(start_row, ws.max_row + 1):
        if (r - start_row) % 2 == 1:
            for c in range(1, ncol + 1):
                ws.cell(row=r, column=c).fill = _ZEBRA


def _provenance_block(ws: Any, payload: dict[str, Any], start_r: int) -> int:
    """Small table of Metainfo fields (e.g. page); always shown."""
    r = start_r
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    top = ws.cell(row=r, column=1, value="Extraction source (OM)")
    top.font = _PROVENANCE_TITLE_FONT
    top.fill = _PROVENANCE_FILL
    top.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    for c in range(2, 5):
        ws.cell(row=r, column=c).fill = _PROVENANCE_FILL
    r += 1

    meta_lbl = EXCEL_FIELD_LABELS.get("_metainfo", {})
    for key in Metainfo.model_fields:
        label = meta_lbl.get(key, _field_row_label(Metainfo, key))
        ws.cell(row=r, column=1, value=label)
        ws.cell(row=r, column=1).font = _BODY_BOLD
        ws.cell(row=r, column=1).fill = _PROVENANCE_FILL
        ws.cell(row=r, column=1).border = _BORDER
        ws.cell(row=r, column=1).alignment = _LEFT
        val = payload.get(key)
        val_cell = ws.cell(row=r, column=2)
        if key == "page_number":
            val_cell.value = _page_number_cell_text(val)
            val_cell.number_format = "@"
        else:
            val_cell.value = val if val not in (None, "") else "—"
        val_cell.font = _BODY_FONT
        val_cell.fill = PatternFill("solid", fgColor="FFFFFF")
        val_cell.border = _BORDER
        val_cell.alignment = _WRAP
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
        r += 1

    r += 1
    return r


def _section_title_row(ws: Any, r: int, text: str, last_col: int = 4) -> int:
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=last_col)
    c = ws.cell(row=r, column=1, value=text)
    c.font = _TITLE_FONT
    c.fill = _SECTION_FILL
    c.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    return r + 1


def _sheet_field_value_ordered(
    ws: Any,
    payload: dict[str, Any],
    model_cls: type[BaseModel],
    *,
    schema_key: str,
    start_r: int,
) -> None:
    r = start_r
    if model_cls is MetadataFromText:
        r = _metadata_cap_noi_summary_table(ws, r, payload)
    r = _section_title_row(ws, r, "Extracted fields", last_col=4)
    ws.cell(row=r, column=1, value="Field").font = _SUB_FONT
    ws.cell(row=r, column=2, value="Value").font = _SUB_FONT
    _style_header_row(ws, r, 2)
    r += 1
    hdr_row = r - 1
    flattened: list[tuple[str, Any]] = []
    for key in _ordered_payload_keys(model_cls, payload, exclude_metainfo=True):
        if model_cls is MetadataFromText and key in _METADATA_CAP_NOI_KEYS:
            continue
        _flatten_to_rows(key, payload.get(key), flattened)
    for field_path, val in flattened:
        ws.cell(
            row=r,
            column=1,
            value=_excel_row_label(schema_key, model_cls, field_path),
        )
        ws.cell(row=r, column=1).font = _BODY_BOLD
        ws.cell(row=r, column=1).border = _BORDER
        ws.cell(row=r, column=1).alignment = _LEFT
        vmod, vleaf = _resolve_model_for_path(model_cls, field_path)
        _apply_typed_cell(
            ws.cell(row=r, column=2),
            val,
            field_name=vleaf,
            field_path=field_path,
            field_model=vmod,
        )
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
        r += 1
    ws.freeze_panes = ws.cell(row=hdr_row + 1, column=1)
    _autosize_columns(ws)


def _rent_roll_column_headers(list_rows: list[dict[str, Any]]) -> list[str]:
    headers: list[str] = []
    for j, row_d in enumerate(list_rows, start=1):
        tn = row_d.get("tenant_name")
        if tn is not None and str(tn).strip():
            header = str(tn).strip()
        else:
            header = f"Tenant {j}"
        if len(header) > 36:
            header = header[:33] + "..."
        headers.append(header)
    return headers


def _rent_roll_append_price_pivot(
    ws: Any,
    r: int,
    *,
    list_rows: list[dict[str, Any]],
    schema_key: str,
    fli_field: str,
    title_map_key: str,
    default_title: str,
) -> int:
    """Block: title row, header = tenant names, rows = T-12 and Y1 for one FLI field."""
    r += 1
    labels = EXCEL_FIELD_LABELS.get(schema_key, {})
    title = labels.get(title_map_key, default_title)
    ncol = 1 + len(list_rows)
    last_col = max(4, ncol)
    r = _section_title_row(ws, r, title, last_col=last_col)
    headers = _rent_roll_column_headers(list_rows)
    corner = ws.cell(row=r, column=1, value="")
    corner.font = _SUB_FONT
    corner.fill = _HEADER_FILL
    corner.border = _BORDER
    for j, h in enumerate(headers, start=1):
        c = ws.cell(row=r, column=j + 1, value=h[:40])
        c.font = _HEADER_FONT
        c.fill = _HEADER_FILL
        c.border = _BORDER
        c.alignment = _CENTER
    r += 1
    t12_lbl = labels.get("rent_pivot_t12", "T-12")
    y1_lbl = labels.get("rent_pivot_y1", "Y1")
    for row_label, fk in ((t12_lbl, "in_place_t12"), (y1_lbl, "pro_forma_year1")):
        ws.cell(row=r, column=1, value=row_label)
        ws.cell(row=r, column=1).font = _BODY_BOLD
        ws.cell(row=r, column=1).border = _BORDER
        ws.cell(row=r, column=1).alignment = _LEFT
        for j, d in enumerate(list_rows, start=1):
            cell = ws.cell(row=r, column=j + 1)
            blob = d.get(fli_field)
            raw_v = blob.get(fk) if isinstance(blob, dict) else None
            _apply_typed_cell(
                cell,
                raw_v,
                field_name=fk,
                field_path=f"{fli_field}.{fk}",
                field_model=FinancialLineItem,
            )
        r += 1
    return r


def _sheet_rent_roll(
    ws: Any,
    payload: dict[str, Any],
    *,
    schema_key: str,
    table_model: type[BaseModel],
    row_model: type[BaseModel],
    start_r: int,
) -> None:
    r = start_r
    r = _section_title_row(ws, r, "Rent roll", last_col=8)
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not rows or not isinstance(rows, list):
        desc = table_model.model_fields.get("rows")
        hint = _short_label(desc.description, 80) if desc and desc.description else "rows"
        ws.cell(row=r, column=1, value=f"No data: expected list `{hint}`.")
        return

    list_rows: list[dict[str, Any]] = [x for x in rows if isinstance(x, dict)]
    if not list_rows:
        ws.cell(row=r, column=1, value="No row dicts in `rows`.")
        return

    declared_row_keys = list(row_model.model_fields.keys())
    seen: set[str] = set()
    all_keys: list[str] = []
    for k in declared_row_keys:
        if any(k in d for d in list_rows):
            all_keys.append(k)
            seen.add(k)
    for d in list_rows:
        for k in d:
            if k not in seen:
                seen.add(k)
                all_keys.append(k)

    all_keys = [k for k in all_keys if k not in _RENT_ROLL_PRICE_PIVOT_FIELD_KEYS]

    headers = _rent_roll_column_headers(list_rows)

    field_col_label = EXCEL_FIELD_LABELS.get(schema_key, {}).get(
        "rows", _field_row_label(table_model, "rows")
    )
    ws.cell(row=r, column=1, value=field_col_label[:31]).font = _HEADER_FONT
    ws.cell(row=r, column=1).fill = _HEADER_FILL
    ws.cell(row=r, column=1).border = _BORDER

    max_col = 1 + len(list_rows)
    for j, header in enumerate(headers, start=1):
        c = j + 1
        ws.cell(row=r, column=c, value=header).font = _HEADER_FONT
        ws.cell(row=r, column=c).fill = _HEADER_FILL
        ws.cell(row=r, column=c).border = _BORDER
        ws.cell(row=r, column=c).alignment = _CENTER
    hdr = r
    r += 1
    start_data = r
    for idx, key in enumerate(all_keys):
        ri = start_data + idx
        label = _excel_row_label(schema_key, row_model, key)
        ws.cell(row=ri, column=1, value=label)
        ws.cell(row=ri, column=1).font = _BODY_BOLD
        ws.cell(row=ri, column=1).border = _BORDER
        ws.cell(row=ri, column=1).alignment = _LEFT
        for j, d in enumerate(list_rows, start=1):
            cell = ws.cell(row=ri, column=j + 1)
            raw = d.get(key)
            if isinstance(raw, dict) and (
                "in_place_t12" in raw or "pro_forma_year1" in raw
            ):
                parts_ln: list[str] = []
                for fk in ("in_place_t12", "pro_forma_year1"):
                    if raw.get(fk) is None:
                        continue
                    sub_l = _excel_row_label(schema_key, row_model, f"{key}.{fk}")
                    parts_ln.append(f"{sub_l}: {_format_value_plain(raw.get(fk))}")
                cell.value = "\n".join(parts_ln) if parts_ln else _format_value_plain(raw)
                cell.font = _BODY_FONT
                cell.border = _BORDER
                cell.alignment = _WRAP
            else:
                _apply_typed_cell(
                    cell, raw, field_name=key, field_path=key, field_model=row_model
                )
    _apply_zebra(ws, start_data, max_col)
    if hdr and max_col:
        ws.freeze_panes = ws.cell(row=start_data, column=1)
    r = _rent_roll_append_price_pivot(
        ws,
        ws.max_row,
        list_rows=list_rows,
        schema_key=schema_key,
        fli_field="unit_rent_price_yearly",
        title_map_key="table_yearly_rent",
        default_title="Yearly rent ($)",
    )
    _rent_roll_append_price_pivot(
        ws,
        r,
        list_rows=list_rows,
        schema_key=schema_key,
        fli_field="unit_rent_price_monthly",
        title_map_key="table_monthly_rent",
        default_title="Monthly rent ($)",
    )
    _autosize_columns(ws)


def _is_financial_line_item_field(model_cls: type[BaseModel], field_name: str) -> bool:
    field = model_cls.model_fields.get(field_name)
    if not field:
        return False
    ann = field.annotation
    args = get_args(ann)
    if args:
        non_none = [a for a in args if a not in (type(None), None)]
        return len(non_none) == 1 and non_none[0] is FinancialLineItem
    return ann is FinancialLineItem


def _sheet_financial(
    ws: Any,
    payload: dict[str, Any],
    model_cls: type[BaseModel],
    *,
    schema_key: str,
    start_r: int,
) -> None:
    r = start_r
    r = _section_title_row(ws, r, "Financial statement", last_col=4)
    ws.cell(row=r, column=1, value="Line item")
    ws.cell(row=r, column=2, value=_field_row_label(FinancialLineItem, "in_place_t12"))
    ws.cell(row=r, column=3, value=_field_row_label(FinancialLineItem, "pro_forma_year1"))
    _style_header_row(ws, r, 3)
    hdr = r
    r += 1
    start_data = r

    for key in model_cls.model_fields:
        if key in _METAINFO_FIELD_NAMES:
            continue
        if key not in payload:
            continue
        val = payload[key]
        if not _is_financial_line_item_field(model_cls, key):
            continue
        ws.cell(row=r, column=1, value=_excel_row_label(schema_key, model_cls, key))
        ws.cell(row=r, column=1).font = _BODY_BOLD
        ws.cell(row=r, column=1).border = _BORDER
        if isinstance(val, dict):
            for c_idx, fk in enumerate(("in_place_t12", "pro_forma_year1"), start=2):
                cell = ws.cell(row=r, column=c_idx)
                _apply_typed_cell(
                    cell,
                    val.get(fk),
                    field_name=fk,
                    field_path=f"{key}.{fk}",
                    field_model=FinancialLineItem,
                )
        else:
            cell = ws.cell(row=r, column=2)
            _apply_typed_cell(cell, val, field_name=key, field_path=key, field_model=model_cls)
        r += 1

    for k, v in payload.items():
        if k in _METAINFO_FIELD_NAMES or k not in model_cls.model_fields:
            continue
        if _is_financial_line_item_field(model_cls, k):
            continue
        if v is None:
            continue
        if isinstance(v, dict) and ("in_place_t12" in v or "pro_forma_year1" in v):
            ws.cell(row=r, column=1, value=_excel_row_label(schema_key, model_cls, k))
            ws.cell(row=r, column=1).font = _BODY_BOLD
            ws.cell(row=r, column=1).border = _BORDER
            for c_idx, fk in enumerate(("in_place_t12", "pro_forma_year1"), start=2):
                cell = ws.cell(row=r, column=c_idx)
                _apply_typed_cell(
                    cell,
                    v.get(fk),
                    field_name=fk,
                    field_path=f"{k}.{fk}",
                    field_model=FinancialLineItem,
                )
            r += 1
        elif isinstance(v, dict):
            flat: list[tuple[str, Any]] = []
            _flatten_to_rows(k, v, flat)
            for fp, vv in flat:
                ws.cell(row=r, column=1, value=_excel_row_label(schema_key, model_cls, fp))
                ws.cell(row=r, column=1).font = _BODY_BOLD
                ws.cell(row=r, column=1).border = _BORDER
                vmod, vleaf = _resolve_model_for_path(model_cls, fp)
                cell = ws.cell(row=r, column=2)
                _apply_typed_cell(
                    cell, vv, field_name=vleaf, field_path=fp, field_model=vmod
                )
                ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
                r += 1
        else:
            ws.cell(row=r, column=1, value=_excel_row_label(schema_key, model_cls, k))
            ws.cell(row=r, column=1).font = _BODY_BOLD
            ws.cell(row=r, column=1).border = _BORDER
            cell = ws.cell(row=r, column=2)
            _apply_typed_cell(cell, v, field_name=k, field_path=k, field_model=model_cls)
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
            r += 1

    _apply_zebra(ws, start_data, 3)
    ws.freeze_panes = ws.cell(row=start_data, column=1)
    _autosize_columns(ws)


def _sheet_demographics(
    ws: Any,
    payload: dict[str, Any],
    report_model: type[BaseModel],
    column_model: type[BaseModel],
    *,
    schema_key: str,
    start_r: int,
) -> None:
    r = start_r

    sub_keys = [
        k
        for k in report_model.model_fields
        if k != "catchment_areas"
        and k not in _METAINFO_FIELD_NAMES
        and k in payload
        and payload.get(k) is not None
    ]
    if sub_keys:
        r = _section_title_row(ws, r, "Submarket overview", last_col=3)
        ws.cell(row=r, column=1, value="Metric").font = _SUB_FONT
        ws.cell(row=r, column=2, value="Value").font = _SUB_FONT
        _style_header_row(ws, r, 2, subheader=True)
        sr_hdr = r
        r += 1
        for k in sub_keys:
            ws.cell(row=r, column=1, value=_excel_row_label(schema_key, report_model, k))
            ws.cell(row=r, column=1).font = _BODY_BOLD
            ws.cell(row=r, column=1).border = _BORDER
            cell = ws.cell(row=r, column=2)
            _apply_typed_cell(
                cell, payload.get(k), field_name=k, field_path=k, field_model=report_model
            )
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
            r += 1
        _apply_zebra(ws, sr_hdr + 1, 3)
        r += 1

    areas = payload.get("catchment_areas") or []
    if not isinstance(areas, list) or not areas:
        ca_field = report_model.model_fields.get("catchment_areas")
        hint = (
            _short_label(ca_field.description, 80)
            if ca_field and ca_field.description
            else "catchment_areas"
        )
        ws.cell(row=r, column=1, value=f"No catchment data (`{hint}`).")
        _autosize_columns(ws)
        return

    r = _section_title_row(ws, r, "Demographics by catchment area", last_col=1 + len(areas))

    # Column headers = area_type per column (miles / radius)
    col_labels: list[str] = []
    for idx, row_d in enumerate(areas):
        if not isinstance(row_d, dict):
            col_labels.append(f"Area {idx + 1}")
        else:
            at = row_d.get("area_type")
            col_labels.append(str(at).strip() if at else f"Area {idx + 1}")

    metric_keys = [k for k in column_model.model_fields if k != "area_type"]
    extra: set[str] = set()
    for row_d in areas:
        if isinstance(row_d, dict):
            for k in row_d:
                if k != "area_type" and k not in column_model.model_fields:
                    extra.add(k)
    metric_keys.extend(sorted(extra))

    ws.cell(row=r, column=1, value="Metric").font = _HEADER_FONT
    ws.cell(row=r, column=1).fill = _HEADER_FILL
    ws.cell(row=r, column=1).border = _BORDER
    for j, title in enumerate(col_labels, start=1):
        c = j + 1
        ws.cell(row=r, column=c, value=title[:40]).font = _HEADER_FONT
        ws.cell(row=r, column=c).fill = _HEADER_FILL
        ws.cell(row=r, column=c).border = _BORDER
        ws.cell(row=r, column=c).alignment = _CENTER
    ncol = 1 + len(col_labels)
    hdr_row = r
    r += 1
    start_data = r

    for mkey in metric_keys:
        ws.cell(row=r, column=1, value=_excel_row_label(schema_key, column_model, mkey))
        ws.cell(row=r, column=1).font = _BODY_BOLD
        ws.cell(row=r, column=1).border = _BORDER
        for j, row_d in enumerate(areas, start=1):
            cell = ws.cell(row=r, column=j + 1)
            if not isinstance(row_d, dict):
                cell.value = "—"
                continue
            raw = row_d.get(mkey)
            _apply_typed_cell(
                cell, raw, field_name=mkey, field_path=mkey, field_model=column_model
            )
        r += 1

    _apply_zebra(ws, start_data, ncol)
    ws.freeze_panes = ws.cell(row=start_data, column=1)
    _autosize_columns(ws)


def _fill_sheet(
    ws: Any, schema_key: str, model_cls: type[BaseModel], payload: Optional[dict[str, Any]]
) -> None:
    ws.sheet_view.showGridLines = False
    if payload is None:
        r = _provenance_block(ws, {}, 1)
        ws.cell(row=r, column=1, value=f"No data for `{schema_key}`.")
        return
    try:
        r = _provenance_block(ws, payload, 1)
        if model_cls is RentRollTableExtraction:
            _sheet_rent_roll(
                ws,
                payload,
                schema_key=schema_key,
                table_model=model_cls,
                row_model=RentRollRow,
                start_r=r,
            )
        elif model_cls is FinancialStatementExtraction:
            _sheet_financial(ws, payload, model_cls, schema_key=schema_key, start_r=r)
        elif model_cls is MarketDemographicsReport:
            _sheet_demographics(
                ws,
                payload,
                schema_key=schema_key,
                report_model=model_cls,
                column_model=DemographicColumn,
                start_r=r,
            )
        else:
            _sheet_field_value_ordered(
                ws, payload, model_cls, schema_key=schema_key, start_r=r
            )
    except Exception as exc:
        logger.exception("Excel sheet %s failed: %s", schema_key, exc)
        ws.cell(row=1, column=1, value=f"Error building sheet: {exc}")


def build_text_llm_workbook(text_llm_by_schema: Optional[dict[str, Any]]) -> Any:
    if Workbook is None:
        raise ImportError("openpyxl is required — pip install openpyxl")

    data = text_llm_by_schema or {}
    wb = Workbook()
    wb.remove(wb.active)

    used_titles: set[str] = set()
    for schema_key, model_cls in schemas_dict.items():
        # Auction tab: only when sale is an auction and extraction has values — append after all others.
        if schema_key == _AUCTION_SCHEMA_KEY:
            continue
        tab_base = EXCEL_SCHEMA_SHEET_TITLES.get(schema_key, schema_key)
        title = _unique_sheet_title(tab_base, used_titles)
        ws = wb.create_sheet(title=title)
        section = data.get(schema_key)
        payload = section if isinstance(section, dict) else None
        _fill_sheet(ws, schema_key, model_cls, payload)

    auction_section = data.get(_AUCTION_SCHEMA_KEY)
    if _is_nonempty_auction_payload(auction_section):
        akey = _AUCTION_SCHEMA_KEY
        tab_base = EXCEL_SCHEMA_SHEET_TITLES.get(akey, akey)
        title = _unique_sheet_title(tab_base, used_titles)
        ws = wb.create_sheet(title=title)
        _fill_sheet(
            ws,
            akey,
            AuctionInformation,
            auction_section if isinstance(auction_section, dict) else None,
        )

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
