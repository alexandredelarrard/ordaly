import os 
os.chdir("C:\\Users\\alarr\\Documents\\repos\\ordaly\\api\\app")

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional
import pymupdf
from omegaconf import DictConfig

from src.celery.utils import utils_camelot, utils_vision
from src.celery.utils.post_process_llm_values import post_process_llm_values
from src.constants import parse_pipeline as PP
from src.context import AppContext
from src.gpt_extraction.pdf_parse_gpt_bridge import PdfParseGptBridge
from src.utils.text_llm_excel import save_parse_excel_export

logger = logging.getLogger(__name__)


def _page_texts(doc: pymupdf.Document) -> list[str]:
    return [(doc[i].get_text() or "").strip() for i in range(doc.page_count)]


class PdfParseOrchestrator:
    """
    Coordinates local PDF parsing (PyMuPDF, Camelot) and LLM steps (``PdfParseGptBridge``).
    """

    def __init__(self, context: AppContext, config: DictConfig):
        self._ctx = context
        self._config = config
        self._llm = PdfParseGptBridge(context, config)

    # --- Tier 1: PyMuPDF -------------------------------------------------
    def extract_text_stats(self, path: Path) -> tuple[str, list[str], dict[str, Any]]:
        doc = pymupdf.open(str(path))
        try:
            pages = _page_texts(doc)
            full = "\n\n".join(pages)
            non_ws = re.sub(r"\s+", "", full)
            alnum = sum(1 for c in non_ws if c.isalnum())
            ratio = (alnum / len(non_ws)) if non_ws else 0.0
            stats = {
                "page_count": doc.page_count,
                "char_count": len(full.strip()),
                "alnum_ratio": round(ratio, 3),
            }
            return full, pages, stats
        finally:
            doc.close()

    @staticmethod
    def is_likely_native_pdf(full_text: str, stats: dict[str, Any]) -> bool:
        if stats.get("char_count", 0) < PP.MIN_CHARS_NATIVE_LIKELY:
            return False
        if stats.get("alnum_ratio", 0) < PP.MIN_ALNUM_RATIO:
            return False
        return True

    # --- Public API ------------------------------------------------------
    def run(self, path: Path) -> dict[str, Any]:
        path = path.resolve()
        if not path.is_file():
            return {
                "status": "error",
                "parser": "orchestrator_v1",
                "document_filename": path.name,
                "detail": "file not found",
                "mock_extractions": {},
            }

        tier = "text_only"
        camelot_tables: list[dict[str, Any]] = []
        text_llm_by_schema: Optional[dict[str, Any]] = None
        vision_results: list[dict[str, Any]] = []
        errors: list[str] = []

        full_text, page_texts, stats = self.extract_text_stats(path)
        native = self.is_likely_native_pdf(full_text, stats)
        camelot_tables = utils_camelot.run_camelot_financial_pass(path, page_texts)

        if native:
            coherent = utils_camelot.tables_look_coherent(camelot_tables)
            if not coherent:
                tier = "hybrid"
                errors.append("camelot_incoherent_or_empty")
                vision_results = utils_vision.vision_fallback_pages(
                    path,
                    native=native,
                    pages=page_texts,
                    camelot_ok=False,
                    bridge=self._llm,
                    ctx=self._ctx,
                )
                camelot_tables = [result["vision"] for result in vision_results]
        else:
            tier = "vision_fallback"
            errors.append("low_text_native_pdf")
            vision_results = utils_vision.vision_fallback_pages(
                path,
                native=False,
                pages=page_texts,
                camelot_ok=False,
                bridge=self._llm,
                ctx=self._ctx,
            )
            if not vision_results and self._ctx.google_api_key:
                errors.append("vision_failed_or_no_pdf2image")
            camelot_tables = [result["vision"] for result in vision_results]

        text_llm_by_schema = self._llm.extract_metadata_from_pdf_text(
            full_text, camelot_tables
        )

        text_llm_by_schema = post_process_llm_values(text_llm_by_schema)

        if "type_of_sale" in text_llm_by_schema.get("metadata_from_text", {}):
            type_of_sale = text_llm_by_schema.get("metadata_from_text").get("type_of_sale")
            if type_of_sale in ["auction", "auctions", "auction sale"]:
                _, text_llm_by_schema["auction_information"] = self._llm.run_one_sync(
                    "auction_information", full_text, camelot_tables
                )

        excel_export_path = save_parse_excel_export(
            text_llm_by_schema=text_llm_by_schema,
            source_pdf_path=path,
        )

        return {
            "status": "completed",
            "parser": "orchestrator_v1",
            "document_filename": path.name,
            "tier": tier,
            "text_llm": text_llm_by_schema,
            "excel_export_path": str(excel_export_path)
            if excel_export_path
            else None,
            "metadata_llm": (text_llm_by_schema or {}).get("metadata_from_text"),
            "errors": errors,
            "native_pdf_likely": native,
            "camelot_tables": camelot_tables,
            "vision_results": vision_results,
        }


if __name__ == "__main__":  # pragma: no cover
    path = Path("test2.pdf")
    from src.context import config, context

    self = PdfParseOrchestrator(context, config)
    self._llm = PdfParseGptBridge(context, config)
    self._llm.api_key = "AIzaSyDkltMEkFNuJvjw6WxnkIA_jxKq4nhyktI"
