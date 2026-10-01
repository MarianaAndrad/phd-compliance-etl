import asyncio
import logging
import os
import sys
import json


from components.extract_compoment import convert_to_markdown, extract_metadata, write_to_file
from components.transform_compoment import parse_md, dump_cdm_instances
from components.load_compoment import load_cdm_instances, persist_data
from components.indexer import index_data

from dependencies.database import get_mongo_client, get_elasticsearch_client

logger = logging.getLogger(__name__)

if os.name == 'nt':
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"


def load_metadata() -> dict:
    with open("metadata.json", "r", encoding="utf-8") as f:
        metadata = json.load(f)

    return metadata

async def run_pipeline(data_path: str, output_path: str) -> None:
    pipeline_components = "all"
    if len(sys.argv) > 1 and sys.argv[1][:2] == "--":
        if sys.argv[1][2:] in ["all", "extract", "transform", "load", "index"]:
            pipeline_components = sys.argv[1][2:]
        else:
            print("[ERROR] Unknown component argument, supported args: [--{all|extract|transform|load|index}]")
            return

    print("[INFO] Running " + pipeline_components + " component(s)")

    metadata = load_metadata()
    
    for file in os.listdir(data_path):
        if file[-4:] != ".pdf":
            continue

        input_file = os.path.join(data_path, file)
        base_name = os.path.splitext(file)[0]
        markdown_file = os.path.join(output_path, "01-markdown", f"{base_name}.md")
        cdm_file = os.path.join(output_path, "02-cdm-instances", f"{base_name}.json")
        #print("file:", file + "\ninput_file:", input_file + "\nbase_name:", base_name + "\nmarkdown_file:", markdown_file + "\ncdm_file:", cdm_file)
        
        # find metadata for current file
        framework_metadata = None
        for k, v in metadata.items():
            b_framework_match = False
            for i in range(len(v["file_props"]["keywords"])):
                if v["file_props"]["keywords"][i].lower() not in base_name.lower():
                    break
                elif i == len(v["file_props"]["keywords"]) - 1:
                    b_framework_match = True
            if b_framework_match:
                framework_metadata = metadata[k]
                print("[INFO] Found framework '" + k + "' metadata for file '" + file +"'")
                break

        if framework_metadata is None:
            print("[ERROR] No metadata found for file '" + file +"'")
            continue

        """import time
        times_arr = []
		
        for i in range(5):
            start = time.time()

            # load
            if pipeline_components in ["load", "all"]:
                mongodb_client = get_mongo_client()

                cdm_instances = load_cdm_instances(cdm_file)
                await persist_data(mongodb_client, framework_metadata["details"]["name"], cdm_instances)

            end = time.time()
            length = end - start
            times_arr.append(length)

        print("Average time:", sum(times_arr)/len(times_arr), "seconds")
        continue"""
        
        # extract
        if pipeline_components in ["extract", "all"]:
            text_result = convert_to_markdown(input_file, framework_metadata["file_props"])
            doc_metadata = extract_metadata(input_file)
            write_to_file(markdown_file, doc_metadata, text_result)

        # transform
        if pipeline_components in ["transform", "all"]:
            cdm_instances = parse_md(markdown_file, framework_metadata["details"])
            dump_cdm_instances(cdm_file, cdm_instances)
        
        # load
        if pipeline_components in ["load", "all"]:
            mongodb_client = get_mongo_client()

            cdm_instances = load_cdm_instances(cdm_file)
            await persist_data(mongodb_client, framework_metadata["details"]["name"], cdm_instances)

        # index
        if pipeline_components in ["index", "all"]:
            es_client = get_elasticsearch_client()

            cdm_instances = load_cdm_instances(cdm_file)
            index_data(es_client, cdm_instances)



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data_folder = "./data/"
    data_output_folder = "./data-output/"

    asyncio.run(run_pipeline(data_folder, data_output_folder))



