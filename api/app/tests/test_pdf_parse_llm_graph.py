"""Tests for config-driven extraction graph (no live LLM calls)."""

from __future__ import annotations

import logging
import sys
from typing import Any
from unittest.mock import MagicMock

def _install_step_stub() -> None:
    """Avoid SqlHelper DB when importing :class:`PdfParseGptBridge` in unit tests."""
    import types

    mod = types.ModuleType("src.utils.step")

    class Step:
        def __init__(self, config, context=None, *args, **kwargs):
            self._config = config
            self._context = context
            self._log = logging.getLogger("test")

    mod.Step = Step
    sys.modules["src.utils.step"] = mod


_install_step_stub()

try:
    import pytest
except ImportError:  # pragma: no cover
    pytest = None  # type: ignore[assignment]

from omegaconf import DictConfig

from src.gpt_extraction.graph_condition import evaluate_condition
from src.gpt_extraction.pdf_parse_gpt_bridge import PdfParseGptBridge
from src.gpt_extraction.pdf_parse_llm_graph import (
    BuildGraph,
    build_pdf_parse_llm_graph,
    normalize_page_texts,
    run_pdf_parse_llm_graph,
)
from src.utils.config import read_config

logger = logging.getLogger(__name__)

_STUB_PAYLOADS: dict[str, dict[str, Any]] = {
    "metadata_from_text": {
        "asset_type": "Retail",
        "type_of_sale": "auction",
    },
    "page_extraction": {"metadata_page": 1},
    "auction_information": {"auction_date": "2026-01-01"},
    "rent_roll_report": {"units": 1},
    "building_report": {"year_built": 1990},
    "demographics_report": {"population": 1000},
    "financial_statement": {"noi": 1},
}


class StubPdfParseGptBridge(PdfParseGptBridge):
    """``PdfParseGptBridge`` with stubbed ``run_one_sync`` / ``aux_parallel_extractions``."""

    def __init__(self, config: DictConfig, context: Any = None) -> None:
        self._config = config
        self._context = context or MagicMock()
        self._log = logger
        self.run_one_sync_calls: list[str] = []

    def run_one_sync(
        self,
        schema_name: str,
        page_texts: list[str],
        *,
        tier: str = "fast",
        prompt_files: tuple[str, str] | None = None,
    ) -> tuple[str, Any | None]:
        self.run_one_sync_calls.append(schema_name)
        return schema_name, _STUB_PAYLOADS.get(schema_name, {"ok": True})

    def aux_parallel_extractions(
        self,
        schema_names: tuple[str, ...],
        page_texts: list[str],
        *,
        tier: str = "fast",
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for name in schema_names:
            _, payload = self.run_one_sync(name, page_texts, tier=tier)
            if payload is not None:
                merged[name] = payload
        return {"extractions": merged}


def _graph_config() -> DictConfig:
    return read_config(path="./configs")


def _context(config: DictConfig) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config
    return ctx


def _bridge(config: DictConfig | None = None) -> StubPdfParseGptBridge:
    cfg = config or _graph_config()
    return StubPdfParseGptBridge(cfg, _context(cfg))


def _build_graph(bridge: StubPdfParseGptBridge, config: DictConfig) -> BuildGraph:
    return BuildGraph(bridge._context, config, bridge=bridge)


if pytest is not None:

    @pytest.fixture(scope="module")
    def graph_config() -> DictConfig:
        return _graph_config()

    @pytest.fixture
    def bridge(graph_config: DictConfig) -> StubPdfParseGptBridge:
        return _bridge(graph_config)


def test_graph_yml_individual_nodes(graph_config: DictConfig) -> None:
    nodes = graph_config.graph.nodes
    assert "extract_metadata" in nodes
    assert "extract_building" in nodes
    assert "extract_rent_roll" in nodes
    assert "extract_auxiliary_parallel_routed" not in nodes
    parallel = graph_config.graph.parallel
    assert "extract_pages_parallel" in parallel
    assert "extract_building" in parallel.extract_pages_parallel


def test_normalize_page_texts_accepts_str() -> None:
    assert normalize_page_texts("hello") == ["hello"]
    assert normalize_page_texts(["a", "b"]) == ["a", "b"]
    assert PdfParseGptBridge.document_query(["p1", "p2"]) == "p1\n\np2"


def test_run_graph_accepts_joined_string(
    bridge: StubPdfParseGptBridge, graph_config: DictConfig
) -> None:
    result = run_pdf_parse_llm_graph(bridge, "single document text", config=graph_config)
    assert "metadata_from_text" in result


def test_condition_auction_expression() -> None:
    state = {
        "extractions": {
            "metadata_from_text": {"transaction_type": "Auction Sale"},
        }
    }
    expr = (
        "in_list(lower(coalesce(get('extractions.metadata_from_text.type_of_sale'), "
        "get('extractions.metadata_from_text.transaction_type'))), "
        "'auction', 'auctions', 'auction sale')"
    )
    assert evaluate_condition(expr, state) is True


def test_condition_hotel_asset_type() -> None:
    state = {"extractions": {"metadata_from_text": {"asset_type": "Full-service hotel"}}}
    expr = (
        "contains_any(lower(get('extractions.metadata_from_text.asset_type')), "
        "'hotel', 'hospitality')"
    )
    assert evaluate_condition(expr, state) is True


def test_compiled_graph_has_parallel_group(
    bridge: StubPdfParseGptBridge, graph_config: DictConfig
) -> None:
    app = _build_graph(bridge, graph_config).build()
    nodes = set(app.get_graph().nodes.keys())
    assert "extract_pages_parallel" in nodes
    assert "extract_metadata" in nodes
    assert "extract_auction_information" in nodes


def test_run_graph_auction_branch(
    bridge: StubPdfParseGptBridge, graph_config: DictConfig
) -> None:
    result = run_pdf_parse_llm_graph(bridge, ["p1"], config=graph_config)
    assert result["metadata_from_text"]["type_of_sale"] == "auction"
    assert "rent_roll_report" in result
    assert "auction_information" in bridge.run_one_sync_calls


def test_retail_skips_hotel_only_nodes(
    bridge: StubPdfParseGptBridge, graph_config: DictConfig
) -> None:
    run_pdf_parse_llm_graph(bridge, ["p1"], config=graph_config)
    assert "hotel_specific_report" not in bridge.run_one_sync_calls
    assert "financial_statement_hotel" not in bridge.run_one_sync_calls
    assert "rent_roll_report" in bridge.run_one_sync_calls


def test_build_graph_step_run(
    bridge: StubPdfParseGptBridge, graph_config: DictConfig
) -> None:
    result = _build_graph(bridge, graph_config).run(["p1"])
    assert "metadata_from_text" in result


def _run_all() -> None:
    cfg = _graph_config()
    b = _bridge(cfg)
    test_graph_yml_individual_nodes(cfg)
    test_normalize_page_texts_accepts_str()
    test_run_graph_accepts_joined_string(b, cfg)
    test_condition_auction_expression()
    test_condition_hotel_asset_type()
    test_compiled_graph_has_parallel_group(b, cfg)
    test_run_graph_auction_branch(b, cfg)
    test_retail_skips_hotel_only_nodes(b, cfg)
    test_build_graph_step_run(b, cfg)


if __name__ == "__main__":
    _run_all()
    print("OK: all tests passed")
