"""Normalize e-mail fields from inbound gateways (SendGrid ``From`` can be ``Name <addr>``)."""

from email.utils import parseaddr


def normalize_email_address(field: str | None) -> str | None:
    """
    Return bare ``user@domain`` from ``Name <user@domain>``, ``<user@domain>``, or a plain address.

    Uses :func:`email.utils.parseaddr` (RFC 5322–aware).
    """
    if not (field or "").strip():
        return None
    _, addr = parseaddr(field.strip())
    cleaned = addr.strip() if addr else ""
    return cleaned or None
