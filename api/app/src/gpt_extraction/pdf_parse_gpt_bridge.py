"""
LLM bridge for PDF parsing — same patterns as GptGetter (prompts + RobustJSONParser + LangChain)
without DB/SqlHelper (safe for Celery workers without Postgres).
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

from src.constants.variables import schemas_dict
from src.context import AppContext
from src.gpt_extraction.utils_genai.customed_parser import RobustJSONParser
from src.schemas.parse_pipeline import VisionTableExtraction

logger = logging.getLogger(__name__)


class PdfParseGptBridge:
    """
    Text + vision extraction using Google Gemini via LangChain, mirroring GptGetter/GptExtracter
    prompt assembly without queue or database side-effects.
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

    def _read(self, name: str) -> str:
        path = self._prompt_path / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing prompt {path}")
        return path.read_text(encoding="utf-8")

    def _google_api_key(self) -> Optional[str]:
        return (self._ctx.google_api_key or "").strip() or None

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

    def run_one_sync(self, schema_name: str, text: str, camelot_tables: list[dict[str, Any]]) -> tuple[str, Any | None]:
        
        snippet = text[:120_000]
        camelot_tables_snippet = "\n".join([str(table) for table in camelot_tables[:20]]) if len(camelot_tables) > 0 else ""
        
        try:
            chain = self._metadata_chain(schema_name)
            if chain is None:
                return schema_name, None
            out = chain.invoke({"query": snippet, "camelot_tables": camelot_tables_snippet})
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


    async def extract_metadata_from_pdf_text_async(
        self, text: str, camelot_tables: list[dict[str, Any]]
    ) -> dict[str, Any | None]:
        """
        One LLM call per ``schemas_dict`` schema, in parallel.

        Uses sync ``chain.invoke`` on the asyncio default thread pool (``asyncio.to_thread``).
        ``ChatGoogleGenerativeAI.ainvoke`` is unreliable under ``asyncio.run`` / nested loops and
        was returning failures for every schema while ``invoke`` works.
        """
        if not self.api_key:
            self._log.warning(
                "extract_metadata_from_pdf_text skipped: GOOGLE_API_KEY is missing or empty"
            )
            return dict.fromkeys(schemas_dict, None)

        pairs = await asyncio.gather(
            *(asyncio.to_thread(self.run_one_sync, name, text, camelot_tables) for name in schemas_dict)
        )
        return dict(pairs)

    def extract_metadata_from_pdf_text(self, text: str, camelot_tables: list[dict[str, Any]]) -> dict[str, Any | None]:
        """
        Tier-1 text extraction: parallel LLM calls (``gather`` inside
        :meth:`extract_metadata_from_pdf_text_async`). Blocks until all finish.
        Camelot tables are passed to the LLM to help it extract the metadata.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.extract_metadata_from_pdf_text_async(text, camelot_tables))

        def _run_in_fresh_loop() -> dict[str, Any | None]:
            return asyncio.run(self.extract_metadata_from_pdf_text_async(text, camelot_tables))

        self._log.debug(
            "extract_metadata_from_pdf_text: nested event loop — running parallel LLM "
            "batch in a worker thread"
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_run_in_fresh_loop).result()

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
