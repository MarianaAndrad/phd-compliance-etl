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

def redact_doc(source_document: str, file_props: dict) -> None:
    doc = pymupdf.open(source_document)

    #page = doc.load_page(1)
    for page in doc:
        draft = []

        for phrase in file_props.get("redact_phrases", []):
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

        if "redact_margins" in file_props:
            # redact margins
            top_margin_end = page.rect.height * file_props["redact_margins"].get("top_y_end_percent", 0)
            top_rect = pymupdf.Rect(0, 0, page.rect.width, top_margin_end)
            page.add_redact_annot(top_rect)

            bottom_margin_start = page.rect.height * file_props["redact_margins"].get("bottom_y_start_percent", 1)
            footer_rect = pymupdf.Rect(0, bottom_margin_start, page.rect.width, page.rect.height)
            page.add_redact_annot(footer_rect)


            left_margin_end = page.rect.width * file_props["redact_margins"].get("left_x_end_percent", 0)
            left_rect = pymupdf.Rect(0, 0, left_margin_end, page.rect.height)
            page.add_redact_annot(left_rect)

            right_margin_start = page.rect.width * file_props["redact_margins"].get("right_x_start_percent", 1)
            right_rect = pymupdf.Rect(right_margin_start, 0, page.rect.width, page.rect.height)
            page.add_redact_annot(right_rect)

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

import re
import io

G_MAX_TITLE_WORD_COUNT = 18
G_MAX_TITLE_CHAR_COUNT = 150

def convert_to_markdown(source_document: str, file_props: dict) -> str:
    source_document = redact_doc(source_document, file_props)
    
    #result = _get_converter().convert(source_document, page_range=(48, 51))#, page_range=(5, len(PdfReader(source_document).pages))
    #doc_content: str = result.document.export_to_markdown(page_break_placeholder="<!-- PAGE_BREAK -->")

    #result = parser.from_file(source_document)
    #doc_content: str = result["content"]

    #parsed = parser.from_file(str(source_document))
    #final_doc_content = (parsed["content"] or "").strip()

    #return final_doc_content
    #print(doc_content)


    def _is_title_candidate(strg, search=re.compile(r'[^a-zA-Z0-9:|.,()/\-\s]').search):
        if len(strg) > G_MAX_TITLE_CHAR_COUNT or len(strg.split()) > G_MAX_TITLE_WORD_COUNT or strg.strip()[-1] == '.':
            return False
        return not bool(search(strg))

    def _get_block_font_size(block):
        text_size = None
        if block["type"] == 0:  # text block
            for line in block["lines"]:
                for span in line["spans"]:
                    if not span["text"].isspace():
                        if not text_size:
                            text_size = span['size']
                        elif abs(span['size'] - text_size) > 3: # if difference between text within the same block is too high, return error value
                            return None
        return text_size

    def _is_text_continuation(prev_block, block):
        prev_block_font_size = _get_block_font_size(prev_block)
        block_font_size = _get_block_font_size(block)

        if not prev_block_font_size or not block_font_size:
            return False

        return abs(prev_block_font_size - block_font_size) < 5
    
    def _non_ascii_to_html(text):
        return ''.join(
            f'&#x{ord(c):x};' if ord(c) > 127 else c
            for c in text
        )

    def _normalize_non_ascii(text):
        text = _non_ascii_to_html(text)
        text = text.replace("&#x2013;", ' - ')
        text = text.replace("&#x2014;", ' - ')
        text = text.replace("&#x201c;", '\"')
        text = text.replace("&#x201d;", '\"')
        text = text.replace("&#x2019;", '\'')
        text = text.replace("&#x2026;", '...')
        text = text.replace("&#x2022;", '-')
        return text

    def _should_merge_title():
        return (prev_block and prev_block["bbox"][3] > block["bbox"][1] and
                    block["bbox"][0] >= prev_block["bbox"][0] and
                    _is_text_continuation(prev_block, block) and
                    _is_title_candidate(prev_block_text) and _is_title_candidate(block_text) and
                    prev_block_text.isupper() == block_text.isupper() and
                    len(prev_block_text.split()) + len(block_text.split()) <= G_MAX_TITLE_WORD_COUNT)

    doc = pymupdf.open(source_document)

    doc_content = ""
    for page in doc:
        blocks = page.get_text("dict")["blocks"]
        prev_block = None
        prev_block_text = ""
        for block in blocks:
            #print(block)
            block_text = ""
            if block["type"] == 0:  # text block
                for line in block["lines"]:
                    for span in line["spans"]:
                        #print(f"{span['text']!r}  font={span['font']}  size={span['size']:.1f}")
                        block_text += span["text"]

                block_text = _normalize_non_ascii(block_text)

                doc_content += prev_block_text
                #prev_block_text = ""

                # title merge composite check
                if not _should_merge_title():
                    doc_content += '\n'
                #else:
                #    print("BLOCKS SHOULD MERGE!", prev_block_text, "(size =", _get_block_font_size(prev_block),
                #        _is_title_candidate(prev_block_text) ,") ||| ", block_text, "(size =", _get_block_font_size(block), _is_title_candidate(block_text), ")")

                prev_block = block
                prev_block_text = block_text

        doc_content += prev_block_text


    return doc_content

    doc = pymupdf.open(source_document)
    doc_content = ""
    for page in doc:
        xhtml = page.get_text("xhtml")
        #markdown = md(xhtml)

        text = re.sub(r"<.*?>", r"", xhtml) # "?" affects its preceeding operator "*", making it non-greedy
        text = re.sub(r"<img\b[^>]*>", "", text, flags=re.DOTALL) # \b demarks word boundary
        #print(text, "\n")
        doc_content += text

    s = io.StringIO(doc_content)
    final_doc_content = ""
    prev_line = ""
    for line in s:
        line = line.rstrip('\r\n')

        if not (prev_line and prev_line[-1].isspace() and ',' not in prev_line and prev_line.isupper() and line.isupper()):# or prev_line[-1] not in string.punctuation:
            final_doc_content += '\n'

        final_doc_content += line

        prev_line = line

    """min_l, min_t = float('inf'), float('inf')
    cur_page, cur_item = 0, None
    for item, level in result.document.iterate_items():
        if cur_page != item.prov[0].page_no:
            cur_page = item.prov[0].page_no
            min_l = float('inf')
            min_t = float('inf')
            
        if item.prov[0].bbox.t < min_t:
            min_t = item.prov[0].bbox.t
            cur_item = item
        else:
            print(f"[WARNING] Page {item.prov[0].page_no}: Item '{item.text}' is higher up than '{cur_item.text}'")
        #if item.prov.bbox.l < min_l:
        #    min_l = item.prov.bbox.l
        #else:
        #    print("WARNING: ")
        '''print(
            item.label,
            repr(item.text if hasattr(item, "text") else ""),
            item.prov
        )'''"""
    return final_doc_content
    #return doc_content

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
