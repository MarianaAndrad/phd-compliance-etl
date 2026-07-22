from typing import Type

from langchain_ollama import ChatOllama
from pydantic import BaseModel


def build_llm(
    base_url: str = "http://10.42.0.10:11434",
    model: str = "qwen3.5:4b",
    temperature: float = 0.0,
) -> ChatOllama:
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