import email
import inspect
import json
import os
import re
from email import policy
from pathlib import Path
from typing import List, Tuple
from uuid import uuid4

import python_multipart

from fastapi import HTTPException, Request, status
from starlette.datastructures import UploadFile

python_multipart.multipart.MULTIPART_MAX_PART_SIZE = 100 * 1024 * 1024

from src.utils.atomic_io import write_bytes_atomically_and_sync
from src.utils.email_address import normalize_email_address
from src.utils.multipart import parse_multipart_form

ATTACHMENT_FIELD = re.compile(r"^attachment(\d+)$", re.IGNORECASE)

TEXT_FORM_KEYS = {
    "headers",
    "dkim",
    "content-ids",
    "to",
    "text",
    "html",
    "from",
    "sender_ip",
    "envelope",
    "attachments",
    "subject",
    "charsets",
    "spam_report",
    "spam_score",
    "attachment-info",
    "spf",
    "email",
}


def _attachment_sort_key(item: Tuple[str, object]) -> Tuple[int, int, str]:
    k, _ = item
    m = ATTACHMENT_FIELD.match(k)
    if m:
        return (0, int(m.group(1)), k)
    return (1, 0, k)


def _is_pdf(filename: str, meta: dict) -> bool:
    fn = (filename or "").lower()
    if fn.endswith(".pdf"):
        return True
    ctype = (meta.get("type") or "").lower()
    return ctype == "application/pdf"


def _is_upload_part(value: object) -> bool:
    if isinstance(value, UploadFile):
        return True
    read = getattr(value, "read", None)
    return callable(read) and hasattr(value, "filename")


async def _read_upload_body(value: object) -> bytes:
    if isinstance(value, UploadFile):
        return await value.read()
    read = getattr(value, "read", None)
    if not callable(read):
        return b""
    try:
        chunk = read()
    except TypeError:
        chunk = read(1024 * 1024)
    if inspect.isawaitable(chunk):
        return await chunk  # type: ignore[union-attr]
    if isinstance(chunk, (bytes, bytearray)):
        return bytes(chunk)
    return b""


def _meta_for_field(attach_info: dict, field_key: str) -> dict:
    raw = attach_info.get(field_key)
    if isinstance(raw, dict):
        return raw
    lk = field_key.lower()
    for ak, av in attach_info.items():
        if str(ak).lower() == lk and isinstance(av, dict):
            return av
    return {}


def _pdf_upload_candidates(form) -> List[Tuple[str, object]]:
    seen: set[int] = set()
    out: List[Tuple[str, object]] = []
    for key, value in form.multi_items():
        if not _is_upload_part(value):
            continue
        uid = id(value)
        if uid in seen:
            continue
        seen.add(uid)
        if key.lower() in TEXT_FORM_KEYS:
            continue
        out.append((key, value))
    out.sort(key=_attachment_sort_key)
    return out


def _extract_pdfs_from_raw_mime(raw: object) -> List[Tuple[str, bytes]]:
    if raw is None:
        return []
    if isinstance(raw, bytes):
        msg = email.message_from_bytes(raw, policy=policy.default)
    elif isinstance(raw, str):
        msg = email.message_from_string(raw, policy=policy.default)
    else:
        return []

    found: List[Tuple[str, bytes]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        ctype = (part.get_content_type() or "").lower()
        filename = part.get_filename() or ""
        fn_l = filename.lower()
        if ctype != "application/pdf" and not fn_l.endswith(".pdf"):
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, (bytes, bytearray)):
            continue
        name = filename or "document.pdf"
        found.append((name, bytes(payload)))
    return found


async def extract_and_store_sendgrid_pdfs(
    request: Request, upload_dir: Path
) -> tuple[list[str], str]:
    """
    Parse SendGrid Inbound Parse POST, persist PDFs under ``upload_dir``.

    Returns ``(saved_absolute_paths, from_email)``.
    """
    upload_dir.mkdir(parents=True, exist_ok=True)
    form = await parse_multipart_form(request)

    from_email_raw = str(form.get("from") or "").strip()
    to_email = str(form.get("to") or "").strip()
    if not from_email_raw or not to_email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Champs « from » et « to » requis.",
        )

    from_email = normalize_email_address(from_email_raw) or from_email_raw
    attach_info: dict = {}
    raw_info = form.get("attachment-info")
    if isinstance(raw_info, str) and raw_info.strip():
        try:
            attach_info = json.loads(raw_info)
        except json.JSONDecodeError:
            attach_info = {}

    log = __import__("logging").getLogger("ordaly.inbound")
    log.info("Inbound email from=%s raw_from=%r", from_email, from_email_raw)

    upload_pairs = _pdf_upload_candidates(form)
    if not upload_pairs:
        form_keys = list(dict.fromkeys(k for k, _ in form.multi_items()))
        log.warning("No multipart file parts; form keys: %s", form_keys)

    saved_files: list[str] = []
    for key, upload in upload_pairs:
        meta = _meta_for_field(attach_info, key)
        filename = (
            getattr(upload, "filename", None)
            or meta.get("filename")
            or meta.get("name")
            or f"{key}.pdf"
        )
        filename = os.path.basename(str(filename))

        if not _is_pdf(filename, meta):
            continue

        if not filename.lower().endswith(".pdf"):
            filename = f"{Path(filename).stem}.pdf"

        body = await _read_upload_body(upload)
        if not body:
            continue

        dest = upload_dir / filename
        if dest.exists():
            dest = upload_dir / f"{Path(filename).stem}_{uuid4().hex[:8]}.pdf"

        write_bytes_atomically_and_sync(dest, body)
        saved_files.append(str(dest.resolve()))
        log.info("Stored PDF %s", dest)

    if not saved_files:
        raw_email = form.get("email")
        for name, payload in _extract_pdfs_from_raw_mime(raw_email):
            filename = os.path.basename(str(name)) or "document.pdf"
            if not filename.lower().endswith(".pdf"):
                filename = f"{Path(filename).stem}.pdf"
            dest = upload_dir / filename
            if dest.exists():
                dest = upload_dir / f"{Path(filename).stem}_{uuid4().hex[:8]}.pdf"
            write_bytes_atomically_and_sync(dest, payload)
            saved_files.append(str(dest.resolve()))
            log.info("Stored PDF from raw MIME %s", dest)

    if not saved_files:
        log.warning("No PDF saved from inbound message")

    return saved_files, from_email
