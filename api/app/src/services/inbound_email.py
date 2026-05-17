from src.context import context
from src.utils.pdf_storage import extract_and_store_sendgrid_pdfs


async def process_inbound_email_and_queue(request):
    """
    Store PDFs from SendGrid webhook and enqueue Celery parse tasks (stub worker for now).
    """
    saved, sender = await extract_and_store_sendgrid_pdfs(
        request, context.incoming_dir
    )
    task_ids: list[str] = []
    if saved:
        try:
            from src.celery.tasks.pdf_parse import parse_pdf_document

            for path in saved:
                async_result = parse_pdf_document.delay(path, sender)
                task_ids.append(async_result.id)
        except Exception as exc:  # pragma: no cover — broker misconfig
            context.log.exception("Celery enqueue failed: %s", exc)
    return saved, task_ids
