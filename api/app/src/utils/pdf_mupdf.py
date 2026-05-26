"""
PyMuPDF helpers for opening PDFs whose tagged-PDF / structure tree is invalid.

MuPDF may log ``format error: No common ancestor in structure tree`` and slow down
rendering when ``StructTreeRoot`` is broken. Clearing that catalog entry (in-memory
only) matches upstream guidance and keeps text extraction / rasterization working.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def open_pdf(path: str | Path) -> Any:
    """
    Open ``path`` with PyMuPDF and strip a broken structure tree root when present.

    Returns a live ``pymupdf.Document``; caller must ``close()`` it.
    """
    import pymupdf

    doc = pymupdf.open(str(path))
    _clear_struct_tree_root_if_present(doc)
    return doc


def _clear_struct_tree_root_if_present(doc: Any) -> None:
    try:
        cat = doc.pdf_catalog()
        if not isinstance(cat, int) or cat <= 0:
            return
        doc.xref_set_key(cat, "StructTreeRoot", "null")
    except Exception as exc:
        logger.debug("Could not null PDF StructTreeRoot (non-fatal): %s", exc)
