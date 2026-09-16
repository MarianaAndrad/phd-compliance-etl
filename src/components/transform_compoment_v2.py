# from dependencies.database import get_db_client

import re
import json

from uuid import uuid4
from typing import Dict
from enum import Enum

from schemas.catalog import CatalogModel, MetadataModel
from schemas.control import ControlModel


def UTIL_is_phrase_continuity(prev_str, next_str):
    prev_str_last_word = prev_str.split()
    next_str_first_word = next_str.split()

    if not prev_str_last_word or not next_str_first_word:
        return True

    # NOTE: Fix missing "\n" case: "(...) the value for the assignment operation can be \"none.\"\nRelated Controls: AC-8, IA-2, PL-2."
    if prev_str_last_word[-1][-1] == '"' and (
            next_str_first_word[0][0].isupper() and not next_str_first_word[0].isupper()):
        return False

    return True


def UTIL_is_list_item_start(strg):
    return (not not re.match(r"\((?:[a-z]|\d+)\)\s+", strg)) or (not not re.match(r"(?:[a-z]|\d+)\.\s+", strg))


G_IN_ITEM_LIST = False


def UTIL_update_text_state(strg):
    global G_IN_ITEM_LIST
    if UTIL_is_list_item_start(strg):
        G_IN_ITEM_LIST = True
    elif strg.strip() and strg.strip()[-1] == '.':
        G_IN_ITEM_LIST = False


def UTIL_string_append(dest, source):
    """if dest and dest[-1] != '\n' and dest[-1] != ' ':
        dest += '\n'

    if source and source[0].islower():
        if dest and dest[-1] == '\n':
            dest = dest[:-1] + ' '
        elif dest and dest[-1] != ' ':
            dest += ' '"""

    end_punctuation = "!.:;?"
    if (
            ((source and source[0].islower()) or (dest and dest[-1] != '\n' and dest[-1] not in end_punctuation)) and
            dest.split('\n')[-1].isupper() == source.isupper() and
            not UTIL_is_list_item_start(source) and
            UTIL_is_phrase_continuity(dest, source)
    ):
        if dest and dest[-1] != ' ':
            dest += ' '
    else:
        if dest and dest[-1] != '\n':
            dest += '\n'

    UTIL_update_text_state(source)

    if "<!-- PAGE_BREAK -->" in source:
        return dest

    return dest + source


G_BASE_CONTROL_DELIMITER_COUNT = None


def UTIL_get_control_lvl(control, control_levels):
    global G_BASE_CONTROL_DELIMITER_COUNT

    if isinstance(control, ControlModel):
        ref_code = control.ref_code
    elif isinstance(control, str):
        ref_code = control

    if control_levels is not None:
        for k, v in control_levels.items():
            if v(ref_code):
                if G_BASE_CONTROL_DELIMITER_COUNT is None:
                    G_BASE_CONTROL_DELIMITER_COUNT = k
                return k

    control_delimiters = ".-"

    # register the base control delimiter count according to the first analyzed control
    if G_BASE_CONTROL_DELIMITER_COUNT is None:
        G_BASE_CONTROL_DELIMITER_COUNT = sum(ref_code.count(c) for c in control_delimiters)

    if control is not None:
        return sum(ref_code.count(c) for c in control_delimiters) + 1 - G_BASE_CONTROL_DELIMITER_COUNT

    return None


def UTIL_regex_str_match(regex, str):
    match = re.search(regex, str)

    if isinstance(match, re.Match):
        return match.group(0)

    return ''


class ControlStates(Enum):
    NONE = 0
    START = 1
    DESCRIPTION = 2
    PURPOSE = 3
    GUIDANCE = 4
    OTHER_INFORMATION = 5
    MEANS_OF_VERIFICATION = 6
    ATTRIBUTES = 7


