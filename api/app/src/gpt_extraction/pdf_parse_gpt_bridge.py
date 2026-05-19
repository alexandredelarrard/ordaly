"""
LLM bridge for PDF parsing — same patterns as GptGetter (prompts + RobustJSONParser +
LangChain) without DB/SqlHelper (safe for Celery workers without Postgres).

Node helpers (:meth:`node_*`) are composed by :mod:`src.celery.tasks.pdf_parse_llm_graph`
via LangGraph.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import logging
from os.path import abspath, dirname
from pathlib import Path
from typing import Any, Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from omegaconf import DictConfig

from src.constants.variables import SCHEMA_TO_PAGE_INTEREST_FIELD, schemas_dict
from src.context import AppContext
from src.gpt_extraction.utils_genai.customed_parser import RobustJSONParser
from src.schemas.parse_pipeline import VisionTableExtraction

logger = logging.getLogger(__name__)

_STANDARD_AUX_SCHEMAS = (
    "meta_key_kpis",
    "financial_statement",
    "rent_roll_report",
    "building_report",
    "demographics_report",
    "attractiveness_report",
)
_HOTEL_AUX_SCHEMAS = (
    "meta_key_kpis",
    "financial_statement_hotel",
    "building_report",
    "amenities_report",
    "hotel_specific_report",
    "demographics_report",
    "attractiveness_report",
)


def _normalize_page_numbers(raw: Any) -> list[int] | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return [raw]
    if isinstance(raw, list):
        out: list[int] = []
        for item in raw:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out or None
    return None


def pages_of_interest_has_any_pages(pages_of_interest: dict[str, Any] | None) -> bool:
    """True when step 1 returned at least one routed page number."""
    if not pages_of_interest:
        return False
    for field in set(SCHEMA_TO_PAGE_INTEREST_FIELD.values()):
        if _normalize_page_numbers(pages_of_interest.get(field)):
            return True
    return False


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


def filter_camelot_tables(
    camelot_tables: list[dict[str, Any]],
    page_numbers: list[int] | None,
) -> list[dict[str, Any]]:
    if not page_numbers:
        return camelot_tables
    allowed = set(page_numbers)
    return [t for t in camelot_tables if t.get("page") in allowed]


def page_numbers_for_schema(
    pages_of_interest: dict[str, Any] | None,
    schema_name: str,
) -> list[int] | None:
    """
    Return 1-based page numbers for ``schema_name``, or ``None`` to use all pages.

    When step 1 found no pages at all, or this schema's field is empty, returns
    ``None`` so downstream calls receive the full document.
    """
    if not pages_of_interest or not pages_of_interest_has_any_pages(pages_of_interest):
        return None
    field = SCHEMA_TO_PAGE_INTEREST_FIELD.get(schema_name)
    if not field:
        return None
    return _normalize_page_numbers(pages_of_interest.get(field))


class PdfParseGptBridge:
    """
    Text + vision extraction using Google Gemini via LangChain, mirroring
    GptGetter/GptExtracter prompt assembly without queue or database side-effects.
    """

    def __init__(self, context: AppContext, config: DictConfig):
        self._ctx = context
        self._config = config
        self._log = logging.getLogger(__name__)
        self._prompt_path = Path(dirname(abspath(__file__))) / "prompt_templates"

        self.api_key = context.google_api_key
        self.model_text = config.gpt.model_text
        self.model_vision = config.gpt.model_vision
        self.model_vision_pro = getattr(
            config.gpt, "model_vision_pro", None
        ) or self.model_vision
        self.temperature = float(config.gpt.temperature)
        self.max_token = int(config.gpt.max_token)

        self._STANDARD_AUX_SCHEMAS = _STANDARD_AUX_SCHEMAS
        self._HOTEL_AUX_SCHEMAS = _HOTEL_AUX_SCHEMAS

    def _read(self, name: str) -> str:
        path = self._prompt_path / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing prompt {path}")
        return path.read_text(encoding="utf-8")

    def _metadata_chain(self, schema_name: str):
        if not self.api_key:
            return None

        system = self._read("parse_metadata_system_prompt.md")
        user = self._read("parse_metadata_prompt.md")

        if schema_name not in schemas_dict:
            raise ValueError(f"Invalid schema name: {schema_name}")

        parser = PydanticOutputParser(pydantic_object=schemas_dict[schema_name])
        robust = RobustJSONParser(parser)
        prompt = PromptTemplate(
            template=system + "\n\n" + user,
            input_variables=["query", "camelot_tables"],
            partial_variables={
                "_format": parser.get_format_instructions(),
            },
        )
        llm = ChatGoogleGenerativeAI(
            model=self.model_text,
            google_api_key=self.api_key,
            temperature=self.temperature,
            max_output_tokens=self.max_token,
        )
        return prompt | llm | robust

    def run_one_sync(
        self,
        schema_name: str,
        page_texts: list[str],
        camelot_tables: list[dict[str, Any]],
        *,
        page_numbers: list[int] | None = None,
    ) -> tuple[str, Any | None]:
        text = format_labeled_pages(page_texts, page_numbers)
        # Empty routed context → use all pages (and all Camelot tables).
        if page_numbers and not text.strip():
            page_numbers = None
            text = format_labeled_pages(page_texts, None)
        snippet = text[:120_000]
        tables_subset = filter_camelot_tables(camelot_tables, page_numbers)
        camelot_tables_snippet = (
            "\n".join([str(table) for table in tables_subset[:20]])
            if tables_subset
            else ""
        )

        try:
            chain = self._metadata_chain(schema_name)
            if chain is None:
                return schema_name, None
            out = chain.invoke(
                {"query": snippet, "camelot_tables": camelot_tables_snippet}
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

    def node_extract_pages_of_interest(self, state: dict[str, Any]) -> dict[str, Any]:
        """Step 1: route OM pages to downstream extraction schemas."""
        _, payload = self.run_one_sync(
            "page_of_interest",
            state["page_texts"],
            state["camelot_tables"],
        )
        return {"extractions": {"page_of_interest": payload}}

    def node_extract_metadata(self, state: dict[str, Any]) -> dict[str, Any]:
        """Step 2: property summary and asset type from metadata pages."""
        pages = page_numbers_for_schema(
            (state.get("extractions") or {}).get("page_of_interest"),
            "metadata_from_text",
        )
        _, payload = self.run_one_sync(
            "metadata_from_text",
            state["page_texts"],
            state["camelot_tables"],
            page_numbers=pages,
        )
        return {"extractions": {"metadata_from_text": payload}}

    def _aux_parallel_extractions(
        self,
        schema_names: tuple[str, ...],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Step 3: run each auxiliary schema on its page subset in parallel."""
        if not self.api_key:
            return {"extractions": dict.fromkeys(schema_names, None)}

        page_texts = state["page_texts"]
        camelot_tables = state["camelot_tables"]
        pages_of_interest = (state.get("extractions") or {}).get("page_of_interest")

        async def _gather() -> dict[str, Any | None]:
            pairs = await asyncio.gather(
                *[
                    asyncio.to_thread(
                        self.run_one_sync,
                        name,
                        page_texts,
                        camelot_tables,
                        page_numbers=page_numbers_for_schema(
                            pages_of_interest, name
                        ),
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

    def node_extract_auxiliary_parallel_standard(
        self, state: dict[str, Any]
    ) -> dict[str, Any]:
        return self._aux_parallel_extractions(self._STANDARD_AUX_SCHEMAS, state)

    def node_extract_auxiliary_parallel_hotel(
        self, state: dict[str, Any]
    ) -> dict[str, Any]:
        return self._aux_parallel_extractions(self._HOTEL_AUX_SCHEMAS, state)

    def node_extract_auction_information(self, state: dict[str, Any]) -> dict[str, Any]:
        pages_of_interest = (state.get("extractions") or {}).get("page_of_interest")
        _, payload = self.run_one_sync(
            "auction_information",
            state["page_texts"],
            state["camelot_tables"],
            page_numbers=page_numbers_for_schema(
                pages_of_interest, "auction_information"
            ),
        )
        return {"extractions": {"auction_information": payload}}

    def extract_metadata_from_pdf_text(
        self,
        page_texts: list[str] | str,
        camelot_tables: list[dict[str, Any]],
    ) -> dict[str, Any | None]:
        """
        Full text-tier extraction via LangGraph (pages of interest → metadata →
        parallel schema extractions → optional auction). Kept for call sites that
        expect this name.
        """
        from src.celery.tasks.pdf_parse_llm_graph import run_pdf_parse_llm_graph

        if isinstance(page_texts, str):
            page_texts = [page_texts]
        return run_pdf_parse_llm_graph(self, page_texts, camelot_tables)

    def _vision_chain(self, model: Optional[str] = None):
        if not self.api_key:
            return None

        system = self._read("parse_vision_system_prompt.md")
        user = self._read("parse_vision_prompt.md")

        parser = PydanticOutputParser(pydantic_object=VisionTableExtraction)
        robust = RobustJSONParser(parser)
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                (
                    "human",
                    [
                        {"type": "text", "text": user},
                        {"type": "image_url", "image_url": "{image_url}"},
                    ],
                ),
            ]
        ).partial(_format=parser.get_format_instructions())
        llm = ChatGoogleGenerativeAI(
            model=model or self.model_vision,
            google_api_key=self.api_key,
            temperature=self.temperature,
            max_output_tokens=self.max_token,
        )
        return prompt | llm | robust

    def extract_table_from_page_image(
        self,
        png_bytes: bytes,
        page_label: str,
        *,
        use_pro: bool = False,
    ) -> Optional[VisionTableExtraction]:
        """Tier-2 vision: page image → structured table (Gemini multimodal)."""
        model = self.model_vision_pro if use_pro else self.model_vision
        chain = self._vision_chain(model=model)
        if chain is None:
            self._log.debug("No GOOGLE_API_KEY — skip vision table LLM")
            return None

        b64 = base64.standard_b64encode(png_bytes).decode("ascii")
        url = f"data:image/png;base64,{b64}"
        try:
            out = chain.invoke(
                {
                    "page_context": page_label,
                    "image_url": url,
                }
            )
            if isinstance(out, VisionTableExtraction):
                return out
            return VisionTableExtraction.model_validate(out)
        except Exception as exc:
            self._log.warning("Vision table LLM failed (%s): %s", page_label, exc)
            return None
