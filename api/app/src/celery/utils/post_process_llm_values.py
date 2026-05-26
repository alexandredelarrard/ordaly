"""
Post-process LLM extraction payloads in-place so **metadata**, **rent roll**, and
**standard financial statements** use consistent numbers where fields are missing
or obviously inconsistent.

Hotel / hospitality assets are skipped for rent-roll and standard-financial math
(different P&L shape); hotel statements are left unchanged.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Any

logger = logging.getLogger(__name__)

_HOTEL_TOKENS = frozenset(
    ("hotel", "hospitality", "lodging", "resort", "motel", "inn", "hostel", "casino")
)

_STANDARD_OPEX_KEYS: tuple[str, ...] = (
    "taxes_property",
    "insurance",
    "utilities_combined",
    "management_fees",
    "repairs_and_maintenance",
    "general_and_administrative",
)

_LEASE_END_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%m/%d/%y",
    "%b %d, %Y",
    "%B %d, %Y",
)
_DAYS_PER_YEAR = 365.2425
_YEAR_ONLY_LEASE_END = re.compile(r"^\s*(\d{4})\s*$")

# Income + opex keys used to detect "NOI only" sparse financial cycles (no other line items set).
_FIN_NOI_ONLY_SENTINEL_KEYS: tuple[str, ...] = (
    "gross_potential_rent",
    "expense_reimbursements",
    "other_income",
    "gross_scheduled_income",
    "vacancy_loss",
    "effective_gross_income",
    "total_operating_expenses",
    "other_operating_expenses",
    *_STANDARD_OPEX_KEYS,
)


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------


def _financial_amount_tolerance(expected: float) -> float:
    return max(500.0, 0.02 * max(abs(expected), 1.0))


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        t = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not t:
            return None
        try:
            return float(t)
        except ValueError:
            return None
    return None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _is_hotel_metadata(meta: dict[str, Any]) -> bool:
    asset_type = (meta.get("asset_type") or "").strip().lower()
    return any(tok in asset_type for tok in _HOTEL_TOKENS)


def _unit_is_vacant(unit: dict[str, Any]) -> bool:
    tenant = str(unit.get("tenant_name") or "").strip().lower()
    return tenant in ("vacant", "empty", "available", "-", "")


def _cap_rate_as_fraction(cap_rate: Any) -> float | None:
    """
    Schema stores cap as percent points (e.g. 6.75). Values already in (0,1] are treated as fractions.
    """
    c = _to_float(cap_rate)
    if c is None or c == 0.0:
        return None
    if abs(c) <= 1.0:
        return c
    return c / 100.0


def _cap_rate_to_storage_percent_points(fraction: float) -> float:
    """Store back as 6.75-style percent when |fraction| <= 1."""
    if abs(fraction) <= 1.0:
        return round(fraction * 100.0, 2)
    return round(fraction, 2)


# ---------------------------------------------------------------------------
# Rent roll
# ---------------------------------------------------------------------------


def _iter_rent_roll_unit_rows(rent_roll: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rows = rent_roll.get("rows")
    if not isinstance(rows, list):
        return out
    for building in rows:
        if not isinstance(building, dict):
            continue
        inner = building.get("rows")
        if not isinstance(inner, list):
            continue
        for unit in inner:
            if isinstance(unit, dict):
                out.append(unit)
    return out


def _sum_annual_rent_from_roll(rent_roll: dict[str, Any]) -> float:
    total = 0.0
    for unit in _iter_rent_roll_unit_rows(rent_roll):
        ar = _to_float(unit.get("annual_rent_usd"))
        if ar is not None:
            total += ar
    return total


def _sum_unit_sf_from_roll(rent_roll: dict[str, Any]) -> float:
    total = 0.0
    for unit in _iter_rent_roll_unit_rows(rent_roll):
        sf = _to_float(unit.get("unit_size_sf"))
        if sf is not None and sf > 0:
            total += sf
    return total


def _occupancy_from_roll(rent_roll: dict[str, Any]) -> float | None:
    """Occupied SF / total leasable SF (excludes vacant rows with no SF)."""
    total_sf = 0.0
    occ_sf = 0.0
    for unit in _iter_rent_roll_unit_rows(rent_roll):
        sf = _to_float(unit.get("unit_size_sf"))
        if sf is None or sf <= 0:
            continue
        total_sf += sf
        if not _unit_is_vacant(unit):
            occ_sf += sf
    if total_sf <= 0:
        return None
    return round(100.0 * occ_sf / total_sf, 2)


def _lease_remaining_years_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _parse_lease_end_date(text: str) -> date | None:
    """Parse a verifiable lease end; skip MTM / options / placeholders."""
    t = text.strip()
    if not t:
        return None
    upper = t.upper()
    if upper in ("N/A", "—", "-", "NA", "TBD"):
        return None
    if "MTM" in upper or "MONTH TO MONTH" in upper:
        return None
    if "OPTION" in upper:
        return None
    for fmt in _LEASE_END_DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    m = _YEAR_ONLY_LEASE_END.match(t)
    if m:
        y = int(m.group(1))
        try:
            return date(y, 12, 31)
        except ValueError:
            return None
    return None


def _lease_end_date_from_record(lease: dict[str, Any]) -> str | None:
    end = lease.get("lease_end_date")
    if not _is_blank(end):
        return str(end).strip()
    return None


def _deduce_lease_remaining_years_for_record(lease: dict[str, Any], *, now: datetime | None = None) -> None:
    """
    Set ``lease_remaining_years`` (1 decimal) on a single ``Leases`` dict from
    ``lease_end_date`` vs **now** when missing.
    """
    now = now or datetime.today()
    if not _lease_remaining_years_blank(lease.get("lease_remaining_years")):
        return
    raw = _lease_end_date_from_record(lease)
    if not raw:
        return
    end_d = _parse_lease_end_date(raw)
    if end_d is None:
        return

    end_of_lease_day = datetime.combine(end_d, time.max)
    delta = end_of_lease_day - now
    seconds_per_avg_year = _DAYS_PER_YEAR * 24 * 3600
    lease["lease_remaining_years"] = round(delta.total_seconds() / seconds_per_avg_year, 1)


def _deduce_lease_remaining_years(unit: dict[str, Any], *, now: datetime | None = None) -> None:
    """Fill missing ``lease_remaining_years`` on each lease record (list or legacy dict)."""
    anchor = now or datetime.today()
    ul = unit.get("unit_leases")
    if isinstance(ul, list):
        for le in ul:
            if isinstance(le, dict):
                _deduce_lease_remaining_years_for_record(le, now=anchor)
        return
    if isinstance(ul, dict):
        _deduce_lease_remaining_years_for_record(ul, now=anchor)
        if _lease_remaining_years_blank(unit.get("lease_remaining_years")) and not _lease_remaining_years_blank(
            ul.get("lease_remaining_years")
        ):
            unit["lease_remaining_years"] = ul["lease_remaining_years"]
        return
    # Legacy: lease dates only on the unit row
    if not _lease_remaining_years_blank(unit.get("lease_remaining_years")):
        return
    raw = unit.get("lease_end_date")
    if _is_blank(raw):
        return
    end_d = _parse_lease_end_date(str(raw).strip())
    if end_d is None:
        return
    end_of_lease_day = datetime.combine(end_d, time.max)
    delta = end_of_lease_day - anchor
    seconds_per_avg_year = _DAYS_PER_YEAR * 24 * 3600
    unit["lease_remaining_years"] = round(delta.total_seconds() / seconds_per_avg_year, 1)


def _clear_rent_fields_for_vacant_unit(unit: dict[str, Any]) -> None:
    """Vacant rows should not carry rent amounts (OM noise / hallucinations)."""
    unit["monthly_rent_usd"] = None
    unit["annual_rent_usd"] = None
    unit["rent_per_sf_yearly"] = None


def _correct_rent_roll_in_place(rent_roll: dict[str, Any]) -> None:
    """
    - Align ``number_tenants_in_building`` with row count.
    - For **Vacant** tenants: set ``monthly_rent_usd``, ``annual_rent_usd``, ``rent_per_sf_yearly`` to null.
    - Derive ``annual_rent_usd`` from ``monthly_rent_usd`` and vice versa (occupied only).
    - Derive ``rent_per_sf_yearly`` from annual rent and ``unit_size_sf`` when possible (occupied only).
    - Derive ``lease_remaining_years`` from ``lease_end_date`` vs today when missing (1 decimal).
    """
    rows = rent_roll.get("rows")
    if not isinstance(rows, list) or not rows:
        return

    for i, building in enumerate(rows):
        if not isinstance(building, dict):
            continue
        urows = building.get("rows")
        if not isinstance(urows, list):
            urows = []
            building["rows"] = urows

        n_units = len(urows)
        declared = building.get("number_tenants_in_building")
        if declared != n_units:
            bname = building.get("building_name")
            logger.warning(
                "Rent roll building %r: number_tenants_in_building=%s but %s unit rows — coercing count.",
                bname,
                declared,
                n_units,
            )
            building["number_tenants_in_building"] = n_units

        for j, unit in enumerate(urows):
            if not isinstance(unit, dict):
                continue

            if _unit_is_vacant(unit):
                _clear_rent_fields_for_vacant_unit(unit)
                _deduce_lease_remaining_years(unit)
                continue

            m = _to_float(unit.get("monthly_rent_usd"))
            a = _to_float(unit.get("annual_rent_usd"))
            if m is not None and m > 0:
                new_a = round(12.0 * m, 2)
                unit["annual_rent_usd"] = new_a
                a = new_a
            elif a is not None and a > 0 and (m is None or m <= 0):
                unit["monthly_rent_usd"] = round(a / 12.0, 2)

            sf = _to_float(unit.get("unit_size_sf"))
            a = _to_float(unit.get("annual_rent_usd"))
            if sf is not None and sf > 0 and a is not None and a > 0:
                unit["rent_per_sf_yearly"] = round(a / sf, 2)

            _deduce_lease_remaining_years(unit)


# ---------------------------------------------------------------------------
# Metadata ↔ rent roll / financials
# ---------------------------------------------------------------------------


def _first_offer_list(meta: dict[str, Any]) -> list[dict[str, Any]]:
    raw = meta.get("asset")
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _first_asking_price_usd(meta: dict[str, Any]) -> float | None:
    for offer in _first_offer_list(meta):
        if offer.get("is_unpriced") is True:
            continue
        p = _to_float(offer.get("asking_price"))
        if p is not None and p > 0:
            return p
    return None


def _sync_metadata_from_roll_in_place(meta: dict[str, Any], rent_roll: dict[str, Any]) -> None:
    """Fill summary GLA / occupancy from rent roll when missing."""
    offers = _first_offer_list(meta)
    if not offers:
        return

    roll_sf = _sum_unit_sf_from_roll(rent_roll)
    occ = _occupancy_from_roll(rent_roll)

    primary = offers[0]
    if roll_sf > 0 and _is_blank(primary.get("offer_rentable_square_feet")):
        primary["offer_rentable_square_feet"] = round(roll_sf, 2)
        logger.info("Filled metadata offer_rentable_square_feet from rent roll: %s", roll_sf)

    if occ is not None and primary.get("occupancy_percentage") is None:
        primary["occupancy_percentage"] = occ
        logger.info("Filled metadata occupancy_percentage from rent roll: %s", occ)

    if len(offers) == 1 and isinstance(rent_roll.get("rows"), list):
        n_b = len([b for b in rent_roll["rows"] if isinstance(b, dict)])
        if n_b > 0 and _is_blank(primary.get("buildings_number")):
            primary["buildings_number"] = n_b


# ---------------------------------------------------------------------------
# Standard financial statement (non-hotel)
# ---------------------------------------------------------------------------


def _is_noi_only_financial_cycle(y: dict[str, Any]) -> bool:
    """
    True when ``net_operating_income`` is set but no other income-statement or
    opex fields are populated (all other tracked keys are None / missing).
    """
    if _to_float(y.get("net_operating_income")) is None:
        return False
    for k in _FIN_NOI_ONLY_SENTINEL_KEYS:
        if y.get(k) is not None:
            return False
    return True


def _apply_noi_only_financial_stub(y: dict[str, Any]) -> None:
    """
    When only NOI exists, set gross rent (GPR) and income subtotals to NOI and
    zero out OpEx so we do not infer negative ``total_operating_expenses`` /
    ``other_operating_expenses``.
    """
    noi_v = _to_float(y.get("net_operating_income"))
    if noi_v is None:
        return
    noi_v = round(noi_v, 2)
    y["gross_potential_rent"] = noi_v
    y["vacancy_loss"] = 0.0
    y["gross_scheduled_income"] = noi_v
    y["effective_gross_income"] = noi_v
    y["total_operating_expenses"] = 0.0
    y["other_operating_expenses"] = 0.0
    logger.info(
        "Sparse financial cycle (%r): only NOI — set GPR/GSI/EGI to NOI and OpEx to 0.",
        y.get("financial_year"),
    )


def _warn_financial_cycle_gaps(y: dict[str, Any]) -> None:
    """
    Log when gross revenue → EGI (via vacancy) or EGI → NOI (via total OpEx)
    identities do not hold, or when OpEx line items + ``other_operating_expenses``
    do not roll up to ``total_operating_expenses``.
    """
    fy = y.get("financial_year")
    gpr = _to_float(y.get("gross_potential_rent"))
    er = _to_float(y.get("expense_reimbursements"))
    oi = _to_float(y.get("other_income"))
    gsi = _to_float(y.get("gross_scheduled_income"))
    if gpr is not None and gsi is not None:
        er_adj = er if er is not None else 0.0
        oi_adj = oi if oi is not None else 0.0
        expected_gsi = gpr + er_adj + oi_adj
        if abs(expected_gsi - gsi) > _financial_amount_tolerance(expected_gsi):
            logger.warning(
                "Gross revenue bridge gap for %s: GPR+reimb+other_income ~= %.2f vs gross_scheduled_income=%s",
                fy,
                expected_gsi,
                gsi,
            )

    vac = _to_float(y.get("vacancy_loss"))
    egi = _to_float(y.get("effective_gross_income"))
    if gsi is not None and egi is not None:
        vac_adj = vac if vac is not None else 0.0
        expected_egi = gsi - vac_adj
        if abs(expected_egi - egi) > _financial_amount_tolerance(expected_egi):
            logger.warning(
                "Gross vs net revenue gap (vacancy) for %s: GSI−vacancy ~= %.2f vs effective_gross_income=%.2f",
                fy,
                expected_egi,
                egi,
            )

    opex = _to_float(y.get("total_operating_expenses"))
    noi = _to_float(y.get("net_operating_income"))
    if egi is not None and opex is not None and noi is not None:
        expected_noi = egi - opex
        if abs(expected_noi - noi) > _financial_amount_tolerance(expected_noi):
            logger.warning(
                "NOI bridge gap for %s: EGI−total_operating_expenses ~= %.2f vs net_operating_income=%.2f "
                "(verify OpEx incl. other_operating_expenses)",
                fy,
                expected_noi,
                noi,
            )

    if opex is not None:
        known = 0.0
        for k in _STANDARD_OPEX_KEYS:
            v = _to_float(y.get(k))
            if v is not None:
                known += v
        other = _to_float(y.get("other_operating_expenses"))
        other_adj = other if other is not None else 0.0
        rolled = known + other_adj
        if abs(rolled - opex) > _financial_amount_tolerance(opex):
            logger.warning(
                "OpEx roll-up gap for %s: major lines + other_operating_expenses ~= %.2f vs total_operating_expenses=%.2f",
                fy,
                rolled,
                opex,
            )


def _apply_cap_rate_derived_fields_and_reconcile_noi(y: dict[str, Any], price: float | None) -> None:
    """Derive cap from NOI/price or NOI from cap×price; optionally align NOI to EGI−OpEx."""
    cap = y.get("cap_rate")
    cap_f = _cap_rate_as_fraction(cap)
    noi = _to_float(y.get("net_operating_income"))

    if price is not None and price > 0:
        if noi is not None and noi > 0 and cap_f is None:
            frac = noi / price
            y["cap_rate"] = _cap_rate_to_storage_percent_points(frac)
            logger.info("Derived cap_rate from NOI/price for year %s", y.get("financial_year"))
        elif cap_f is not None and noi is None:
            y["net_operating_income"] = round(price * cap_f, 2)
            logger.info("Derived net_operating_income from price×cap_rate for year %s", y.get("financial_year"))
        elif cap_f is not None and noi is not None and noi > 0:
            implied = noi / cap_f
            if implied > 0 and abs(implied - price) / price > 0.15:
                logger.debug(
                    "Implied value from NOI/cap (%.0f) differs from asking (%.0f); leaving asking_price unchanged.",
                    implied,
                    price,
                )

    egi = _to_float(y.get("effective_gross_income"))
    opex = _to_float(y.get("total_operating_expenses"))
    noi = _to_float(y.get("net_operating_income"))
    if (
        _to_float(y.get("cap_rate")) is None
        and egi is not None
        and opex is not None
        and noi is not None
    ):
        expected = egi - opex
        if abs(noi - expected) > _financial_amount_tolerance(expected):
            prev_noi = noi
            y["net_operating_income"] = round(expected, 2)
            logger.warning(
                "Adjusted net_operating_income to match EGI−OpEx for %s (was %s, now %s)",
                y.get("financial_year"),
                prev_noi,
                y["net_operating_income"],
            )


def _year_token_matches_current(financial_year: Any) -> bool:
    if financial_year is None:
        return False
    y = str(financial_year).strip()
    m = re.search(r"(20\d{2})", y)
    if not m:
        return False
    try:
        return int(m.group(1)) == datetime.now().year
    except ValueError:
        return False


def _pick_cycle_index_for_rent_proxy(cycles: list[dict[str, Any]]) -> int:
    """Prefer a row whose label looks like the calendar year; else first row."""
    for idx, row in enumerate(cycles):
        if isinstance(row, dict) and _year_token_matches_current(row.get("financial_year")):
            return idx
    return 0


def _correct_standard_financial_in_place(
    financial: dict[str, Any],
    meta: dict[str, Any],
    rent_roll: dict[str, Any],
) -> None:
    """
    Align income statement lines and NOI / cap / asking price where fields are missing.

    Uses rent-roll sum of ``annual_rent_usd`` as a proxy for GPR when GPR is empty
    (typically the in-place rent roll matches the first / current operating year).

    When a cycle has **only** ``net_operating_income`` populated among income/opex
    lines, sets GPR/GSI/EGI to that NOI and zeros OpEx (avoids negative inferred
    ``other_operating_expenses``). After fills, logs gaps for GPR→GSI→EGI→NOI and
    OpEx roll-up vs ``other_operating_expenses``.
    """
    cycles = financial.get("financial_cycles")
    if not isinstance(cycles, list) or not cycles:
        return

    price = _first_asking_price_usd(meta)
    rent_roll_gpr_proxy = _sum_annual_rent_from_roll(rent_roll)
    gpr_fill_idx = _pick_cycle_index_for_rent_proxy([c for c in cycles if isinstance(c, dict)])

    for idx, raw in enumerate(cycles):
        if not isinstance(raw, dict):
            continue
        y = raw

        if _is_noi_only_financial_cycle(y):
            _apply_noi_only_financial_stub(y)
            _apply_cap_rate_derived_fields_and_reconcile_noi(y, price)
            _warn_financial_cycle_gaps(y)
            continue

        # 1) GPR from rent roll when missing for the preferred (current / first) cycle only.
        if (
            idx == gpr_fill_idx
            and _to_float(y.get("gross_potential_rent")) is None
            and rent_roll_gpr_proxy > 0
        ):
            y["gross_potential_rent"] = round(rent_roll_gpr_proxy, 2)
            logger.info("Filled gross_potential_rent from rent roll for cycle %s", y.get("financial_year"))

        gpr = _to_float(y.get("gross_potential_rent")) or 0.0
        er = _to_float(y.get("expense_reimbursements")) or 0.0
        oi = _to_float(y.get("other_income")) or 0.0

        if _to_float(y.get("gross_scheduled_income")) is None:
            y["gross_scheduled_income"] = round(gpr + er + oi, 2)

        gsi = _to_float(y.get("gross_scheduled_income")) or 0.0
        vac = _to_float(y.get("vacancy_loss")) or 0.0

        if _to_float(y.get("effective_gross_income")) is None:
            y["effective_gross_income"] = round(gsi - vac, 2)

        egi = _to_float(y.get("effective_gross_income"))
        noi = _to_float(y.get("net_operating_income"))
        opex = _to_float(y.get("total_operating_expenses"))

        # 2) Derive total opex from EGI − NOI when opex missing.
        if opex is None and egi is not None and noi is not None:
            y["total_operating_expenses"] = round(egi - noi, 2)
            opex = _to_float(y.get("total_operating_expenses"))

        # 3) Split opex into line items vs other_operating_expenses.
        if opex is not None:
            known = 0.0
            for k in _STANDARD_OPEX_KEYS:
                v = _to_float(y.get(k))
                if v is not None:
                    known += v
            diff = opex - known
            if abs(diff) > 1.0:
                other = _to_float(y.get("other_operating_expenses")) or 0.0
                if other == 0.0:
                    y["other_operating_expenses"] = round(diff, 2)
                    logger.info(
                        "Allocated other_operating_expenses=%s to match total_operating_expenses",
                        y["other_operating_expenses"],
                    )

        # Refresh after possible fills
        egi = _to_float(y.get("effective_gross_income"))
        opex = _to_float(y.get("total_operating_expenses"))
        noi = _to_float(y.get("net_operating_income"))

        # 4) NOI identity: EGI − opex when NOI missing.
        if noi is None and egi is not None and opex is not None:
            y["net_operating_income"] = round(egi - opex, 2)
            noi = _to_float(y.get("net_operating_income"))

        _apply_cap_rate_derived_fields_and_reconcile_noi(y, price)
        _warn_financial_cycle_gaps(y)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def post_process_llm_values(text_llm_by_schema: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize extraction dicts **in-place** (and return the same dict).

    For non-hotel deals:
      - rent roll: tenant counts, monthly/annual rent, $/SF (cleared for vacant), lease years from end date;
      - standard financials: income subtotals, opex roll-up, NOI/cap coherence with asking price,
        NOI-only sparse cycles, and logged checks for GPR→GSI→EGI→NOI / OpEx roll-up gaps;
      - metadata: GLA and occupancy from rent roll when missing.
    """
    if not text_llm_by_schema:
        return text_llm_by_schema

    meta = text_llm_by_schema.get("metadata_from_text")
    meta = meta if isinstance(meta, dict) else {}
    hotel = _is_hotel_metadata(meta)

    if not hotel:
        rr = text_llm_by_schema.get("rent_roll_report")
        if isinstance(rr, dict):
            _correct_rent_roll_in_place(rr)
            text_llm_by_schema["rent_roll_report"] = rr
            _sync_metadata_from_roll_in_place(meta, rr)
            text_llm_by_schema["metadata_from_text"] = meta

    fin = text_llm_by_schema.get("financial_statement")
    if not hotel and isinstance(fin, dict):
        rr2 = text_llm_by_schema.get("rent_roll_report")
        rr2 = rr2 if isinstance(rr2, dict) else {}
        _correct_standard_financial_in_place(fin, meta, rr2)
        text_llm_by_schema["financial_statement"] = fin

    return text_llm_by_schema