# TODO: Move to own file?
G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS = {
    "iso27002": {
        "new_control": lambda line: re.search(r"^#+\s+\d+", line),

        "control_description": lambda line: {"val": re.match(r"^#+\s*control\s*$", line, re.IGNORECASE),
                                             "skip_line": True},
        "control_purpose": lambda line: {"val": re.match(r"^#+\s*purpose\s*$", line, re.IGNORECASE), "skip_line": True},
        "control_guidance": lambda line: {"val": re.match(r"^#+\s*guidance\s*$", line, re.IGNORECASE),
                                          "skip_line": True},
        "control_other_information": lambda line: {"val": re.match(r"^#+\s*other information\s*$", line, re.IGNORECASE),
                                                   "skip_line": True},
        "control_means_of_verification": lambda line: {
            "val": re.match(r"^#+\s*means of verification\s*$", line, re.IGNORECASE), "skip_line": True},
        "control_attributes": lambda line: {"val": re.search(r"^#+\s+\d+", line), "skip_line": True},

        # control construct function
        "construct_control": lambda line: (
            (cur_ref_code := re.search(r"\d+(:?\.\d+)*", line)),
            (cur_title := line[cur_ref_code.end() + 1:]),
            (cur_slug := cur_ref_code.group(0) + "-" + '-'.join(cur_title.lower().split()))
        )
    },
}


# state machine parser function
def parse_md(md_path: str, framework_details: dict) -> Dict:
    global G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS
    SEQUENCE_STATE_CONDITIONS = G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS[framework_details["name"]]

    control_levels = SEQUENCE_STATE_CONDITIONS[
        "control_levels"] if "control_levels" in SEQUENCE_STATE_CONDITIONS else None

    b_control_start = False
    control_state = ControlStates.NONE
    controls_list = []

    cur_control = None
    parent_controls = {}

    def _add_cur_control():
        nonlocal cur_control  # avoid python treating cur_control as a local function variable when we assign cur_control some value inside this function

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
            if UTIL_get_control_lvl(cur_control, control_levels) > 1:
                cur_control.parent_slug = parent_controls[UTIL_get_control_lvl(cur_control, control_levels) - 1].slug

            # update parent control levels dict
            parent_controls[UTIL_get_control_lvl(cur_control, control_levels)] = cur_control

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
            line = line.replace("**", "")
            line = line.replace("-<br>", "")
            line = line.replace("<br>", " ")
            print("LINE:", line)
            if line is None or line == '':
                continue

            print("PROCESSED LINE:", line)

            if framework_details["doc_start_controls"].lower() in line.lower():
                b_control_start = True

            if b_control_start:
                # end of controls sequence, insert last filled control
                if framework_details["doc_end_controls"].lower() in line.lower():
                    control_state = ControlStates.NONE
                    b_control_start = False
                    _add_cur_control()

                # new control
                elif SEQUENCE_STATE_CONDITIONS["new_control"](line):
                    control_state = ControlStates.START
                    _add_cur_control()

                    line = ' '.join(line.split())  # convert multi spacings to single spacing
                    cur_ref_code, cur_title, cur_slug = SEQUENCE_STATE_CONDITIONS["construct_control"](line)
                    # print("FOUND NEW CONTROL: " + line + " | REF_CODE:", cur_ref_code, "| TITLE: '" + cur_title + "' | SLUG: '" + cur_slug + "'")

                    # print("ENTERED CONTROL: " + line + " | control = " + cur_ref_code.group(0) + ", title = '" + line[cur_ref_code.end() + 1:] + "'")
                    ref_code = cur_ref_code if isinstance(cur_ref_code, str) else cur_ref_code.group(0)
                    cur_control = ControlModel(
                        catalog_uuid=catalog.uuid,
                        ref_code=ref_code,
                        title=cur_title,
                        slug=cur_slug,
                        category=parent_controls[1].title if 1 in parent_controls
                                                             and UTIL_get_control_lvl(ref_code,
                                                                                      control_levels) > G_BASE_CONTROL_DELIMITER_COUNT else cur_title
                    )

                    # print(cur_ref_code.group(0), "->", get_cur_control_lvl())

                # control attributes
                seq_state_result = None
                if ((seq_state_result := SEQUENCE_STATE_CONDITIONS["control_attributes"](line))["val"]):
                    control_state = ControlStates.ATTRIBUTES
                # control description
                elif ((seq_state_result := SEQUENCE_STATE_CONDITIONS["control_description"](line))["val"]):
                    control_state = ControlStates.DESCRIPTION
                # control purpose
                elif ((seq_state_result := SEQUENCE_STATE_CONDITIONS["control_purpose"](line))["val"]):
                    control_state = ControlStates.PURPOSE
                # control guidance
                elif ((seq_state_result := SEQUENCE_STATE_CONDITIONS["control_guidance"](line))["val"]):
                    control_state = ControlStates.GUIDANCE
                # other information
                elif ((seq_state_result := SEQUENCE_STATE_CONDITIONS["control_other_information"](line))["val"]):
                    control_state = ControlStates.OTHER_INFORMATION

                if seq_state_result["val"] and seq_state_result["skip_line"]:
                    continue
                # if the sequence condition result is a regex match, set the line content to start at the end of that match
                if isinstance(seq_state_result["val"], re.Match):
                    # print(seq_state_result)
                    line = line[seq_state_result["val"].end():]
                    if line.startswith(':'):
                        line = line[1:].strip()

                line = line.replace("\u00A0", " ")  # replace non-breaking spaces with normal spaces
                if any(ord(char) > 127 for char in line):  # ignore lines containing non ascii chars
                    continue

                line = line.replace("&#x2014;", "-")

                line = re.sub(r"\( (.)", r"(\1", line)
                line = re.sub(r"(.) \)", r"\1)", line)
                line = re.sub(r"\x08", "", line)  # 0x08 -> backspace hex char code #line = line.replace("\b", "")

                line = ' '.join(line.split())  # convert multi spacings to single spacing

                # control attributes
                if control_state == ControlStates.ATTRIBUTES:
                    if "<!-- PAGE_BREAK -->" in line:
                        continue
                    # print("In ATTRIBUTES state:", line)
                    tags = [k.strip().lower() for k in line.split('|') if
                            k != '' and any(char.isalpha() or char.isdigit() for char in k)]

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
                    # print(cur_control.attributes)
                # control description
                elif control_state == ControlStates.DESCRIPTION:
                    # print("CONTROL", cur_control.ref_code, "DESCRIPTION:", line)
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

    # for control in controls_list:
    # print(control.model_dump_json(indent=2))
    # print(control.ref_code, " -> ", control.parent_slug)

    return {"catalog": catalog, "controls_list": controls_list}


