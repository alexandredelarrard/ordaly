"""Send outbound e-mail via Twilio SendGrid (official Python SDK) after PDF processing."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment,
    Content,
    Disposition,
    Email,
    FileContent,
    FileName,
    FileType,
    Mail,
    To,
)

from src.context import context
from src.utils.email_address import normalize_email_address
from src.utils.email_template_valartic import render_valartic_completion_email

logger = logging.getLogger(__name__)


def _clean_sendgrid_api_key(raw: str) -> str:
    """Strip whitespace / CR / surrounding quotes (common in .env on Windows)."""
    key = (raw or "").strip()
    key = key.replace("\r", "").replace("\n", "")
    if len(key) >= 2 and key[0] == key[-1] and key[0] in '"\'':
        key = key[1:-1].strip()
    return key


def _make_sendgrid_client(api_key: str) -> SendGridAPIClient:
    sg = SendGridAPIClient(api_key)
    return sg


def _resolve_excel_path_for_attachment(
    parse_result: dict[str, Any],
    source_pdf_path: str | None,
) -> Path | None:
    """Prefer ``excel_export_path`` from the parser; else rebuild from ``text_llm`` + PDF path."""
    raw = parse_result.get("excel_export_path")
    if raw:
        p = Path(str(raw))
        if p.is_file():
            return p.resolve()
        logger.warning("excel_export_path not found on disk: %s", raw)

    if source_pdf_path and parse_result.get("text_llm"):
        try:
            from src.utils.text_llm_excel import save_parse_excel_export

            out = save_parse_excel_export(
                text_llm_by_schema=parse_result["text_llm"],
                source_pdf_path=Path(source_pdf_path).resolve(),
            )
            if out and Path(out).is_file():
                return Path(out).resolve()
        except Exception:
            logger.exception("Fallback Excel export for e-mail attachment failed")
    return None


def send_valartic_completion_email(
    *,
    sender_raw: str,
    task_id: str,
    document_name: str,
    parse_result: dict[str, Any],
    source_pdf_path: str | None = None,
) -> dict[str, Any]:
    """Send HTML completion e-mail with structured summary + Excel attachment when available."""

    api_key = _clean_sendgrid_api_key(context.sendgrid_api_key or "")
    from_email = (context.sendgrid_from_email or "").strip()

    to_email = normalize_email_address(sender_raw)
    if not to_email:
        logger.warning("No recipient address extracted from sender=%r", sender_raw)
        return {"sent": False, "reason": "no_recipient"}

    html = render_valartic_completion_email(
        task_id=task_id,
        document_name=document_name,
        parse_result=parse_result,
    )
    subject = f"Valartic — Analysis complete: {document_name}"

    resolved_excel = _resolve_excel_path_for_attachment(parse_result, source_pdf_path)
    excel_attached = False

    if not api_key or not from_email:
        raise ValueError("SENDGRID_API_KEY and SENDGRID_FROM_EMAIL are not configured")

    message = Mail(
        Email(from_email),
        To(to_email),
        subject,
        Content("text/html", html),
    )

    if resolved_excel:
        try:
            encoded = base64.b64encode(resolved_excel.read_bytes()).decode()
            attachment = Attachment(
                FileContent(encoded),
                FileName(resolved_excel.name),
                FileType(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                ),
                Disposition("attachment"),
            )
            message.add_attachment(attachment)
            excel_attached = True
        except OSError as exc:
            logger.error("Cannot read Excel for attachment: %s", exc)
        except Exception:
            logger.exception("Failed to attach Excel file")

    if not excel_attached:
        raise ValueError(
            "Valartic completion e-mail cannot be sent without Excel attachment task=%s" % task_id)

    try:
        sg = _make_sendgrid_client(api_key)
        response = sg.client.mail.send.post(request_body=message.get())
        status_code = getattr(response, "status_code", None)

        if status_code is not None and status_code >= 400:
            body = getattr(response, "body", b"") or b""
            logger.error(
                "SendGrid error status=%s body=%s",
                status_code,
                body[:500] if isinstance(body, (bytes, bytearray)) else body,
            )
            return {"sent": False, "reason": "sendgrid_error", "status": status_code}

        logger.info(
            "Sent Valartic completion e-mail from=%s to=%s task=%s status=%s excel=%s",
            from_email,
            to_email,
            task_id,
            status_code,
            resolved_excel.name if excel_attached else None,
        )
        return {
            "sent": True,
            "to": to_email,
            "status_code": status_code,
            "excel_attached": excel_attached,
            "excel_path": str(resolved_excel) if resolved_excel else None,
        }

    except Exception as exc:
        err_msg = getattr(exc, "message", None) or str(exc)
        logger.exception("Failed to send outbound e-mail: %s", err_msg)
        return {"sent": False, "reason": err_msg}
