import asyncio
import logging
import os
import uuid

from components.extract_compoment import convert_to_markdown, extract_metadata, write_to_file
from components.load_compoment import persist_catalog
from components.transformer_compoment import extract_entities, load_document
from dependencies.database import get_database
from schemas.catalog import Metadata
from schemas.control import Control

logger = logging.getLogger(__name__)


async def run_pipeline(data_path: str, output_path: str) -> None:
    async for db in get_database():
        for file in os.listdir(data_path):
            input_file = os.path.join(data_path, file)
            base_name = os.path.splitext(file)[0]
            markdown_file = os.path.join(output_path, "01-markdown", f"{base_name}.md")
            cdm_file = os.path.join(output_path, "02-cdm-instances", f"{base_name}.json")

            text_result = convert_to_markdown(input_file)
            doc_metadata = extract_metadata(input_file)
            write_to_file(markdown_file, doc_metadata, text_result)

            document_text = load_document(markdown_file)
            controls = extract_entities(document_text, Control)

            with open(cdm_file, "w") as f:
                f.write("[\n")
                for control in controls:
                    f.write(f"  {control.model_dump_json()},\n")
                f.write("]\n")

            catalog_metadata_candidates = extract_entities(document_text, Metadata)
            if not catalog_metadata_candidates:
                logger.warning("No catalog metadata extracted for %s, skipping persistence.", file)
                continue

            catalog_uuid = str(uuid.uuid4())
            await persist_catalog(db, catalog_uuid, catalog_metadata_candidates[0], controls)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data_folder = "./data/"
    data_output_folder = "./data-output/"

    asyncio.run(run_pipeline(data_folder, data_output_folder))



