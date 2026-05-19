"""Camelot table extraction helpers for PDF financial pages."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.constants import parse_pipeline as PP

logger = logging.getLogger(__name__)

FINANCIAL_PAGE_KEYWORDS = (
    "rent roll",
    "rentroll",
    "financial summary",
    "statement of operations",
    "income statement",
    "balance sheet",
    "cash flow",
    "noi",
    "net operating income",
    "occupancy",
    "total revenue",
    "operating expenses",
    "rent",
    "t-12",
    "trailing",
)


def select_financial_page_indices(pages: list[str]) -> list[int]:
    selected: list[int] = []
    for i, txt in enumerate(pages):
        low = txt.lower()
        if any(k in low for k in FINANCIAL_PAGE_KEYWORDS):
            selected.append(i + 1)
        if len(selected) >= PP.MAX_CAMELOT_PAGES_PER_DOC:
            break
    if not selected and pages:
        selected = [1]
        if len(pages) > 1:
            selected.append(min(2, len(pages)))
    return selected[: PP.MAX_CAMELOT_PAGES_PER_DOC]


def camelot_read_page(path: Path, pages_1based: int) -> list[dict[str, Any]]:
    try:
        import camelot  # type: ignore
    except ImportError:
        logger.warning(
            "Camelot not installed — skipping lattice/stream tables "
            "(check worker image: pip install camelot-py[cv] + opencv-python-headless)."
        )
        return []

    out: list[dict[str, Any]] = []
    for flavor in ("lattice", "stream"):
        try:
            tables = camelot.read_pdf(
                str(path), pages=str(pages_1based), flavor=flavor
            )
            for t in tables:
                df = t.df
                out.append(
                    {
                        "page": pages_1based,
                        "flavor": flavor,
                        "accuracy": getattr(t, "accuracy", None),
                        "shape": list(df.shape),
                        "preview": df.head(12).to_dict(orient="records"),
                    }
                )
        except Exception as exc:
            logger.debug("Camelot %s page %s: %s", flavor, pages_1based, exc)
    return out


def run_camelot_financial_pass(
    path: Path, pages: list[str]
) -> list[dict[str, Any]]:
    indices = select_financial_page_indices(pages)
    all_rows: list[dict[str, Any]] = []
    for p in indices:
        all_rows.extend(camelot_read_page(path, p))
    return all_rows


def tables_look_coherent(camelot_tables: list[dict[str, Any]]) -> bool:
    if not camelot_tables:
        return False
    total_rows = 0
    for t in camelot_tables:
        shape = t.get("shape") or [0, 0]
        if len(shape) >= 1:
            total_rows += int(shape[0])
    if total_rows < PP.MIN_TABLE_ROWS_MEANINGFUL:
        return False
    if total_rows > PP.MAX_TABLE_ROWS_SANE:
        return False
    return True
