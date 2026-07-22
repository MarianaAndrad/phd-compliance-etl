from typing import List, Type, TypeVar

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, create_model, Field
from tqdm import tqdm

from llm import build_llm, build_structured_llm

llm = build_llm() #TODO: CHANGE THIS TO GET TO THE SETTINGS
T = TypeVar("T", bound=BaseModel)

def load_document(path: str) -> str:
    with open(path, "r") as f:
         return f.read()

def splitter_text() -> RecursiveCharacterTextSplitter:
    """Creates a RecursiveCharacterTextSplitter that splits on characters."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=100,
    )
    return splitter


def extract_entities(document_text: str, schema: Type[T]) -> List[T]:
    """Splits `document_text` into chunks and extracts a list of `schema`
    instances from each chunk via structured output (no manual JSON parsing).
    """
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
        tries = 0
        result = None
        while tries < 5:
            try:
                result = structured_llm.invoke([system_message, HumanMessage(content=chunk)])
                break
            except Exception as e:
                print(f"  [chunk parse failed, attempt {tries + 1}/5] {e}")
                tries += 1
        if result is None:
            print(f"  Skipping chunk after 5 failed attempts (chunk preview: {chunk[:120]!r}...)")
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

def save_result(file_path: str, result: T) -> None:
    with open(file_path, "w") as f:
        f.write(result.model_dump_json(indent=2))


if __name__ == "__main__":

    class Control(BaseModel):
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
    # -----------------------------------------------------------------------
    # Documento de exemplo (na prática, vem de um ficheiro .txt, .pdf, .docx...)
    # -----------------------------------------------------------------------
    document_path = "../data-output/01-markdown/NIST.SP.800-53r52.md"
    document_text = load_document(document_path)
    document_text = document_text[20000:]


    results = extract_entities(document_text, Control)

    print("Resultado final:")
    print("[")
    for control in results:
        print(f"  {control.model_dump_json()},")
    print("]")


    ## SAVE this a document json please
    with open("../data-output/02-cdm-instances/NIST.SP.800-53r52.json", "w") as f:
        f.write("[\n")
        for control in results:
            f.write(f"  {control.model_dump_json()},\n")
        f.write("]\n")



