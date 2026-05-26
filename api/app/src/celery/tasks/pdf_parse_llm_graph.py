"""
LangGraph workflow for PDF text-tier LLM extraction.

Flow: metadata (full document) → parallel auxiliary schemas (by ``asset_type``)
→ optional auction → **final_alignment_check** (Gemini Pro: returns ``OmFinalAlignmentBundle`` vs full OM + aggregated JSON).
Each extraction node uses ``TEXT_SCHEMA_PROMPT_FILES`` for its schema key.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src.constants.variables import schemas_dict
from src.gpt_extraction.pdf_parse_gpt_bridge import PdfParseGptBridge

logger = logging.getLogger(__name__)


def _merge_extractions(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    a = dict(left) if left else {}
    b = dict(right) if right else {}
    return {**a, **b}


class PdfParseLlmState(TypedDict, total=False):
    page_texts: list[str]
    extractions: Annotated[dict[str, Any], _merge_extractions]

_FINAL_SCHEMA_KEYS: tuple[str, ...] = tuple(schemas_dict.keys())


def _metadata_dict(state: PdfParseLlmState) -> dict[str, Any]:
    raw = (state.get("extractions") or {}).get("metadata_from_text")
    return raw if isinstance(raw, dict) else {}


def route_after_auxiliary(state: PdfParseLlmState) -> Literal["auction", "done"]:
    meta = _metadata_dict(state)
    sale = (
        meta.get("type_of_sale") or meta.get("transaction_type") or ""
    ).strip().lower()
    if sale in ("auction", "auctions", "auction sale"):
        return "auction"
    return "done"


def _empty_extractions() -> dict[str, Any | None]:
    return dict.fromkeys(_FINAL_SCHEMA_KEYS, None)


def build_pdf_parse_llm_graph(bridge: PdfParseGptBridge):
    """Compile a fresh graph bound to ``bridge`` node callables."""
    
    g = StateGraph(PdfParseLlmState)
    
    g.add_node("extract_metadata", bridge.node_extract_metadata)
    g.add_node("extract_pages", bridge.node_extract_pages)
    g.add_node(
        "extract_auxiliary_parallel_routed",
        bridge.node_extract_auxiliary_parallel_routed,
    )
    g.add_node("extract_auction_information", bridge.node_extract_auction_information)

    g.add_edge(START, "extract_metadata")
    g.add_edge("extract_metadata", "extract_pages")
    g.add_edge("extract_pages", "extract_auxiliary_parallel_routed")
    g.add_conditional_edges(
        "extract_auxiliary_parallel_routed",
        route_after_auxiliary,
        {
            "auction": "extract_auction_information",
            "done": END,
        },
    )
    g.add_edge("extract_auction_information", END)

    return g.compile()


def run_pdf_parse_llm_graph(
    bridge: PdfParseGptBridge,
    page_texts: list[str]
) -> dict[str, Any | None]:
    """
    Run the extraction graph and return the merged ``extractions`` dict
    (schema keys → model_dump payloads or ``None``).
    """
    if not bridge.api_key:
        logger.warning(
            "run_pdf_parse_llm_graph skipped: no API key for provider %r "
            "(set GOOGLE_API_KEY when gpt.default_api is google, or OPENAI_API_KEY when openai)",
            getattr(bridge, "llm_provider", "google"),
        )
        return _empty_extractions()

    app = build_pdf_parse_llm_graph(bridge)
    final: PdfParseLlmState = app.invoke(
        {
            "page_texts": page_texts,
            "extractions": {},
        }
    )
    merged = final.get("extractions") or {}
    return {**_empty_extractions(), **merged}