def dump_cdm_instances(file_path: str, cdm_instances: Dict) -> None:
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump({
            "catalog": cdm_instances["catalog"].model_dump(),
            "controls_list": [control.model_dump() for control in cdm_instances["controls_list"]]
        },
            f, indent=2)


if __name__ == "__main__":
    # DATA_MD_FILES_DIR = "../data-output/01-markdown"
    # OUTPUT_DIR = "../data-output/02-cdm-instances"
    # for md_file in Path(DATA_MD_FILES_DIR).glob("*.md"):
    #     framework_name = md_file.stem.split('.')[0]
    #     print(f"Processing {md_file} for framework {framework_name}...")

    document_path = "../data-output/01-markdown/i.s.eniso-iec27002-2022-v2.00_pdf.md"
    output_file = "../data-output/02-cdm-instances/i.s.eniso-iec27002-2022-v2.00_pdf.json"
    framework_details = {
        "name": "iso27002",
        "type": "framework",
        "publisher": "ISO/IEC",
        "doc_start_controls": "5 organizational controls",
        "doc_end_controls": "Information security roles and responsibilities"
    }
    cdm_instances = parse_md(md_path=document_path, framework_details=framework_details)
    dump_cdm_instances(output_file, cdm_instances)

# asyncio.run(persist_data(controls_list))
