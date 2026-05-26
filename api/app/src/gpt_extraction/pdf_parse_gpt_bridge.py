"""
LLM bridge for PDF parsing — same patterns as GptGetter (prompts + RobustJSONParser +
LangChain) without DB/SqlHelper (safe for Celery workers without Postgres).

Supports **Google Gemini** (``GOOGLE_API_KEY``) or **OpenAI** (``OPENAI_API_KEY``) for
text-tier extraction, selected via ``gpt.default_api`` in config (see ``configs/gpt.yml``).
Per-provider model ids use nested blocks ``gpt.model_fast`` / ``gpt.model_deep`` with
``google`` and ``openai`` keys; ``metadata_from_text`` and ``page_extraction`` use the
**deep** tier, other schemas use **fast**.

Each ``schemas_dict`` extraction uses its own system + user markdown pair from
:data:`src.constants.variables.TEXT_SCHEMA_PROMPT_FILES` (see ``prompt_templates/``).

**Prompt markdown:** user templates are merged into LangChain ``PromptTemplate`` (Python
``str.format`` rules). Literal curly braces in JSON examples must be doubled (``{{`` /
``}}``). Keep only ``{_format}`` and ``{query}`` as single-brace
placeholders (per-schema prompts); the final alignment user prompt also uses
``{aggregated_json}``.

Node helpers (:meth:`node_*`) are composed by :mod:`src.celery.tasks.pdf_parse_llm_graph`
via LangGraph.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from os.path import abspath, dirname
from pathlib import Path
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from omegaconf import DictConfig

from src.constants.variables import (
    HOTEL_AUX_SCHEMAS,
    INDUSTRIAL_AUX_SCHEMAS,
    LAND_AUX_SCHEMAS,
    MULTIFAMILY_AUX_SCHEMAS,
    RETAIL_AUX_SCHEMAS,
    STANDARD_AUX_SCHEMAS,
    TEXT_SCHEMA_PROMPT_FILES,
    schemas_dict,
)
from src.context import AppContext
from src.gpt_extraction.utils_genai.customed_parser import RobustJSONParser

logger = logging.getLogger(__name__)

# --- Parallel aux routing (metadata ``asset_type`` → schema list) ----------------

# Ordered bucket ids: first match wins (e.g. hotel before retail in mixed phrases).
_AUX_PARALLEL_ROUTE_ORDER: tuple[str, ...] = (
    "hotel",
    "land",
    "industrial",
    "multifamily",
    "retail",
)

# Per asset kind: substring keywords on ``asset_type``, optional exact full-string
# matches, and the parallel schema names to run when this bucket matches.
_AUX_PARALLEL_ROUTE_BY_ASSET_KIND: dict[str, dict[str, Any]] = {
    "hotel": {
        "substring_keywords": frozenset(
            (
                "hotel",
                "hospitality",
                "lodging",
                "resort",
                "motel",
                "inn",
                "hostel",
                "casino",
            )
        ),
        "exact_asset_types": frozenset(),
        "schemas": HOTEL_AUX_SCHEMAS,
    },
    "land": {
        "substring_keywords": frozenset(
            (
                "vacant land",
                "raw land",
                "land offering",
                "land sale",
                "undeveloped",
                "unimproved",
                "development site",
                "agricultural land",
                "acreage",
            )
        ),
        "exact_asset_types": frozenset(("land", "vacant land")),
        "schemas": LAND_AUX_SCHEMAS,
    },
    "industrial": {
        "substring_keywords": frozenset(
            (
                "industrial",
                "warehouse",
                "distribution",
                "logistics",
                "manufacturing",
                "flex",
            )
        ),
        "exact_asset_types": frozenset(),
        "schemas": INDUSTRIAL_AUX_SCHEMAS,
    },
    "multifamily": {
        "substring_keywords": frozenset(
            (
                "multifamily",
                "multi-family",
                "multi family",
                "apartment",
                "apartments",
            )
        ),
        "exact_asset_types": frozenset(),
        "schemas": MULTIFAMILY_AUX_SCHEMAS,
    },
    "retail": {
        "substring_keywords": frozenset(
            (
                "retail",
                "shopping",
                "strip center",
                "strip mall",
                "restaurant",
            )
        ),
        "exact_asset_types": frozenset(),
        "schemas": RETAIL_AUX_SCHEMAS,
    },
}


def _asset_type_matches_aux_route(
    asset_lower: str,
    *,
    substring_keywords: frozenset[str],
    exact_asset_types: frozenset[str],
) -> bool:
    if asset_lower in exact_asset_types:
        return True
    if not substring_keywords:
        return False
    return any(kw in asset_lower for kw in substring_keywords)


def aux_parallel_schema_names_for_metadata(
    metadata: dict[str, Any] | None,
) -> tuple[str, ...]:
    """
    Choose auxiliary parallel extraction schemas from ``metadata_from_text.asset_type``.

    Uses :data:`_AUX_PARALLEL_ROUTE_ORDER` and :data:`_AUX_PARALLEL_ROUTE_BY_ASSET_KIND`;
    first matching bucket wins; otherwise ``STANDARD_AUX_SCHEMAS`` from
    ``src.constants.variables``.
    """
    asset = ((metadata or {}).get("asset_type") or "").strip().lower()
    for kind in _AUX_PARALLEL_ROUTE_ORDER:
        cfg = _AUX_PARALLEL_ROUTE_BY_ASSET_KIND[kind]
        if _asset_type_matches_aux_route(
            asset,
            substring_keywords=cfg["substring_keywords"],
            exact_asset_types=cfg["exact_asset_types"],
        ):
            return cfg["schemas"]
    return STANDARD_AUX_SCHEMAS


def format_labeled_pages(
    page_texts: list[str],
    page_numbers: list[int] | None = None,
) -> str:
    """Build LLM context from ``page_texts`` (0-based list, 1-based page labels)."""
    if page_numbers:
        chunks: list[str] = []
        for page_num in page_numbers:
            idx = page_num - 1 if page_num >= 1 else page_num
            if 0 <= idx < len(page_texts):
                body = (page_texts[idx] or "").strip()
                if body:
                    chunks.append(f"--- Page {page_num} ---\n{body}")
        if chunks:
            return "\n\n".join(chunks)
        # Routed pages did not resolve to text — fall back to full document.
        page_numbers = None

    chunks = []
    for i, raw in enumerate(page_texts):
        body = (raw or "").strip()
        if body:
            chunks.append(f"--- Page {i + 1} ---\n{body}")
    return "\n\n".join(chunks)


def _normalize_llm_provider(raw: Any) -> str:
    """Return ``google`` or ``openai`` from ``gpt.default_api`` (or legacy aliases)."""
    s = str(raw or "google").strip().lower()
    if s in ("openai", "oai", "chatgpt"):
        return "openai"
    return "google"


def _provider_model_from_block(
    gpt_cfg: Any,
    block: str,
    *,
    defaults: tuple[str, str],
) -> tuple[str, str]:
    """
    Read ``gpt.{block}.google`` and ``gpt.{block}.openai`` (nested YAML dict).

    Returns ``(google_model_id, openai_model_id)``.
    """
    dg, do = defaults
    sub = getattr(gpt_cfg, block, None)
    if sub is None:
        return (dg, do)
    g_raw = sub.get("google") if hasattr(sub, "get") else getattr(sub, "google", None)
    o_raw = sub.get("openai") if hasattr(sub, "get") else getattr(sub, "openai", None)
    g = str(g_raw).strip() if g_raw not in (None, "") else dg
    o = str(o_raw).strip() if o_raw not in (None, "") else do
    return (g, o)


def _text_tier_for_schema(schema_name: str) -> str:
    return "fast"

class PdfParseGptBridge:
    """
    Text-tier extraction via LangChain, using **Google Gemini** or **OpenAI** depending
    on ``gpt.default_api``. Model ids come from ``gpt.model_fast`` / ``gpt.model_deep``
    (each with ``google`` / ``openai``); see ``configs/gpt.yml``.
    """

    def __init__(self, context: AppContext, config: DictConfig):
        self._ctx = context
        self._config = config
        self._log = logging.getLogger(__name__)
        self._prompt_path = Path(dirname(abspath(__file__))) / "prompt_templates"

        gpt_cfg = config.gpt
        self.llm_provider = _normalize_llm_provider(getattr(gpt_cfg, "default_api", "google"))

        self._google_api_key = (context.google_api_key or "").strip() or None
        self._openai_api_key = (context.openai_api_key or "").strip() or None

        _dg, _do = "gemini-2.5-flash-lite", "gpt-5-nano"
        g_fast, o_fast = _provider_model_from_block(gpt_cfg, "model_fast", defaults=(_dg, _do))
        g_deep, o_deep = _provider_model_from_block(gpt_cfg, "model_deep", defaults=(_dg, _do))

        # Legacy flat keys (pre nested model_fast / model_deep)
        if getattr(gpt_cfg, "model_fast", None) is None:
            if getattr(gpt_cfg, "model_text", None):
                g_fast = str(getattr(gpt_cfg, "model_text")).strip()
            if getattr(gpt_cfg, "model_text_openai", None):
                o_fast = str(getattr(gpt_cfg, "model_text_openai")).strip()
        if getattr(gpt_cfg, "model_deep", None) is None:
            g_deep, o_deep = g_fast, o_fast

        self._google_model_fast = g_fast
        self._openai_model_fast = o_fast
        self._google_model_deep = g_deep
        self._openai_model_deep = o_deep

        raw_effort = getattr(gpt_cfg, "openai_reasoning_effort", "low")
        if raw_effort is None or (isinstance(raw_effort, str) and not raw_effort.strip()):
            self._openai_reasoning_effort: str | None = None
        else:
            self._openai_reasoning_effort = str(raw_effort).strip().lower()

        self.temperature = float(gpt_cfg.temperature)
        self.max_token = int(gpt_cfg.max_token)
        self.model_text = (
            self._openai_model_fast if self.llm_provider == "openai" else self._google_model_fast
        )

        self._STANDARD_AUX_SCHEMAS = STANDARD_AUX_SCHEMAS
        self._HOTEL_AUX_SCHEMAS = HOTEL_AUX_SCHEMAS
        self._LAND_AUX_SCHEMAS = LAND_AUX_SCHEMAS
        self._INDUSTRIAL_AUX_SCHEMAS = INDUSTRIAL_AUX_SCHEMAS
        self._MULTIFAMILY_AUX_SCHEMAS = MULTIFAMILY_AUX_SCHEMAS
        self._RETAIL_AUX_SCHEMAS = RETAIL_AUX_SCHEMAS

    @property
    def api_key(self) -> str | None:
        """Active API key for the configured ``llm_provider``."""
        if self.llm_provider == "openai":
            return self._openai_api_key
        return self._google_api_key

    def _read(self, name: str) -> str:
        path = self._prompt_path / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing prompt {path}")
        return path.read_text(encoding="utf-8")

    def _text_tier_extraction_chain(self, schema_name: str, *, tier: str):
        """LangChain runnable: dedicated system + user prompts per ``schemas_dict`` key."""
        
        if schema_name not in schemas_dict:
            raise ValueError(f"Invalid schema name: {schema_name}")
        
        try:
            system_name, user_name = TEXT_SCHEMA_PROMPT_FILES[schema_name]
        except KeyError as exc:
            raise ValueError(
                f"No prompt template pair registered for schema {schema_name!r} "
                "in TEXT_SCHEMA_PROMPT_FILES"
            ) from exc

        system = self._read(system_name)
        user = self._read(user_name)

        parser = PydanticOutputParser(pydantic_object=schemas_dict[schema_name])
        robust = RobustJSONParser(parser)
        format_instructions = parser.get_format_instructions()
        prompt = PromptTemplate(
            template=system + "\n\n" + user,
            input_variables=["query"],
            partial_variables={
                "_format": format_instructions,
            },
        )

        llm = self._make_text_chat_model(tier)

        return prompt | llm | robust

    def _make_text_chat_model(self, tier: str) -> Any:
        """Instantiate the LangChain chat model for ``tier`` (``fast`` or ``deep``)."""
        if tier not in ("fast", "deep"):
            tier = "fast"

        if self.llm_provider == "openai":

            model = self._openai_model_deep if tier == "deep" else self._openai_model_fast
            kwargs: dict[str, Any] = {
                "model": model,
                "api_key": self._openai_api_key,
                "temperature": self.temperature,
                "max_tokens": self.max_token,
            }
            if self._openai_reasoning_effort:
                kwargs["reasoning_effort"] = self._openai_reasoning_effort

            return ChatOpenAI(**kwargs)

        g_model = self._google_model_deep if tier == "deep" else self._google_model_fast
        return ChatGoogleGenerativeAI(
            model=g_model,
            google_api_key=self._google_api_key,
            temperature=self.temperature,
            max_output_tokens=self.max_token,
        )

    def run_one_sync(
        self,
        schema_name: str,
        page_texts: list[str],
    ) -> tuple[str, Any | None]:
        
        try:
            tier = _text_tier_for_schema(schema_name)
            chain = self._text_tier_extraction_chain(schema_name, tier=tier)
            out = chain.invoke(
                {"query": page_texts[:120_000]}
            )
            model_cls = schemas_dict[schema_name]
            if isinstance(out, model_cls):
                return schema_name, out.model_dump()
            return schema_name, model_cls.model_validate(out).model_dump()
        
        except Exception as exc:
            self._log.warning(
                "Text LLM schema %s failed: %s",
                schema_name,
                exc,
                exc_info=self._log.isEnabledFor(logging.DEBUG),
            )
            return schema_name, None

    # --- LangGraph nodes -------------------------------------------------------

    def _aux_parallel_extractions(
        self,
        schema_names: tuple[str, ...],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Run each auxiliary schema in parallel (full-document context)."""
        if not self.api_key:
            return {"extractions": dict.fromkeys(schema_names, None)}

        page_texts = state["page_texts"]

        async def _gather() -> dict[str, Any | None]:
            pairs = await asyncio.gather(
                *[
                    asyncio.to_thread(
                        self.run_one_sync,
                        name,
                        page_texts,
                    )
                    for name in schema_names
                ]
            )
            return {name: payload for name, payload in pairs}

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            merged = asyncio.run(_gather())
        else:
            self._log.debug(
                "aux_parallel: nested event loop — running batch in a worker thread"
            )

            def _run_in_fresh_loop() -> dict[str, Any | None]:
                return asyncio.run(_gather())

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                merged = pool.submit(_run_in_fresh_loop).result()

        return {"extractions": merged}

    def node_extract_metadata(self, state: dict[str, Any]) -> dict[str, Any]:
        """Property summary and asset type (full-document text + tables)."""
        _, payload = self.run_one_sync(
            "metadata_from_text",
            state["page_texts"],
        )
        return {"extractions": {"metadata_from_text": payload}}
    
    def node_extract_pages(self, state: dict[str, Any]) -> dict[str, Any]:
        """Property summary and asset type (full-document text + tables)."""
        _, payload = self.run_one_sync(
            "page_extraction",
            state["page_texts"],
        )
        return {"extractions": {"page_extraction": payload}}

    def node_extract_auxiliary_parallel_standard(
        self, state: dict[str, Any]
    ) -> dict[str, Any]:
        return self._aux_parallel_extractions(self._STANDARD_AUX_SCHEMAS, state)

    def node_extract_auxiliary_parallel_hotel(
        self, state: dict[str, Any]
    ) -> dict[str, Any]:
        return self._aux_parallel_extractions(self._HOTEL_AUX_SCHEMAS, state)

    def node_extract_auxiliary_parallel_routed(
        self, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Step 3: parallel aux schemas chosen from metadata ``asset_type`` (hotel / land / etc.)."""
        raw = (state.get("extractions") or {}).get("metadata_from_text")
        meta = raw if isinstance(raw, dict) else {}
        names = aux_parallel_schema_names_for_metadata(meta)
        self._log.debug(
            "aux_parallel_routed asset_type=%r -> %d schemas",
            meta.get("asset_type"),
            len(names),
        )
        return self._aux_parallel_extractions(names, state)

    def node_extract_auction_information(self, state: dict[str, Any]) -> dict[str, Any]:
        _, payload = self.run_one_sync(
            "auction_information",
            state["page_texts"],
        )
        return {"extractions": {"auction_information": payload}}
