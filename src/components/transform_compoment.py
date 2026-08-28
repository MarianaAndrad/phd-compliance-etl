#from dependencies.database import get_database

import re
import json
import asyncio

from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from typing import Dict
from enum import Enum

from schemas.catalog import CatalogModel, MetadataModel
from schemas.control import ControlModel


def UTIL_string_append(dest, source):
    if dest and dest[-1] != "\n":
        if (dest[-1] in ".;:!?|") or ('|' in source): # NOTE: The second condition is used to fix a case in ISO 27002 parsing (transition between Table 1 title and its contents)
            dest += "\n"
        elif dest[-1] != " ":
            dest += " "
    
    return dest + source


def UTIL_get_control_lvl(control):
    if control is not None:
        return control.ref_code.count(".") + 1

    return None


class ControlStates(Enum):
    NONE  = 0
    START = 1
    DESCRIPTION = 2
    PURPOSE = 3
    GUIDANCE = 4
    OTHER_INFORMATION = 5
    MEANS_OF_VERIFICATION = 6
    ATTRIBUTES = 7


# NOTE: Sequence conditions specifically for the ISO 27002 standard, needs to be adapted for other norms
G_FRAMEWORK_SEQUENCE_STATE_CONDITIONS = {
    "doc_start_controls": lambda line: "## 5 Organizational controls".lower() in line.lower(),
    "doc_end_controls": lambda line: "## A.1	 General".lower() in line.lower(),

    "new_control": lambda line: re.search(r"^##\s+\d+", line), #"^##\\s+\\d+"
    
    "control_description": lambda line: "## Control".lower() in line.lower(),
    "control_purpose": lambda line: "## Purpose".lower() in line.lower(),
    "control_guidance": lambda line: "## Guidance".lower() in line.lower(),
    "control_other_information": lambda line: "## Other information".lower() in line.lower(),
    "control_means_of_verification": lambda line: "## Means of verification".lower() in line.lower(),
    "control_attributes": lambda line: "## Attributes".lower() in line.lower()
}


