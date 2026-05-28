"""Safe evaluation of branch ``if`` expressions from ``graph.yml``."""

from __future__ import annotations

from typing import Any


def _resolve_path(state: dict[str, Any], path: str) -> Any:
    cur: Any = state
    for part in path.strip().split("."):
        if part == "":
            continue
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _contains_any(haystack: Any, *needles: str) -> bool:
    text = str(haystack or "").lower()
    if not text:
        return False
    return any(str(n).lower() in text for n in needles)


def _in_list(value: Any, *items: str) -> bool:
    text = str(value or "").strip().lower()
    allowed = {str(i).strip().lower() for i in items}
    return text in allowed


def _coalesce(*values: Any) -> Any:
    for v in values:
        if v is not None and v != "":
            return v
    return ""


def _lower(value: Any) -> str:
    return str(value or "").lower()


def build_eval_context(state: dict[str, Any]) -> dict[str, Any]:
    """Namespace passed to ``eval`` for graph condition strings."""

    def get(path: str) -> Any:
        return _resolve_path(state, path)

    return {
        "state": state,
        "get": get,
        "lower": _lower,
        "coalesce": _coalesce,
        "in_list": _in_list,
        "contains_any": _contains_any,
        "true": True,
        "false": False,
    }


def evaluate_condition(expression: str | None, state: dict[str, Any]) -> bool:
    """
    Evaluate a boolean expression from graph config.

    Examples::

        in_list(lower(coalesce(get('extractions.metadata_from_text.type_of_sale'),
                              get('extractions.metadata_from_text.transaction_type'))),
                'auction', 'auctions')
        contains_any(lower(get('extractions.metadata_from_text.asset_type')), 'hotel', 'resort')
    """
    if expression is None or str(expression).strip() == "":
        return True
    expr = str(expression).strip()
    if expr.lower() in ("true", "1", "yes"):
        return True
    if expr.lower() in ("false", "0", "no"):
        return False
    ctx = build_eval_context(state)
    try:
        return bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307 — trusted internal YAML
    except Exception as exc:
        raise ValueError(f"Invalid graph condition {expression!r}: {exc}") from exc
