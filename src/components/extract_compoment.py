import os
from typing import Any
from docling.document_converter import DocumentConverter
from pypdf import PdfReader

converter: DocumentConverter = None

def _get_converter() -> DocumentConverter:
    global converter
    if converter is None:
        converter = DocumentConverter()
    return converter

def convert_to_markdown(source_document: str) -> str:
    result = _get_converter().convert(source_document)
    doc_content: str = result.document.export_to_markdown()
    return doc_content

def extract_metadata(source_document: str) -> dict:
    reader = PdfReader(source_document)
    meta_document = reader.metadata
    metadata: dict = {
        "document_name": os.path.basename(source_document),
        "title": meta_document.title if meta_document else "",
        "author": meta_document.author if meta_document else "",
        "subject": meta_document.subject if meta_document else "",
        "creation_date": meta_document.creation_date if meta_document else "",
        "modification_date": meta_document.modification_date if meta_document else "",
    }
    return metadata

def write_to_file(file_path: str, metadata:dict, content: Any) -> None:
    header_line = [f"{chave}: {valor}" for chave, valor in metadata.items()]
    header = "---\n" + "\n".join(header_line) + "\n---\n\n"
    with open(file_path, "w") as file:
        file.write(header)
        file.write(content)

if __name__ == "__main__":
    file = "../data/NIST.SP.800-53Ar5.pdf"
    output_file = "./data-output/01-markdown/NIST.SP.800-53Ar5.md"

    text_result = convert_to_markdown(file)
    doc_metadata = extract_metadata(file)
    write_to_file(output_file, doc_metadata, text_result)
