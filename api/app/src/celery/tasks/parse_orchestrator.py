"""
Two-tier PDF parse orchestrator.

Tier 1 — Fast track: PyMuPDF + Camelot on financial-looking pages; CRE metadata via
         LangChain/Gemini using :class:`PdfParseGptBridge` (same patterns as GptGetter, no DB).
Tier 2 — Vision fallback: pdf2image + Gemini multimodal via ``PdfParseGptBridge.extract_table_from_page_image``.
"""
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
from src.schemas.parse_pipeline import MetadataFromText, metadata_to_flat_dict

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

    # --- Output shaping --------------------------------------------------
    @staticmethod
    def build_email_extractions(
        tier: str,
        stats: dict[str, Any],
        meta: Optional[MetadataFromText],
        camelot: list[dict[str, Any]],
        vision: list[dict[str, Any]],
        google_configured: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "parse_tier": tier,
            "pages": str(stats.get("page_count", "")),
            "chars_extracted": str(stats.get("char_count", "")),
            "camelot_tables": len(camelot),
            "vision_pages": len(vision),
        }
        if meta:
            out.update(metadata_to_flat_dict(meta))
        if vision:
            first = vision[0].get("vision") or {}
            out["vision_page_kind"] = first.get("page_kind", "")
            out["vision_sample_columns"] = ", ".join(
                (first.get("columns") or [])[:8]
            )
        elif camelot and not vision:
            out["notes"] = "Tables extracted locally (Camelot / PyMuPDF path)."
        if not meta and not vision and not camelot and not google_configured:
            out["notes"] = (
                "Limited extraction — set GOOGLE_API_KEY for LLM metadata / vision."
            )
        return out

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

        full_text, page_texts, stats = self.extract_text_stats(path)
        native = self.is_likely_native_pdf(full_text, stats)

        tier = "fast_track"
        camelot_tables: list[dict[str, Any]] = []
        metadata_llm: Optional[MetadataFromText] = None
        vision_results: list[dict[str, Any]] = []
        errors: list[str] = []

        metadata_llm = self._llm.extract_metadata_from_pdf_text(full_text)

        if native:
            camelot_tables = self.run_camelot_financial_pass(path, page_texts)
            coherent = self.tables_look_coherent(camelot_tables)
            if not coherent:
                tier = "hybrid"
                errors.append("camelot_incoherent_or_empty")
                vision_results = self.vision_fallback_pages(
                    path, native=native, pages=page_texts, camelot_ok=False
                )
        else:
            tier = "vision_fallback"
            errors.append("low_text_native_pdf")
            vision_results = self.vision_fallback_pages(
                path, native=False, pages=page_texts, camelot_ok=False
            )
            if not vision_results and self._ctx.google_api_key:
                errors.append("vision_failed_or_no_pdf2image")

        google_on = bool(self._ctx.google_api_key)
        mock_extractions = self.build_email_extractions(
            tier, stats, metadata_llm, camelot_tables, vision_results, google_on
        )

        return {
            "status": "completed",
            "parser": "orchestrator_v1",
            "document_filename": path.name,
            "tier": tier,
            "mock_extractions": mock_extractions,
            "pipeline": {
                "stats": stats,
                "native_pdf_likely": native,
                "camelot_tables": camelot_tables,
                "vision_results": vision_results,
                "metadata_llm": metadata_llm.model_dump() if metadata_llm else None,
                "errors": errors,
            },
        }

if __name__ == "__main__":  # pragma: no cover
    p = Path("test.pdf")
