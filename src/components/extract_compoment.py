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

import pymupdf

def redact_doc(source_document: str, redact_phrases: list) -> None:
    doc = pymupdf.open(source_document)

    #page = doc.load_page(1)
    for page in doc:
        draft = []

        for phrase in redact_phrases:
            draft.extend(page.search_for(phrase))
            #print(draft)

        # redact given phrases
        for rect in draft:
            margin_x = 1.0  # points
            margin_y = 0.5

            smaller_rect = pymupdf.Rect(
                rect.x0 + margin_x,
                rect.y0 + margin_y,
                rect.x1 - margin_x,
                rect.y1 - margin_y
            )
            #annot = page.add_redact_annot(rect)

            annot = page.add_redact_annot(smaller_rect)
            #page.apply_redactions()

        # redact header and footer
        header_end = page.rect.height * 0.05
        header_rect = pymupdf.Rect(
            0,
            0,
            page.rect.width,
            header_end
        )
        page.add_redact_annot(header_rect)

        footer_start = page.rect.height * 0.965
        footer_rect = pymupdf.Rect(
            0,
            footer_start,
            page.rect.width,
            page.rect.height
        )
        page.add_redact_annot(footer_rect)

        # apply redactions
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)

    redacted_path = source_document.split("/")
    redacted_path.insert(-1, "redacted")
    redacted_path = '/'.join(redacted_path)

    from pathlib import Path
    Path(redacted_path).parent.mkdir(parents=True, exist_ok=True)

    # save the doc to a new PDF
    doc.save(redacted_path, garbage=3, deflate=True)

    return redacted_path

def convert_to_markdown(source_document: str, file_props: dict) -> str:
    if file_props["redact_phrases"]:
        source_document = redact_doc(source_document, file_props["redact_phrases"])
    
    result = _get_converter().convert(source_document)#, page_range=(5, len(PdfReader(source_document).pages))
    doc_content: str = result.document.export_to_markdown(page_break_placeholder="<!-- PAGE_BREAK -->")

    '''for item, level in result.document.iterate_items():
        print(
            item.label,
            repr(item.text if hasattr(item, "text") else ""),
            item.prov
        )
    return'''
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
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(header)
        file.write(content)

if __name__ == "__main__":
    file = "../data/NIST.SP.800-53Ar5.pdf"
    output_file = "./data-output/01-markdown/NIST.SP.800-53Ar5.md"

    text_result = convert_to_markdown(file)
    doc_metadata = extract_metadata(file)
    write_to_file(output_file, doc_metadata, text_result)
