from typing import Dict, List, Tuple, Type, TypeVar

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


def extract_entities(document_text: str, schema: Type[T], key_fields: List[str] | None = None) -> List[T]:
    """Splits `document_text` into chunks and extracts a list of `schema`
    instances from each chunk via structured output (no manual JSON parsing).

    `key_fields` are the natural-key field(s) of `schema` (e.g. ["slug"] or
    ["ref_code"]) used to flag conflicting near-duplicate extractions. Pass
    None to skip that check.
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
        result = None
        try:
            result = structured_llm.invoke([system_message, HumanMessage(content=chunk)])
        except Exception as e:
            print(f"  [chunk parse failed] {e}")
        if result is None:
            print(f"  Skipping chunk after 5 failed attempts (chunk preview: {chunk[:120]!r}...)")
            continue

        for item in result.items:
            errors = validate_required_fields(item) + validate_field_content(item)
            if errors:
                print(f"  [validation failed] {item!r}: {'; '.join(errors)}")
                continue
            all_results.append(item)

    seen = set()
    deduped_results: List[T] = []
    for item in all_results:
        key = item.model_dump_json()
        if key not in seen:
            seen.add(key)
            deduped_results.append(item)

    if key_fields:
        for key, group in find_conflicting_duplicates(deduped_results, key_fields).items():
            print(f"  [possible duplicate] {dict(zip(key_fields, key))}: {len(group)} conflicting extractions")

    return deduped_results

def save_result(file_path: str, result: T) -> None:
    with open(file_path, "w") as f:
        f.write(result.model_dump_json(indent=2))

# ---------------------------------------------------------------------------
# Validation gates
# ---------------------------------------------------------------------------
# Pydantic already guarantees each required field is present and has the
# right Python type, but the LLM can still satisfy that with junk (blank
# strings, placeholder text). These gates catch that before an item is
# accepted into the results.

PLACEHOLDER_VALUES = {
    "n/a", "na", "none", "null", "unknown", "tbd",
    "not specified", "not provided", "not mentioned", "not applicable",
}


def validate_required_fields(item: T) -> List[str]:
    """Flags required fields (per the pydantic schema) that are present but
    effectively empty — blank/whitespace-only strings, empty lists/dicts —
    which pydantic's required-field check does not catch on its own."""
    errors = []
    for name, field_info in type(item).model_fields.items():
        if not field_info.is_required():
            continue
        value = getattr(item, name)
        if value is None:
            errors.append(f"'{name}' is required but missing")
        elif isinstance(value, str) and not value.strip():
            errors.append(f"'{name}' is required but empty")
        elif isinstance(value, (list, dict)) and len(value) == 0:
            errors.append(f"'{name}' is required but empty")
    return errors


def validate_field_content(item: T) -> List[str]:
    """Flags string fields whose value is a placeholder the LLM sometimes
    emits instead of leaving the field out (e.g. 'N/A', 'unknown'), i.e.
    the field has the right *type* but not the right *type of information*."""
    errors = []
    for name, value in item.model_dump().items():
        if isinstance(value, str) and value.strip().lower() in PLACEHOLDER_VALUES:
            errors.append(f"'{name}' looks like a placeholder value: {value!r}")
    return errors


def find_conflicting_duplicates(items: List[T], key_fields: List[str]) -> Dict[Tuple, List[T]]:
    """Groups items sharing the same `key_fields` (e.g. slug/ref_code) whose
    full content still differs. Exact duplicates are already deduped by
    `extract_entities`; this surfaces the remaining case where the model
    extracted the *same* entity twice with conflicting details, so it can be
    reviewed instead of silently kept as two records or silently merged."""
    groups: Dict[Tuple, List[T]] = {}
    for item in items:
        dumped = item.model_dump()
        key = tuple(dumped.get(field_name) for field_name in key_fields)
        groups.setdefault(key, []).append(item)

    return {
        key: group
        for key, group in groups.items()
        if len(group) > 1 and len({item.model_dump_json() for item in group}) > 1
    }

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


    results = extract_entities(document_text, Control, key_fields=["slug"])

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



