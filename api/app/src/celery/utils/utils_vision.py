"""PDF page rendering and vision (image → table) fallback helpers."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from src.constants import parse_pipeline as PP
from src.context import AppContext
from src.celery.utils import utils_camelot

if TYPE_CHECKING:
    from src.gpt_extraction.pdf_parse_gpt_bridge import PdfParseGptBridge

logger = logging.getLogger(__name__)


def render_page_png(path: Path, page_1based: int) -> Optional[bytes]:
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


def choose_vision_pro(png_len: int) -> bool:
    return png_len >= PP.VISION_PRO_IMAGE_BYTES_THRESHOLD


def vision_fallback_pages(
    path: Path,
    *,
    native: bool,
    pages: list[str],
    camelot_ok: bool,
    bridge: "PdfParseGptBridge",
    ctx: AppContext,
) -> list[dict[str, Any]]:
    if not ctx.google_api_key:
        return []

    n = len(pages)
    targets: list[int] = []
    if not native:
        targets = list(range(1, min(n, PP.MAX_VISION_PAGES_SCANNED_PDF) + 1))
    elif not camelot_ok:
        fin = utils_camelot.select_financial_page_indices(pages)
        targets = fin[: PP.MAX_VISION_PAGES_TABLE_RETRY] or [1]

    results: list[dict[str, Any]] = []
    for p in targets:
        png = render_page_png(path, p)
        if not png:
            continue
        label = f"page={p} scanned={not native}"
        use_pro = choose_vision_pro(len(png))
        vt = bridge.extract_table_from_page_image(png, label, use_pro=use_pro)
        if vt:
            results.append(
                {
                    "page": p,
                    "vision": vt.model_dump(),
                    "model": (
                        ctx.gemini_model_pro
                        if use_pro
                        else ctx.gemini_model_fast
                    ),
                }
            )
    return results
