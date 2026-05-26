import logging
import json
import re
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException
from typing import Any
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable
from pydantic import Field


def _message_content_to_str(content: Any) -> str:
    """
    LangChain message ``content`` is usually a string; Gemini / multimodal chains
    may return a list of blocks like ``[{"type": "text", "text": "..."}]``.
    Regex-based JSON cleanup requires a real string.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text")
                if t is not None:
                    parts.append(str(t))
                elif block.get("type") == "text" and isinstance(block.get("content"), str):
                    parts.append(block["content"])
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


class RobustJSONParser(Runnable):
    def __init__(self, parser: PydanticOutputParser):
        self.parser = parser
        # Get the target pydantic model for validation
        self.pydantic_model = self.parser.pydantic_object

    def invoke(self, input, config=None):
        if isinstance(input, (AIMessage, HumanMessage)):
            text = _message_content_to_str(input.content)
        elif isinstance(input, Field):
            text = None
        elif isinstance(input, dict):
            text = json.dumps(input)
        else:
            text = str(input)

        return self.parse(text)

    def _replace_none_str(self, obj: Any) -> Any:
        """Recursively replace the string 'None' with the object None."""
        if isinstance(obj, dict):
            return {k: self._replace_none_str(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._replace_none_str(elem) for elem in obj]
        elif obj == "None":
            return None
        else:
            return obj

    def parse(self, text: Any) -> Any:
        cleaned_text = ""
        try:
            if not isinstance(text, str):
                text = _message_content_to_str(text) if isinstance(text, list) else str(text)
            # 1. Sanitize the string to remove code fences and fix escapes
            cleaned_text = self._sanitize_json_output(text)

            # 2. Load the cleaned string into a Python dictionary
            data = json.loads(cleaned_text)

            # 3. NEW: Recursively replace all "None" strings with None objects
            cleaned_data = self._replace_none_str(data)

            # 4. Validate the cleaned dictionary against the Pydantic model
            return self.pydantic_model.model_validate(cleaned_data)

        except (json.JSONDecodeError, OutputParserException, Exception) as e:
            logging.error(f"Failed to parse and validate JSON: {e}")
            # As a fallback, try letting the original parser raise its specific error
            try:
                return self.parser.parse(cleaned_text)
            except Exception as final_e:
                logging.error(f"Final parsing attempt also failed: {final_e}")
                raise final_e

    def _sanitize_json_output(self, text: str) -> str:
        # Remove triple backticks and json marker
        text = re.sub(r"```(?:json)?", "", text, flags=re.DOTALL)
        text = text.strip()

        # Fix invalid escape sequences
        text = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)

        return text
