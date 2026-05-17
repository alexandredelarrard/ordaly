"""Multipart and payload limits (SendGrid ~30 MB total message guideline)."""

# Starlette default max_part_size is 1 MiB — too small for PDF attachments
MAX_FORM_PART_SIZE_BYTES = 32 * 1024 * 1024
MAX_FORM_FILES = 100
MAX_FORM_FIELDS = 2000

# Celery may read before the API container’s write is visible on a shared bind mount
PDF_FILE_READY_TIMEOUT_SEC = 120.0
PDF_FILE_READY_POLL_SEC = 0.2
