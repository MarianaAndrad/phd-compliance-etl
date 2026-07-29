import logging
from typing import Type

from langchain_ollama import ChatOllama
from pydantic import BaseModel

from core.config import settings

logger = logging.getLogger(__name__)

def build_llm(
    base_url: str = settings.LLM_BASE_URL,
    model: str = settings.LLM_MODEL,
    temperature: float = 0.0,
) -> ChatOllama:
    logger.info("Building LLM client for base_url=%s model=%s", base_url, model)
    return ChatOllama(
        model=model,
        base_url=base_url,
        api_key="not-needed",
        num_ctx=16384,
        temperature=temperature,
        reasoning=False,
    )

def build_structured_llm(llm: ChatOllama, schema: Type[BaseModel]):
    """Binds the ExtractionResult schema to the model via tool calling."""
    return llm.with_structured_output(schema)