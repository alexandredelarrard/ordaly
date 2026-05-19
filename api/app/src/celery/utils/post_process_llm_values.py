"""Normalize and deduce missing numeric fields on LLM extraction payloads (in-place)."""

from __future__ import annotations

from typing import Any

_FLI_KEYS = ("in_place_t12", "pro_forma_year1")

def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ensure_fli_dict(d: Any) -> dict[str, Any]:
    if isinstance(d, dict):
        return d
    return {}


def _deduce_rent_roll_row(row: dict[str, Any]) -> None:
    """
    Given ``unit_size`` (SF) and monthly/yearly rent (scalar or legacy FLI dict):
    deduce missing rent fields and ``rent_per_sf`` when possible.
    """
    sf_f = _to_float(row.get("unit_size"))
    if sf_f is None or sf_f <= 0:
        return

    monthly_raw = row.get("unit_rent_price_monthly")
    yearly_raw = row.get("unit_rent_price_yearly")

    if isinstance(monthly_raw, dict) or isinstance(yearly_raw, dict):
        monthly = _ensure_fli_dict(monthly_raw)
        yearly = _ensure_fli_dict(yearly_raw)
        for fk in _FLI_KEYS:
            m = _to_float(monthly.get(fk))
            y = _to_float(yearly.get(fk))
            if m is not None and y is None:
                yearly[fk] = round(m * 12.0, 4)
            elif y is not None and m is None:
                monthly[fk] = round(y / 12.0, 4)
        row["unit_rent_price_monthly"] = monthly
        row["unit_rent_price_yearly"] = yearly
        annual = _to_float(yearly.get("in_place_t12")) or _to_float(yearly.get("pro_forma_year1"))
        if annual is None:
            m0 = _to_float(monthly.get("in_place_t12")) or _to_float(monthly.get("pro_forma_year1"))
            if m0 is not None:
                annual = m0 * 12.0
    else:
        monthly = _to_float(monthly_raw)
        yearly = _to_float(yearly_raw)
        if monthly is not None and yearly is None:
            row["unit_rent_price_yearly"] = round(monthly * 12.0, 4)
            yearly = row["unit_rent_price_yearly"]
        elif yearly is not None and monthly is None:
            row["unit_rent_price_monthly"] = round(yearly / 12.0, 4)
        annual = _to_float(row.get("unit_rent_price_yearly"))

    if row.get("rent_per_sf") is not None:
        return
    if annual is not None and sf_f > 0:
        row["rent_per_sf"] = round(annual / sf_f, 6)


def post_process_llm_values(text_llm_by_schema: dict[str, Any]) -> dict[str, Any]:
    """
    Post-process LLM extraction dicts in-place (also returns the same dict).

    Rent roll: deduce monthly ↔ yearly rent from unit SF; fill ``rent_per_sf`` when possible.
    """
    if not text_llm_by_schema:
        return text_llm_by_schema

    rr = text_llm_by_schema.get("rent_roll_report")
    if isinstance(rr, dict):
        rows = rr.get("rows")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    _deduce_rent_roll_row(row)

    return text_llm_by_schema
