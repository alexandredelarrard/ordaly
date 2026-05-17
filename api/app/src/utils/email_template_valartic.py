"""Load HTML e-mail body from the Valartic markdown design file (```html`` fence)."""

import html
from datetime import datetime, timezone
from pathlib import Path

_FENCE = "```html"


def load_valartic_completion_html_template() -> str:
    md_path = Path(__file__).resolve().parent.parent / "email_templates" / "valartic_completion_email.md"
    text = md_path.read_text(encoding="utf-8")
    start = text.find(_FENCE)
    if start == -1:
        raise ValueError("valartic_completion_email.md: missing ```html block")
    start += len(_FENCE)
    end = text.find("```", start)
    if end == -1:
        raise ValueError("valartic_completion_email.md: unclosed ```html block")
    return text[start:end].strip()


def render_valartic_completion_email(
    *,
    task_id: str,
    document_name: str,
    results_rows_html: str,
    year: int | None = None,
) -> str:
    y = year if year is not None else datetime.now(timezone.utc).year
    tpl = load_valartic_completion_html_template()
    return (
        tpl.replace("{{TASK_ID}}", html.escape(task_id))
        .replace("{{DOCUMENT_NAME}}", html.escape(document_name))
        .replace("{{RESULTS_ROWS}}", results_rows_html)
        .replace("{{YEAR}}", str(y))
    )
