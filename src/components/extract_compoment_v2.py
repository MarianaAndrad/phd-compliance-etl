from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any

import pymupdf
import pymupdf4llm
from pypdf import PdfReader

logging.basicConfig(level=logging.INFO, format="EXTRACT COMPONENT -- %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def redact_doc(source_document: str | Path, file_props: dict, output_dir: str = "redacted") -> Path:
    """Permanently remove sensitive phrases and margin areas from a PDF.

    Returns the path to the newly written, redacted PDF. The original file
    is never modified.
    """
    source_path = Path(source_document)
    if not source_path.is_file():
        raise FileNotFoundError(f"Source document not found: {source_path}")

    doc = pymupdf.open(source_path)
    try:
        redact_phrases = file_props.get("redact_phrases", [])
        margins = file_props.get("redact_margins", {})

        for page in doc:
            for phrase in redact_phrases:
                for rect in page.search_for(phrase):
                    page.add_redact_annot(rect, fill=(1, 1, 1))

            if margins:
                width, height = page.rect.width, page.rect.height
                top = margins.get("top", 0)
                bottom = margins.get("bottom", 0)
                left = margins.get("left", 0)
                right = margins.get("right", 0)

                if top:
                    page.add_redact_annot(pymupdf.Rect(0, 0, width, top), fill=(1, 1, 1))
                if bottom:
                    page.add_redact_annot(pymupdf.Rect(0, height - bottom, width, height), fill=(1, 1, 1))
                if left:
                    page.add_redact_annot(pymupdf.Rect(0, 0, left, height), fill=(1, 1, 1))
                if right:
                    page.add_redact_annot(pymupdf.Rect(width - right, 0, width, height), fill=(1, 1, 1))

            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)

        redacted_path = source_path.parent / output_dir / source_path.name
        redacted_path.parent.mkdir(parents=True, exist_ok=True)

        doc.save(redacted_path, garbage=3, deflate=True)
        logger.info("Write redacted PDF to %s", redacted_path)

    finally:
        doc.close()

    return redacted_path

def convert_to_markdown(redacted_document: str | Path) -> str:
    """Convert an already-redacted PDF to Markdown text."""
    doc = pymupdf.open(redacted_document)
    logger.info("Opened redacted document: %s, pages: %d", redacted_document, doc.page_count)
    try:
        markdown = pymupdf4llm.to_markdown(
            doc,
            pages=list(range(doc.page_count)),
            header=False,
            footer=False,
            ignore_images=True,
            table_strategy="lines_strict",
        )
    finally:
        doc.close()

    return markdown

def clean_text(text: str) -> str:
    """Clean up text by removing extra whitespace and newlines, also remove any
    remaining HTML tags or formatting artifacts.
    """
    # Normalize line breaks encoded as HTML
    text = text.replace("-<br>", "")   # remove hyphenation before <br>
    text = text.replace("<br>", "\n")  # convert <br> to real newline

    # Remove any remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Strip trailing/leading whitespace on each line
    text = "\n".join(line.strip() for line in text.split("\n"))

    # Collapse 2+ consecutive newlines (with optional whitespace) into a single newline
    text = re.sub(r'\n\s*\n+', '\n', text)

    return text.strip()

def extract_metadata(source_document: str | Path) -> dict[str, str]:
    """Pull basic document metadata from the (original) PDF."""
    reader = PdfReader(source_document)
    meta = reader.metadata

    def field(name: str) -> str:
        value = getattr(meta, name, None) if meta else None
        return str(value) if value else ""

    return {
        "document_name": Path(source_document).name,
        "title": field("title"),
        "author": field("author"),
        "subject": field("subject"),
        "creation_date": field("creation_date"),
        "modification_date": field("modification_date"),
    }

def write_to_file(file_path: str | Path, metadata: dict[str, str], content: str) -> None:
    """Write a YAML-style front-matter header followed by Markdown content."""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    header_lines = [f"{key}: {value}" for key, value in metadata.items()]
    header = "---\n" + "\n".join(header_lines) + "\n---\n\n"

    with file_path.open("w", encoding="utf-8") as f:
        f.write(header)
        f.write(content)

    logger.info("Write Markdown output to %s", file_path)

def process_pdf(source_document: str | Path, output_file: str | Path, file_props: dict[str, Any]) -> None:
    """End-to-end pipeline: redact once, then derive markdown + metadata from it."""
    redacted_path = redact_doc(source_document, file_props)
    markdown = convert_to_markdown(redacted_path)
    metadata = extract_metadata(source_document)
    markdown_clean = clean_text(markdown)
    write_to_file(output_file, metadata, markdown_clean)

if __name__ == "__main__":
    DATA_FILES_DIR="../data"
    OUTPUT_DIR="../data-output/01-markdown"

    FILE_PROPS = {
        "redact_phrases": ["This page intentionally left blank"],
        "redact_margins": {
            "top": 50,
            "bottom": 40,
            "left": 0,
            "right": 0,
        },
    }
    for source_file in Path(DATA_FILES_DIR).glob("*.pdf"):
        output_file = Path(OUTPUT_DIR) / Path(source_file.name).with_suffix(".md")
        logger.info("Processing %s -> %s", source_file, output_file)
        process_pdf(source_file, output_file, FILE_PROPS)