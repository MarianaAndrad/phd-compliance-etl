import asyncio
import logging
import os
import uuid
import sys


from components.extract_compoment import convert_to_markdown, extract_metadata, write_to_file
from components.transform_compoment import parse_md, dump_cdm_instances
from components.load_compoment import load_cdm_instances, persist_data

from dependencies.database import get_db_client

logger = logging.getLogger(__name__)

if os.name == 'nt':
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"


async def run_pipeline(data_path: str, output_path: str) -> None:
    pipeline_components = "all"
    if len(sys.argv) > 1 and sys.argv[1][:2] == "--":
        if sys.argv[1][2:] in ["extract", "transform", "load"]:
            pipeline_components = sys.argv[1][2:]
        else:
            print("[ERROR] Unknown component argument, supported args: [--{extract|transform|load}]")
            return

    print("[INFO] Running " + pipeline_components + " component(s)")

    iso27002_metadata = {
        "type": "standard",
        "name": "iso27002",
        "publisher": "ISO/IEC"
    }
    
    for file in os.listdir(data_path):
        if file[-4:] != ".pdf":
            continue

        input_file = os.path.join(data_path, file)
        base_name = os.path.splitext(file)[0]
        markdown_file = os.path.join(output_path, "01-markdown", f"{base_name}.md")
        cdm_file = os.path.join(output_path, "02-cdm-instances", f"{base_name}.json")
        #print("file:", file + "\ninput_file:", input_file + "\nbase_name:", base_name + "\nmarkdown_file:", markdown_file + "\ncdm_file:", cdm_file)
        
        # extract
        if pipeline_components in ["extract", "all"]:
            text_result = convert_to_markdown(input_file)
            doc_metadata = extract_metadata(input_file)
            write_to_file(markdown_file, doc_metadata, text_result)

        # transform
        if pipeline_components in ["transform", "all"]:
            cdm_instances = parse_md(markdown_file, iso27002_metadata)
            dump_cdm_instances(cdm_file, cdm_instances)
        
        # load
        if pipeline_components in ["load", "all"]:
            mongodb_client = get_db_client()

            cdm_instances = load_cdm_instances(cdm_file)
            await persist_data(mongodb_client, iso27002_metadata["name"], cdm_instances)
    



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data_folder = "./data/"
    data_output_folder = "./data-output/"

    asyncio.run(run_pipeline(data_folder, data_output_folder))



