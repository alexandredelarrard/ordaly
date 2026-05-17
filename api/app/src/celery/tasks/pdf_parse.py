import logging
from pathlib import Path
from typing import Any

from src.celery.celery_app import celery
from src.constants.limits import PDF_FILE_READY_POLL_SEC, PDF_FILE_READY_TIMEOUT_SEC
from src.utils.file_ready import wait_until_file_ready
from src.utils.outbound_mail import send_valartic_completion_email

logger = logging.getLogger(__name__)


def _mock_parse_pdf(path: Path) -> dict[str, Any]:
    """Fake structured output until the agentic parser is implemented."""
    return {
        "status": "completed",
        "parser": "mock_v1",
        "document_filename": path.name,
        "mock_extractions": {
            "property_or_borrower": "Valartic Sample Property Holdings LLC",
            "asset_type": "Class B multifamily",
            "market_msa": "Austin — TX",
            "loan_amount_hint": "$18,750,000",
            "ltv_estimate": "63%",
            "term_years": "7 (fixed)",
            "notes": (
                "Sortie de démonstration : branchez ici la sortie JSON du parseur agentique "
                "pour alimenter le tableau de l’e-mail Valartic."
            ),
        },
    }


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

    parse_result = _mock_parse_pdf(path)

    mail_info = send_valartic_completion_email(
        sender_raw=sender_email,
        task_id=task_id,
        document_name=path.name,
        parse_result=parse_result,
    )

    return {
        "status": parse_result["status"],
        "task_id": task_id,
        "file_path": file_path,
        "parse_result": parse_result,
        "completion_email": mail_info,
    }
