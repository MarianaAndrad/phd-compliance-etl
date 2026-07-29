import asyncio
import logging
import uuid
from typing import List, Type, TypeVar

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, create_model, Field
from tqdm import tqdm

from dependencies.database import get_database
from dependencies.llm import build_llm, build_structured_llm

logger = logging.getLogger(__name__)

llm = build_llm()
T = TypeVar("T", bound=BaseModel)

TEST_COLLECTION_NAME = "transformer_test_controls"

def load_document(path: str) -> str:
    with open(path, "r") as file:
         return file.read()

def splitter_text() -> RecursiveCharacterTextSplitter:
    """Creates a RecursiveCharacterTextSplitter that splits on characters."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=100,
    )
    return splitter


def extract_entities(document_text: str, schema: Type[T]) -> List[T]:
    extraction_result = create_model(
        "ExtractionResult",
        items=(List[schema], ...),  # type: ignore[valid-type]  # schema is a runtime type, not a literal
    )
    structured_llm = build_structured_llm(llm, extraction_result)

    system_message = SystemMessage(
        content=f"""I want you to extract every entity matching the schema below mentioned in the following text chunk. If none is mentioned, return an empty list.

{schema.model_json_schema()}"""
    )

    chunks = splitter_text().split_text(document_text)
    all_results: List[T] = []

    for chunk in tqdm(chunks):
        result = None
        try:
            result = structured_llm.invoke([system_message, HumanMessage(content=chunk)])
        except Exception as e:
            logger.warning("Chunk parse failed: %s", e)
        if result is None:
            logger.warning("Skipping chunk after failed attempt (chunk preview: %r...)", chunk[:120])
            continue

        all_results.extend(result.items)

    seen = set()
    deduped_results: List[T] = []
    for item in all_results:
        key = item.model_dump_json()
        if key not in seen:
            seen.add(key)
            deduped_results.append(item)

    return deduped_results

# ---------------------------------------------------------------------------
# Validation gates (AFTER extraction, BEFORE persistence)
# ---------------------------------------------------------------------------
# TODO IMPLEMENTED


def save_result(file_path: str, result: T) -> None:
    with open(file_path, "w") as f:
        f.write(result.model_dump_json(indent=2))


async def persist_test_results(db: AsyncIOMotorDatabase, catalog_uuid: str, results: List[BaseModel]) -> None:
    """Upserts extracted items into the test collection, keyed by (catalog_uuid, slug)."""
    for result in results:
        payload = result.model_dump()
        await db[TEST_COLLECTION_NAME].update_one(
            {"catalog_uuid": catalog_uuid, "slug": payload["slug"]},
            {"$set": payload},
            upsert=True,
        )


async def main_test() -> None:

    class ExtractedControl(BaseModel):
        ref_code: str = Field(
            ...,
            title="Reference Code",
            description="Official reference code of the control (e.g. 'A.5.1', 'AC-2').",
            min_length=1,
        )

        title: str = Field(
            ...,
            alias="title",
            title="Title",
            description="Short title/name of the control.",
            min_length=1,
        )

        slug: str = Field(
            ...,
            title="Slug",
            description=" Unique, human-readable, URL-friendly identifier for this control ( <ref-code>-<short-title>), e.g. 'ac-2-account-management'.",
            min_length=1,
        )

        description: str = Field(
            ...,
            title="Description",
            description="General description of the control.",
            min_length=1,
        )

    document_path = "./data-output/01-markdown/NIST.SP.800-53r52.md"
    output_file = "./data-output/02-cdm-instances/NIST.SP.800-53r52.v2.json"
    document_text = load_document(document_path)
    document_text = document_text[len(document_text)//2 - 10000:len(document_text)//2 + 10000]

    results = extract_entities(document_text, ExtractedControl)

    logger.info("Results:")
    for control in results:
        logger.info("  %s,", control.model_dump_json())

    catalog_uuid = str(uuid.uuid4())
    async for db in get_database():
        await persist_test_results(db, catalog_uuid, results)

    with open(output_file, "w") as f:
        f.write("[\n")
        for control in results:
            f.write(f"  {control.model_dump_json()},\n")
        f.write("]\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main_test())

