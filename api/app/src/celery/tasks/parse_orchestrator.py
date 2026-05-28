from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import pymupdf
from omegaconf import DictConfig

from src.gpt_extraction.pdf_parse_llm_graph import run_pdf_parse_llm_graph
from src.utils.pdf_mupdf import open_pdf as open_pdf_sanitized
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
    Coordinates local PDF parsing (PyMuPDF) and LLM steps (``PdfParseGptBridge``).
    """

    def __init__(self, context: AppContext, config: DictConfig):
        self._ctx = context
        self._config = config
        self._llm = PdfParseGptBridge(context, config)

    # --- Tier 1: PyMuPDF -------------------------------------------------
    def extract_text_stats(self, path: Path) -> tuple[str, list[str], dict[str, Any]]:
        doc = open_pdf_sanitized(path)
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
        text_llm_by_schema: Optional[dict[str, Any]] = None
        errors: list[str] = []

        # extract full text from pdf 
        full_text, pages, stats = self.extract_text_stats(path)
        native = self.is_likely_native_pdf(full_text, stats)

        # call the graph (per-page list; graph also accepts a single joined str)
        text_llm_by_schema = run_pdf_parse_llm_graph(self._llm, pages)
        text_llm_by_schema = post_process_llm_values(text_llm_by_schema)

        # save to excel 
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
            "native_pdf_likely": native
        }
