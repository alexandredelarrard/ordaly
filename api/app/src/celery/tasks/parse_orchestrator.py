"""
Two-tier PDF parse orchestrator.

Tier 1 — Fast track: PyMuPDF + Camelot on financial-looking pages; CRE metadata via
         LangChain/Gemini using :class:`PdfParseGptBridge` (same patterns as GptGetter, no DB).
Tier 2 — Vision fallback: pdf2image + Gemini multimodal via ``PdfParseGptBridge.extract_table_from_page_image``.
"""
# import os 
# os.chdir("C:\\Users\\alarr\\Documents\\repos\\ordaly\\api\\app")

from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Any, Optional

import pymupdf

from omegaconf import DictConfig

from src.constants import parse_pipeline as PP
from src.context import AppContext
from src.gpt_extraction.pdf_parse_gpt_bridge import PdfParseGptBridge
from src.utils.text_llm_excel import save_parse_excel_export

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
    "t-12",
    "trailing",
)


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

    @staticmethod
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

    # --- Tier 1: Camelot -------------------------------------------------
    def _camelot_read_page(self, path: Path, pages_1based: int) -> list[dict[str, Any]]:
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
        self, path: Path, pages: list[str]
    ) -> list[dict[str, Any]]:
        indices = self.select_financial_page_indices(pages)
        all_rows: list[dict[str, Any]] = []
        for p in indices:
            all_rows.extend(self._camelot_read_page(path, p))
        return all_rows

    @staticmethod
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

    # --- Tier 2: images + vision LLM ------------------------------------
    def render_page_png(
        self, path: Path, page_1based: int
    ) -> Optional[bytes]:
        try:
            from pdf2image import convert_from_path  # type: ignore
        except ImportError:
            logger.warning("pdf2image not installed — cannot run vision fallback.")
            return None
        try:
            images = convert_from_path(
                str(path),
                first_page=page_1based,
                last_page=page_1based,
                dpi=PP.PDF2IMAGE_DPI,
            )
            if not images:
                return None
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            return buf.getvalue()
        except Exception as exc:
            logger.warning("pdf2image page %s: %s", page_1based, exc)
            return None

    def _choose_vision_pro(self, png_len: int) -> bool:
        return png_len >= PP.VISION_PRO_IMAGE_BYTES_THRESHOLD

    def vision_fallback_pages(
        self,
        path: Path,
        *,
        native: bool,
        pages: list[str],
        camelot_ok: bool,
    ) -> list[dict[str, Any]]:
        if not self._ctx.google_api_key:
            return []

        n = len(pages)
        targets: list[int] = []
        if not native:
            targets = list(range(1, min(n, PP.MAX_VISION_PAGES_SCANNED_PDF) + 1))
        elif not camelot_ok:
            fin = self.select_financial_page_indices(pages)
            targets = fin[: PP.MAX_VISION_PAGES_TABLE_RETRY] or [1]

        results: list[dict[str, Any]] = []
        for p in targets:
            png = self.render_page_png(path, p)
            if not png:
                continue
            label = f"page={p} scanned={not native}"
            use_pro = self._choose_vision_pro(len(png))
            vt = self._llm.extract_table_from_page_image(
                png, label, use_pro=use_pro
            )
            if vt:
                results.append(
                    {
                        "page": p,
                        "vision": vt.model_dump(),
                        "model": (
                            self._ctx.gemini_model_pro
                            if use_pro
                            else self._ctx.gemini_model_fast
                        ),
                    }
                )
        return results

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

        #first step is to extract the metadata from the text and infos from camelot and pass to LLM
        full_text, page_texts, stats = self.extract_text_stats(path)
        native = self.is_likely_native_pdf(full_text, stats)
        camelot_tables = self.run_camelot_financial_pass(path, page_texts)
        
        if native:
            coherent = self.tables_look_coherent(camelot_tables)
            if not coherent:
                tier = "hybrid"
                errors.append("camelot_incoherent_or_empty")
                vision_results = self.vision_fallback_pages(
                    path, native=native, pages=page_texts, camelot_ok=False
                )
                camelot_tables = [result["vision"] for result in vision_results]
        else:
            tier = "vision_fallback"
            errors.append("low_text_native_pdf")
            vision_results = self.vision_fallback_pages(
                path, native=False, pages=page_texts, camelot_ok=False
            )
            if not vision_results and self._ctx.google_api_key:
                errors.append("vision_failed_or_no_pdf2image")
            camelot_tables = [result["vision"] for result in vision_results]

        # create aggregated information from LLM
        text_llm_by_schema = self._llm.extract_metadata_from_pdf_text(
            full_text, camelot_tables
        )

        if "type_of_sale" in text_llm_by_schema.get("metadata_from_text", {}):
            type_of_sale = text_llm_by_schema.get("metadata_from_text").get("type_of_sale")
            if type_of_sale in ["auction", "auctions", "auction sale"]:
                _, text_llm_by_schema['auction_information'] = self._llm.run_one_sync("auction_information", full_text, 
                camelot_tables)
                
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
    path = Path("test.pdf")
    from src.context import config, context

    self = PdfParseOrchestrator(context, config)
    self._llm = PdfParseGptBridge(context, config)
    self._llm.api_key = "AIzaSyBecWM-RogiYRAeE1mQ1El1b4JYXjctyh4"