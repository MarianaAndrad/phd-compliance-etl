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
    if dest and dest[-1] != '\n' and dest[-1] != ' ':
        dest += '\n'

    if source and source[0].islower():
        if dest and dest[-1] == '\n':
            dest = dest[:-1] + ' '
        elif dest and dest[-1] != ' ':
            dest += ' '

    if "<!-- PAGE_BREAK -->" in source:
        return dest
    
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
G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS = {
    "iso27001": {
        "doc_start_controls": lambda line: "## 4 Context of the organization".lower() in line.lower(),
        "doc_end_controls": lambda line: "## Annex A".lower() in line.lower(),

        "new_control": lambda line: re.search(r"^##\s+\d+", line), #"^##\\s+\\d+"
        
        "control_description": lambda line: re.search(r"^##\s+\d+", line),
        "control_purpose": lambda line: False,
        "control_guidance": lambda line: False,
        "control_other_information": lambda line: False,
        "control_means_of_verification": lambda line: False,
        "control_attributes": lambda line: False
    },
    "iso27002": {
        "doc_start_controls": lambda line: "## 5 Organizational controls".lower() in line.lower(),
        "doc_end_controls": lambda line: "## A.1	 General".lower() in line.lower(),

        "new_control": lambda line: re.search(r"^##\s+\d+", line), #"^##\\s+\\d+"
        
        "control_description": lambda line: "## Control".lower() in line.lower(),
        "control_purpose": lambda line: "## Purpose".lower() in line.lower(),
        "control_guidance": lambda line: "## Guidance".lower() in line.lower(),
        "control_other_information": lambda line: "## Other information".lower() in line.lower(),
        "control_means_of_verification": lambda line: "## Means of verification".lower() in line.lower(),
        "control_attributes": lambda line: re.search(r"^##\s+\d+", line)#lambda line: "## Attributes".lower() in line.lower()
    },
    "iso27005": {
        "doc_start_controls": lambda line: "## 5 Information security risk management".lower() in line.lower(),
        "doc_end_controls": lambda line: "## Annex A".lower() in line.lower(),

        "new_control": lambda line: re.search(r"^##\s+\d+", line), #"^##\\s+\\d+"
        
        "control_description": lambda line: re.search(r"^##\s+\d+", line),
        "control_purpose": lambda line: False,
        "control_guidance": lambda line: False,
        "control_other_information": lambda line: False,
        "control_means_of_verification": lambda line: False,
        "control_attributes": lambda line: False
    },
}


# state machine parser function
def parse_md(md_path: str, framework_details: dict) -> Dict:
    global G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS
    SEQUENCE_STATE_CONDITIONS = G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS[framework_details["name"]]
    
    b_control_start = False
    control_state = ControlStates.NONE
    controls_list = []

    cur_control = None
    parent_controls = {}

    def _add_cur_control():
        nonlocal cur_control # avoid python treating cur_control as a local function variable when we assign cur_control some value inside this function
        
        if cur_control is not None:
            if cur_control.description and cur_control.description[-1] in ['\n', ' ']:
                cur_control.description = cur_control.description[:-1]
            if cur_control.purpose and cur_control.purpose[-1] in ['\n', ' ']:
                cur_control.purpose = cur_control.purpose[:-1]
            if cur_control.guidance and cur_control.guidance[-1] in ['\n', ' ']:
                cur_control.guidance = cur_control.guidance[:-1]
            if cur_control.other_information and cur_control.other_information[-1] in ['\n', ' ']:
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
            type=framework_details["type"],
            name=framework_details["name"],
            publisher=framework_details["publisher"]
        )
    )

    with open(md_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if SEQUENCE_STATE_CONDITIONS["doc_start_controls"](line):
                b_control_start = True

            if b_control_start:
                # end of controls sequence, insert last filled control
                if SEQUENCE_STATE_CONDITIONS["doc_end_controls"](line):
                    control_state = ControlStates.NONE
                    #b_control_start = False
                    _add_cur_control()

                # new control
                elif SEQUENCE_STATE_CONDITIONS["new_control"](line):
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

                # control attributes
                if SEQUENCE_STATE_CONDITIONS["control_attributes"](line):
                    control_state = ControlStates.ATTRIBUTES; continue
                # control description
                elif SEQUENCE_STATE_CONDITIONS["control_description"](line):
                    control_state = ControlStates.DESCRIPTION; continue
                # control purpose
                elif SEQUENCE_STATE_CONDITIONS["control_purpose"](line):
                    control_state = ControlStates.PURPOSE; continue
                # control guidance
                elif SEQUENCE_STATE_CONDITIONS["control_guidance"](line):
                    control_state = ControlStates.GUIDANCE; continue
                # other information
                elif SEQUENCE_STATE_CONDITIONS["control_other_information"](line):
                    control_state = ControlStates.OTHER_INFORMATION; continue

                line = line.replace("\u00A0", " ") # replace non-breaking spaces with normal spaces
                if any(ord(char) > 127 for char in line): # ignore lines containing non ascii chars
                    continue

                line = re.sub(r"\( (.)", r"(\1", line)
                line = re.sub(r"(.) \)", r"\1)", line)
                line = re.sub(r"\x08", "", line) # 0x08 -> backspace hex char code #line = line.replace("\b", "")

                line = ' '.join(line.split()) # convert multi spacings to single spacing

                # control attributes
                if control_state == ControlStates.ATTRIBUTES:
                    if "<!-- PAGE_BREAK -->" in line:
                        continue
                    #print("In ATTRIBUTES state:", line)
                    tags = [k.strip().lower() for k in line.split('|') if k != '' and any(char.isalpha() or char.isdigit() for char in k)]

                    # reading attribute keys (table header for ISOs)
                    if len(cur_control.attributes) == 0:
                        cur_control.attributes = [{'_'.join(k.split(' ')): []} for k in tags]
                    # reading attribute values (table body for ISOs)
                    elif len(tags) > 0:
                        ind = 0
                        for attrs in tags:
                            attrs = [re.sub(r"[ -]", "", a) for a in attrs.split('#') if a != '']
                            next(iter(cur_control.attributes[ind].values())).extend(attrs)
                            ind += 1
                    #print(cur_control.attributes)
                # control description
                elif control_state == ControlStates.DESCRIPTION:
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

    #for control in controls_list:
        #print(control.model_dump_json(indent=2))
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
