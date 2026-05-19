# import os 
# os.chdir("C:\\Users\\alarr\\Documents\\repos\\ordaly\\api\\app")

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import pymupdf
from omegaconf import DictConfig

from src.celery.tasks.pdf_parse_llm_graph import run_pdf_parse_llm_graph
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

    def image_handler(self, native: bool, camelot_tables: list[dict[str, Any]], page_texts: list[str], path: Path) -> list[dict[str, Any]]: 
        errors: list[str] = []
        vision_results: list[dict[str, Any]] = []
        tier: str = "text_only"

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

        return tier, camelot_tables


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

        # extract full text from pdf 
        full_text, page_texts, stats = self.extract_text_stats(path)
        native = self.is_likely_native_pdf(full_text, stats)
        camelot_tables = utils_camelot.run_camelot_financial_pass(path, page_texts)

        # if pages are pictures, will detect and scrap it 
        tier, camelot_tables = self.image_handler(native, camelot_tables, page_texts, path)

        # call the graph
        text_llm_by_schema = run_pdf_parse_llm_graph(self._llm, page_texts, camelot_tables)
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
            "native_pdf_likely": native,
            "camelot_tables": camelot_tables,
            "vision_results": vision_results,
        }


# if __name__ == "__main__":  # pragma: no cover
#     from src.context import config, context
#     from tqdm import tqdm

#     self =PdfParseOrchestrator(context, config)
#     self._llm.api_key = "AIzaSyCD0q1cBDdo_VY80IAUic4pefvjX2-IRsQ"
#     root = Path(r"C:\Users\alarr\Downloads")

#     results = {}

#     # run tests
#     paths = ["1e5f7a67-1067-4aa3-bd09-548f4977ea63.pdf",
#     "Hampton Inn Adel - Offering Memorandum.pdf",
#     "The Plaza - OM - Final 05 2026.pdf",
#     "67df0dbc-f538-4c86-a037-7ec1247c4df1.pdf",
#     "36644faf-99df-46b4-9d02-52aef897003c.pdf",
#     "2ac721ba-773b-450c-86f1-69329f4bddba.pdf",
#     "ff4518f0-4f7c-4f31-b9b2-7ae72a7a0223.pdf",
#     "ea4de6a5-870d-4955-874a-6bab83e29e7f.pdf",
#     "Dark Savers - Antioch, CA - OM (1).pdf",
#     "CBRE Hotels Offering Memorandum - HI Selinsgrove - April 2026.pdf"]

#     for path in tqdm(paths): 
#         path = root / Path(path)
#         full_text, page_texts, stats = self.extract_text_stats(path)
#         native = self.is_likely_native_pdf(full_text, stats)
#         camelot_tables = utils_camelot.run_camelot_financial_pass(path, page_texts)

#         text_llm_by_schema = run_pdf_parse_llm_graph(self._llm, page_texts, camelot_tables)
#         # text_llm_by_schema = post_process_llm_values(text_llm_by_schema)

#         # save to excel 
#         excel_export_path = save_parse_excel_export(
#             text_llm_by_schema=text_llm_by_schema,
#             source_pdf_path=path,
#         )

#         results[path.name] = text_llm_by_schema
