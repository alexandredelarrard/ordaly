import logging
from pathlib import Path
from typing import Any

from src.celery.celery_app import celery
from src.context import context, config
from src.constants.limits import PDF_FILE_READY_POLL_SEC, PDF_FILE_READY_TIMEOUT_SEC
from src.utils.file_ready import wait_until_file_ready
from src.services.outbound_mail import send_valartic_completion_email
from src.celery.tasks.parse_orchestrator import PdfParseOrchestrator

logger = logging.getLogger(__name__)
parse_pdf_orchestrator = PdfParseOrchestrator(context, config)

@celery.task(bind=True, name="pdf.parse_document")
def parse_pdf_document(self, file_path: str, sender_email: str = "") -> dict[str, Any]:
    """
    Parse PDF (stub), then send Valartic HTML completion e-mail to the inbound sender.

    Waits until the PDF is visible and non-empty — the API may still be flushing to the
    shared volume when this task starts.
    """
    task_id = self.request.id
    path = Path(file_path)

    if not wait_until_file_ready(
        path,
        timeout_sec=PDF_FILE_READY_TIMEOUT_SEC,
        poll_sec=PDF_FILE_READY_POLL_SEC,
    ):
        logger.error(
            "parse_pdf_document: file not ready after %.1fs task=%s path=%s",
            PDF_FILE_READY_TIMEOUT_SEC,
            task_id,
            file_path,
        )
        return {
            "status": "error",
            "task_id": task_id,
            "detail": f"file not ready or missing: {file_path}",
        }

    logger.info(
        "parse_pdf_document task=%s path=%s sender=%s",
        task_id,
        file_path,
        sender_email,
    )

    parse_result = parse_pdf_orchestrator.run(path)

    mail_info = send_valartic_completion_email(
        sender_raw=sender_email,
        task_id=task_id,
        document_name=path.name,
        parse_result=parse_result,
        source_pdf_path=str(path.resolve()),
    )

    return {
        "status": parse_result["status"],
        "task_id": task_id,
        "file_path": file_path,
        "parse_result": parse_result,
        "completion_email": mail_info,
    }
