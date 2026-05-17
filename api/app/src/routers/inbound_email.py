from pathlib import Path

from fastapi import APIRouter, Request, status
from src.schemas.inbound import InboundEmailAccepted
from src.services.inbound_email import process_inbound_email_and_queue

router = APIRouter(tags=["inbound-email"])


@router.post(
    "/v1/inbound-email",
    status_code=status.HTTP_200_OK,
    response_model=InboundEmailAccepted,
)
async def inbound_email_webhook(request: Request):
    """SendGrid Inbound Parse webhook — stores PDFs and queues async parsing."""
    saved, task_ids = await process_inbound_email_and_queue(request)
    return InboundEmailAccepted(
        status="received",
        message="PDFs stored; parse jobs queued for async processing",
        saved=[Path(p).name for p in saved],
        task_ids=task_ids,
    )
