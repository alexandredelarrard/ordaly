import inspect

from fastapi import Request

from src.constants.limits import MAX_FORM_FIELDS, MAX_FORM_FILES, MAX_FORM_PART_SIZE_BYTES


async def parse_multipart_form(request: Request):
    """Parse multipart with large parts (SendGrid PDFs)."""
    sig = inspect.signature(request.form)
    kwargs = {}
    if "max_part_size" in sig.parameters:
        kwargs["max_part_size"] = MAX_FORM_PART_SIZE_BYTES
    if "max_files" in sig.parameters:
        kwargs["max_files"] = MAX_FORM_FILES
    if "max_fields" in sig.parameters:
        kwargs["max_fields"] = MAX_FORM_FIELDS
    return await request.form(**kwargs)
