"""Load HTML e-mail body from the Valartic markdown design file (```html`` fence)."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FENCE = "```html"


def load_valartic_completion_html_template() -> str:
    md_path = Path(__file__).resolve().parent.parent / "email_templates" / "valartic_completion_email.md"
    text = md_path.read_text(encoding="utf-8")
    start = text.find(_FENCE)
    if start == -1:
        raise ValueError("valartic_completion_email.md: missing ```html block")
    start += len(_FENCE)
    end = text.find("```", start)
    if end == -1:
        raise ValueError("valartic_completion_email.md: unclosed ```html block")
    return text[start:end].strip()


# English labels for metadata fields shown in the completion e-mail summary.
# ``page_number`` is omitted — not shown in the e-mail (see also ``_EMAIL_SUMMARY_SKIP_META_KEYS``).
_METADATA_SUMMARY_LABELS_EN: dict[str, str] = {
    "property_name": "Property",
    "property_address": "Address",
    "city": "City",
    "state": "State / region",
    "asset_type": "Asset type",
    "asking_price": "Asking price ($)",
    "lot_lease_type": "Lot lease type",
    "type_of_sale": "Sale type",
    "total_rentable_square_feet": "Rentable SF",
    "total_available_square_feet_for_rent": "Available SF",
    "total_parcel_size": "Parcel size (SF)",
    "number_of_units": "Number of units",
    "number_of_buildings": "Number of buildings",
    "cap_rate": "Cap rate",
    "total_net_operating_income": "NOI",
}

# Metadata keys never shown in the e-mail body (e.g. page references).
_EMAIL_SUMMARY_SKIP_META_KEYS = frozenset({"page_number"})


def _format_summary_value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, dict):
        if "in_place_t12" in v or "pro_forma_year1" in v:
            parts: list[str] = []
            if v.get("in_place_t12") is not None:
                parts.append(f"T-12: {v.get('in_place_t12')}")
            if v.get("pro_forma_year1") is not None:
                parts.append(f"Y1: {v.get('pro_forma_year1')}")
            return "; ".join(parts) if parts else "—"
        try:
            s = json.dumps(v, ensure_ascii=False, default=str)
        except TypeError:
            s = str(v)
        return s if len(s) <= 480 else s[:477] + "…"
    if isinstance(v, list):
        if not v:
            return "—"
        return ", ".join(str(x) for x in v[:12]) + ("…" if len(v) > 12 else "")
    return str(v)


def _summary_table_row(label: str, value: Any) -> str:
    text = _format_summary_value(value)
    if text == "—" and value is None:
        return ""
    return (
        "<tr>"
        f'<td style="padding:10px 14px;border-bottom:1px solid #e8ecf1;color:#6b7c8f;'
        f'font-weight:600;vertical-align:top;width:42%;">{html.escape(label)}</td>'
        f'<td style="padding:10px 14px;border-bottom:1px solid #e8ecf1;color:#1c2b3a;'
        f'word-break:break-word;">{html.escape(text)}</td>'
        "</tr>"
    )


def build_valartic_summary_rows_html(parse_result: dict[str, Any]) -> str:
    """
    Build inner HTML table rows from the orchestrator result dict.
    Excludes: processing tier, native-PDF flag, and ``page_number`` from metadata.
    """
    rows: list[str] = []

    doc = parse_result.get("document_filename")
    if doc:
        rows.append(_summary_table_row("Document", doc))

    status = parse_result.get("status")
    if status:
        rows.append(_summary_table_row("Status", status))

    err = parse_result.get("errors") or []
    if err:
        rows.append(_summary_table_row("Warnings", "; ".join(str(e) for e in err)))

    meta = parse_result.get("metadata_llm")
    if not isinstance(meta, dict) and isinstance(parse_result.get("text_llm"), dict):
        meta = parse_result["text_llm"].get("metadata_from_text")
    if not isinstance(meta, dict):
        meta = {}

    ordered_keys = list(_METADATA_SUMMARY_LABELS_EN.keys())
    seen: set[str] = set()
    for k in ordered_keys:
        if k in _EMAIL_SUMMARY_SKIP_META_KEYS:
            continue
        if k not in meta:
            continue
        if meta.get(k) is None or meta.get(k) == "":
            continue
        label = _METADATA_SUMMARY_LABELS_EN[k]
        rows.append(_summary_table_row(label, meta[k]))
        seen.add(k)

    for k, v in meta.items():
        if k in _EMAIL_SUMMARY_SKIP_META_KEYS or k in seen or v is None or v == "":
            continue
        label = _METADATA_SUMMARY_LABELS_EN.get(k, k.replace("_", " ").title())
        rows.append(_summary_table_row(label, v))

    body = "\n                ".join(r for r in rows if r)
    if not body.strip():
        return (
            "<tr><td colspan=\"2\" style=\"padding:14px;color:#5a6b7d;font-size:14px;\">"
            "No structured summary is available for this document."
            "</td></tr>"
        )
    return body


def render_valartic_completion_email(
    *,
    task_id: str,
    document_name: str,
    parse_result: dict[str, Any],
    year: int | None = None,
) -> str:
    """Fill the Valartic HTML template; summary rows are derived from ``parse_result``."""
    y = year if year is not None else datetime.now(timezone.utc).year
    summary_rows = build_valartic_summary_rows_html(parse_result)
    tpl = load_valartic_completion_html_template()
    return (
        tpl.replace("{{TASK_ID}}", html.escape(task_id))
        .replace("{{DOCUMENT_NAME}}", html.escape(document_name))
        .replace("{{SUMMARY_ROWS}}", summary_rows)
        .replace("{{YEAR}}", str(y))
    )
