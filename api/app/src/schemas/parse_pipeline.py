"""Pydantic schemas for LLM / vision extraction (Gemini structured JSON)."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class MetadataFromText(BaseModel):
    """Structured CRE-ish metadata from raw PDF text (fast tier — text-only LLM)."""

    property_or_borrower: Optional[str] = None
    asset_type: Optional[str] = None
    market_msa: Optional[str] = None
    loan_amount_hint: Optional[str] = None
    ltv_estimate: Optional[str] = None
    term_years: Optional[str] = None
    notes: Optional[str] = None


class VisionTableExtraction(BaseModel):
    """
    Table extracted from a page image (rent roll, financial summary, etc.).
    Strict shape for ``response_mime_type=application/json`` validation.
    """

    page_kind: str = Field(
        description="rent_roll | financial_summary | other",
    )
    title: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    confidence: str = Field(default="medium")
    raw_notes: str = ""


def metadata_to_flat_dict(m: MetadataFromText) -> dict[str, Any]:
    return {k: v for k, v in m.model_dump().items() if v is not None and str(v).strip()}
