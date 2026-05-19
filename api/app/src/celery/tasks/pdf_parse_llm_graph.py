"""
LangGraph workflow for PDF text-tier LLM extraction.

Flow: pages of interest → metadata → parallel auxiliary schemas (standard vs hotel)
→ optional auction node.
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
    camelot_tables: list[dict[str, Any]]
    extractions: Annotated[dict[str, Any], _merge_extractions]


_FINAL_SCHEMA_KEYS: tuple[str, ...] = tuple(schemas_dict.keys())

_HOTEL_ASSET_TOKENS: frozenset[str] = frozenset(
    ("hotel", "hospitality", "lodging", "resort", "motel", "inn", "hostel", "casino")
)


def _metadata_dict(state: PdfParseLlmState) -> dict[str, Any]:
    raw = (state.get("extractions") or {}).get("metadata_from_text")
    return raw if isinstance(raw, dict) else {}


def route_after_metadata(state: PdfParseLlmState) -> Literal["hotel_path", "standard_path"]:
    meta = _metadata_dict(state)
    asset = (meta.get("asset_type") or "").strip().lower()
    if any(tok in asset for tok in _HOTEL_ASSET_TOKENS):
        return "hotel_path"
    return "standard_path"


def route_after_auxiliary(state: PdfParseLlmState) -> Literal["auction", "done"]:
    meta = _metadata_dict(state)
    sale = (meta.get("type_of_sale") or "").strip().lower()
    if sale in ("auction", "auctions", "auction sale"):
        return "auction"
    return "done"


def _empty_extractions() -> dict[str, Any | None]:
    return dict.fromkeys(_FINAL_SCHEMA_KEYS, None)


def build_pdf_parse_llm_graph(bridge: PdfParseGptBridge):
    """Compile a fresh graph bound to ``bridge`` node callables."""
    g = StateGraph(PdfParseLlmState)

    g.add_node("extract_pages_of_interest", bridge.node_extract_pages_of_interest)
    g.add_node("extract_metadata", bridge.node_extract_metadata)
    g.add_node(
        "extract_auxiliary_parallel_standard",
        bridge.node_extract_auxiliary_parallel_standard,
    )
    g.add_node(
        "extract_auxiliary_parallel_hotel",
        bridge.node_extract_auxiliary_parallel_hotel,
    )
    g.add_node("extract_auction_information", bridge.node_extract_auction_information)

    g.add_edge(START, "extract_pages_of_interest")
    g.add_edge("extract_pages_of_interest", "extract_metadata")
    g.add_conditional_edges(
        "extract_metadata",
        route_after_metadata,
        {
            "hotel_path": "extract_auxiliary_parallel_hotel",
            "standard_path": "extract_auxiliary_parallel_standard",
        },
    )
    g.add_conditional_edges(
        "extract_auxiliary_parallel_standard",
        route_after_auxiliary,
        {
            "auction": "extract_auction_information",
            "done": END,
        },
    )
    g.add_conditional_edges(
        "extract_auxiliary_parallel_hotel",
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
    page_texts: list[str],
    camelot_tables: list[dict[str, Any]],
) -> dict[str, Any | None]:
    """
    Run the extraction graph and return the merged ``extractions`` dict
    (schema keys → model_dump payloads or ``None``).
    """
    if not bridge.api_key:
        logger.warning(
            "run_pdf_parse_llm_graph skipped: GOOGLE_API_KEY is missing or empty"
        )
        return _empty_extractions()

    app = build_pdf_parse_llm_graph(bridge)
    final: PdfParseLlmState = app.invoke(
        {
            "page_texts": page_texts,
            "camelot_tables": camelot_tables,
            "extractions": {},
        }
    )
    return final.get("extractions") or _empty_extractions()
