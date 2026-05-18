"""Thresholds for two-tier PDF parse (PyMuPDF + Camelot → optional Gemini vision)."""

# --- Fast-track (native PDF) heuristics ---
# Below this total character count, treat as scanned / empty and prefer vision path.
MIN_CHARS_NATIVE_LIKELY: int = 400
# Minimum alphanumeric ratio (0–1) on non-whitespace chars to trust extracted text.
MIN_ALNUM_RATIO: float = 0.45

# --- Camelot ---
MAX_CAMELOT_PAGES_PER_DOC: int = 12
MAX_TABLE_ROWS_SANE: int = 500
MIN_TABLE_ROWS_MEANINGFUL: int = 2

# --- Vision fallback (Gemini + pdf2image) ---
MAX_VISION_PAGES_SCANNED_PDF: int = 15
MAX_VISION_PAGES_TABLE_RETRY: int = 6
PDF2IMAGE_DPI: int = 160

# Large rendered image → use Pro model (env override)
VISION_PRO_IMAGE_BYTES_THRESHOLD: int = 2_200_000
