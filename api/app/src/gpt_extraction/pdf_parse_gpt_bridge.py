from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from os.path import abspath, dirname
from pathlib import Path
from typing import Any
import os

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from omegaconf import DictConfig

from src.constants.variables import (
    TEXT_SCHEMA_PROMPT_FILES,
    schemas_dict,
)
from src.context import AppContext
from src.gpt_extraction.utils_genai.customed_parser import RobustJSONParser
from src.utils.step import Step

logger = logging.getLogger(__name__)

class PdfParseGptBridge(Step):
    """
    Text-tier extraction via LangChain, using **Google Gemini** or **OpenAI** depending
    on ``gpt.default_api``. Model ids come from ``gpt.model_fast`` / ``gpt.model_deep``
    (each with ``google`` / ``openai``); see ``configs/gpt.yml``.
    """

    def __init__(self, context: AppContext, config: DictConfig):
        super().__init__(config, context)

        self._prompt_path = Path(dirname(abspath(__file__))) / "prompt_templates"
        self.llm_provider = self._config.gpt.get("default_api", "google")

        self._api_key = os.environ.get(f"{self.llm_provider.upper()}_API_KEY").strip()
        self.fast_model = self._config.gpt.get(self.llm_provider).get('model_fast', 'gemini-2.5-flash-lite')
        self.deep_model = self._config.gpt.get(self.llm_provider).get('model_deep', 'gemini-2.5-flash-lite')
        self.reasoning = self._config.gpt.get(self.llm_provider).get('reasoning_effort', 'low')
        self.temperature = float(self._config.gpt.temperature)
        self.max_token = int(self._config.gpt.max_token)

    def _read(self, name: str) -> str:
        path = self._prompt_path / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing prompt {path}")
        return path.read_text(encoding="utf-8")

    def _text_tier_extraction_chain(
        self,
        schema_name: str,
        *,
        tier: str = "fast",
        prompt_files: tuple[str, str] | None = None,
    ):
        """LangChain runnable: dedicated system + user prompts per ``schemas_dict`` key."""
        
        if schema_name not in schemas_dict:
            raise ValueError(f"Invalid schema name: {schema_name}")
        
        if prompt_files is not None:
            system_name, user_name = prompt_files
        else:
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
        
        kwargs: dict[str, Any] = {
            "model": self.fast_model if tier == "fast" else self.deep_model,
            "api_key": self._api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_token,
        }
        
        if tier not in ("fast", "deep"):
            tier = "fast"

        if self.llm_provider == "openai":
            if self.reasoning:
                kwargs["reasoning_effort"] = self.reasoning
            return ChatOpenAI(**kwargs)
        else:
            return ChatGoogleGenerativeAI(**kwargs)

    @staticmethod
    def document_query(page_texts: list[str], *, max_chars: int = 120_000) -> str:
        """Join per-page text into one prompt string (character-capped)."""
        if not page_texts:
            return ""
        body = page_texts[0] if len(page_texts) == 1 else "\n\n".join(page_texts)
        return body[:max_chars]

    def run_one_sync(
        self,
        schema_name: str,
        page_texts: list[str],
        *,
        tier: str = "fast",
        prompt_files: tuple[str, str] | None = None,
    ) -> tuple[str, Any | None]:
        
        try:
            chain = self._text_tier_extraction_chain(
                schema_name,
                tier=tier,
                prompt_files=prompt_files,
            )
            out = chain.invoke(
                {"query": self.document_query(page_texts)}
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
        
    def aux_parallel_extractions(
        self,
        schema_names: tuple[str, ...],
        page_texts: list[str],
        *,
        tier: str = "fast",
    ) -> dict[str, Any]:
        """Run each auxiliary schema in parallel (full-document context)."""

        async def _gather() -> dict[str, Any | None]:
            pairs = await asyncio.gather(
                *[
                    asyncio.to_thread(
                        self.run_one_sync,
                        name,
                        page_texts,
                        tier=tier,
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
