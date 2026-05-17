import logging
from pathlib import Path

from src.celery.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(bind=True, name="pdf.parse_document")
def parse_pdf_document(self, file_path: str, sender_email: str = "") -> dict:
    """
    Placeholder for agentic PDF extraction.

    Later: consistent structured extraction (LLM / tools) and DB persistence using
    ``src/sql_queries`` + ``src/utils/database``.
    """
    task_id = self.request.id
    path = Path(file_path)
    if not path.is_file():
        logger.error("parse_pdf_document missing file task=%s path=%s", task_id, file_path)
        return {"status": "error", "task_id": task_id, "detail": f"missing file {file_path}"}

    logger.info(
        "parse_pdf_document stub task=%s path=%s sender=%s",
        task_id,
        file_path,
        sender_email,
    )
    return {
        "status": "completed_stub",
        "task_id": task_id,
        "file_path": file_path,
        "detail": "Agentic parser not implemented yet",
    }