# state machine parser function
def parse_md(md_path: str, catalog_metadata: str) -> Dict:
    global G_FRAMEWORK_SEQUENCE_STATE_CONDITIONS
    
    b_control_start = False
    control_state = ControlStates.NONE
    controls_list = []

    cur_control = None
    parent_controls = {}

    def _add_cur_control():
        nonlocal cur_control # avoid python treating cur_control as a local function variable when we assign cur_control some value inside this function
        
        if cur_control is not None:
            if cur_control.description and cur_control.description[-1] == "\n":
                cur_control.description = cur_control.description[:-1]
            if cur_control.purpose and cur_control.purpose[-1] == "\n":
                cur_control.purpose = cur_control.purpose[:-1]
            if cur_control.guidance and cur_control.guidance[-1] == "\n":
                cur_control.guidance = cur_control.guidance[:-1]
            if cur_control.other_information and cur_control.other_information[-1] == "\n":
                cur_control.other_information = cur_control.other_information[:-1]

            # level 1 controls are root parents
            if UTIL_get_control_lvl(cur_control) > 1:
                cur_control.parent_slug = parent_controls[UTIL_get_control_lvl(cur_control) - 1].slug

            # update parent control levels dict
            parent_controls[UTIL_get_control_lvl(cur_control)] = cur_control

            controls_list.append(cur_control)
            cur_control = None

    catalog = CatalogModel(
        uuid=str(uuid4()),
        metadata=MetadataModel(
            type=catalog_metadata["type"],
            name=catalog_metadata["name"],
            publisher=catalog_metadata["publisher"]
        )
    )

    with open(md_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if G_FRAMEWORK_SEQUENCE_STATE_CONDITIONS["doc_start_controls"](line):
                b_control_start = True

            if b_control_start:
                # end of controls sequence, insert last filled control
                if G_FRAMEWORK_SEQUENCE_STATE_CONDITIONS["doc_end_controls"](line):
                    control_state = ControlStates.NONE
                    #b_control_start = False
                    _add_cur_control()

                # new control
                elif G_FRAMEWORK_SEQUENCE_STATE_CONDITIONS["new_control"](line):
                    control_state = ControlStates.START
                    _add_cur_control()

                    line = ' '.join(line.split()) # convert multi spacings to single spacing
                    cur_ref_code = re.search(r"\d+(:?\.\d+)*", line) # NOTE: ":?" defines the group as non-capturing (avoids storing group matched sub-strings)

                    #print("ENTERED CONTROL: " + line + " | control = " + cur_ref_code.group(0) + ", title = '" + line[cur_ref_code.end() + 1:] + "'")
                    cur_control = ControlModel(
                        catalog_uuid=catalog.uuid,
                        ref_code=cur_ref_code.group(0),
                        title=line[cur_ref_code.end() + 1:],
                        slug=cur_ref_code.group(0) + "-" + '-'.join(line[cur_ref_code.end() + 1:].lower().split()),
                        category=parent_controls[1].title if 1 in parent_controls else line[cur_ref_code.end() + 1:]
                    )

                    #print(cur_ref_code.group(0), "->", get_cur_control_lvl())

                # control description
                elif G_FRAMEWORK_SEQUENCE_STATE_CONDITIONS["control_description"](line):
                    control_state = ControlStates.DESCRIPTION; continue
                # control purpose
                elif G_FRAMEWORK_SEQUENCE_STATE_CONDITIONS["control_purpose"](line):
                    control_state = ControlStates.PURPOSE; continue
                # control guidance
                elif G_FRAMEWORK_SEQUENCE_STATE_CONDITIONS["control_guidance"](line):
                    control_state = ControlStates.GUIDANCE; continue
                # other information
                elif G_FRAMEWORK_SEQUENCE_STATE_CONDITIONS["control_other_information"](line):
                    control_state = ControlStates.OTHER_INFORMATION; continue

                # skip random unknown control sequences
                if line.startswith("#"): #re.search(r"^#+", line):
                    continue

                line = line.replace("\u00A0", " ") # replace non-breaking spaces with normal spaces
                if any(ord(char) > 127 for char in line): # ignore lines containing non ascii chars
                    continue

                line = re.sub(r"\( (.)", r"(\1", line)
                line = re.sub(r"(.) \)", r"\1)", line)
                line = re.sub(r"\x08", "", line) # 0x08 -> backspace hex char code #line = line.replace("\b", "")

                line = ' '.join(line.split()) # convert multi spacings to single spacing

                # control description
                if control_state == ControlStates.DESCRIPTION:
                    #print("CONTROL", cur_control.ref_code, "DESCRIPTION:", line)
                    cur_control.description = UTIL_string_append(cur_control.description, line)
                # control purpose
                elif control_state == ControlStates.PURPOSE:
                    cur_control.purpose = UTIL_string_append(cur_control.purpose, line)
                # control guidance
                elif control_state == ControlStates.GUIDANCE:
                    cur_control.guidance = UTIL_string_append(cur_control.guidance, line)
                # other information
                elif control_state == ControlStates.OTHER_INFORMATION:
                    cur_control.other_information = UTIL_string_append(cur_control.other_information, line)

    if cur_control and cur_control not in controls_list:
        _add_cur_control()

    for control in controls_list:
        print(control.model_dump_json(indent=2))
        #print(control.ref_code, " -> ", control.parent_slug)

    return { "catalog": catalog, "controls_list": controls_list }


def dump_cdm_instances(file_path: str, cdm_instances: Dict) -> None:
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump({
            "catalog": cdm_instances["catalog"].model_dump(),
            "controls_list": [control.model_dump() for control in cdm_instances["controls_list"]]
            },
        f, indent=2)




if __name__ == "__main__":
    document_path = "./data-output/01-markdown/i.s.eniso-iec27002-2022-v2.00_pdf.md"
    output_file = "./data-output/02-cdm-instances/i.s.eniso-iec27002-2022-v2.00_pdf.json"

    controls_list = parse_md(document_path)
    dump_cdm_instances(output_file, controls_list)

    #asyncio.run(persist_data(controls_list))
