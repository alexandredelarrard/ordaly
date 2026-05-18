"""
LLM bridge for PDF parsing — same patterns as GptGetter (prompts + RobustJSONParser + LangChain)
without DB/SqlHelper (safe for Celery workers without Postgres).
"""

from __future__ import annotations

import base64
import logging
from os.path import abspath, dirname
from pathlib import Path
from typing import Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from omegaconf import DictConfig

from src.context import AppContext
from src.gpt_extraction.utils_genai.customed_parser import RobustJSONParser
from src.schemas.parse_pipeline import MetadataFromText, VisionTableExtraction

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

    def _metadata_chain(self):
        if not self._google_api_key():
            return None

        system = self._read("parse_metadata_system_prompt.md")
        user = self._read("parse_metadata_prompt.md")

        parser = PydanticOutputParser(pydantic_object=MetadataFromText)
        robust = RobustJSONParser(parser)
        prompt = PromptTemplate(
            template=system + "\n\n" + user,
            input_variables=["query"],
            partial_variables={
                "_format": parser.get_format_instructions()
            },
        )
        llm = ChatGoogleGenerativeAI(
            model=self.model_text,
            google_api_key=self._google_api_key(),
            temperature=self.temperature,
            max_output_tokens=self.max_token,
        )
        return prompt | llm | robust

    def extract_metadata_from_pdf_text(self, text: str) -> Optional[MetadataFromText]:
        """Tier-1 textual metadata — same role as GptGetter structured extract, single shot."""
        chain = self._metadata_chain()
        if chain is None:
            self._log.debug("No GOOGLE_API_KEY — skip metadata LLM")
            return None
        try:
            out = chain.invoke({"query": text[:120_000]})
            if isinstance(out, MetadataFromText):
                return out
            return MetadataFromText.model_validate(out)
        except Exception as exc:
            self._log.exception("Metadata LLM failed: %s", exc)
            return None

    def _vision_chain(self):

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
            model=self.model_vision,
            google_api_key=self.api_key,
            temperature=self.temperature,
            max_output_tokens=self.max_token,
        )
        return prompt | llm | robust

    def extract_table_from_page_image(
        self,
        png_bytes: bytes,
        page_label: str
    ) -> Optional[VisionTableExtraction]:
        """Tier-2 vision: page image → structured table (Gemini multimodal)."""
        
        chain = self._vision_chain()
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
