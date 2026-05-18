"""Send outbound e-mail via Twilio SendGrid (official Python SDK) after PDF processing."""

import logging
from typing import Any

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content, Email, Mail, To

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


def _mock_results_to_table_rows(mock: dict[str, Any]) -> str:
    rows: list[str] = []
    extractions = mock.get("mock_extractions") or {}
    for key, value in extractions.items():
        label = key.replace("_", " ").title()
        safe_val = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        rows.append(
            "<tr>"
            f'<td style="padding:10px 12px;border-bottom:1px solid #e4eaf0;color:#3d4f63;">{label}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e4eaf0;font-weight:600;color:#0f2744;">{safe_val}</td>'
            "</tr>"
        )
    if not rows:
        rows.append(
            '<tr><td colspan="2" style="padding:12px;color:#6b7c8f;">Aucun champ mock disponible.</td></tr>'
        )
    return "\n".join(rows)


def send_valartic_completion_email(
    *,
    sender_raw: str,
    task_id: str,
    document_name: str,
    parse_result: dict[str, Any],
) -> dict[str, Any]:
    """Send HTML completion e-mail; no API key → log only (dev/mock)."""

    api_key = _clean_sendgrid_api_key(context.sendgrid_api_key or "")
    from_email = (context.sendgrid_from_email or "").strip()

    to_email = normalize_email_address(sender_raw)
    if not to_email:
        logger.warning("No recipient address extracted from sender=%r", sender_raw)
        return {"sent": False, "reason": "no_recipient"}

    rows_html = _mock_results_to_table_rows(parse_result)
    html = render_valartic_completion_email(
        task_id=task_id,
        document_name=document_name,
        results_rows_html=rows_html,
    )
    subject = f"Valartic — Analyse terminée : {document_name}"

    if not api_key or not from_email:
        logger.info(
            "[mock e-mail] Would send to=%s subject=%r (set SENDGRID_API_KEY and SENDGRID_FROM_EMAIL)",
            to_email,
            subject,
        )
        return {"sent": False, "reason": "sendgrid_not_configured", "to": to_email}

    message = Mail(
        Email(from_email),
        To(to_email),
        subject,
        Content("text/html", html),
    )

    try:
        sg = SendGridAPIClient(api_key)
        # Only for EU data residency sub-users; global keys get 401 if this is set incorrectly.
        residency = (context.sendgrid_data_residency or "").strip().lower()
        if residency == "eu":
            sg.set_sendgrid_data_residency("eu")

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
            "Sent Valartic completion e-mail from=%s to=%s task=%s status=%s",
            from_email,
            to_email,
            task_id,
            status_code,
        )
        return {"sent": True, "to": to_email, "status_code": status_code}

    except Exception as exc:
        err_msg = getattr(exc, "message", None) or str(exc)
        logger.exception("Failed to send outbound e-mail: %s", err_msg)
        return {"sent": False, "reason": err_msg}
