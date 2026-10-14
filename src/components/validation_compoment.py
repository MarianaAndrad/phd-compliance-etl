import re
import html
import json
import logging

from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field
from tqdm import tqdm

from dependencies.llm import build_llm, build_structured_llm
from schemas.control import ControlModel
from components.transform_compoment import G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS

logger = logging.getLogger(__name__)

# fields checked deterministically (see check_slug_fields) or internal ids, hidden from the judge
G_JUDGE_EXCLUDED_FIELDS = {"catalog_uuid", "citers", "slug", "parent_slug"}

# a 'fail' with no listed issue is an inconsistent judgement, so the judge is asked again up to this many times
G_JUDGE_MAX_ATTEMPTS = 2

# max characters of source text sent to the judge for a single control (keeps the prompt inside the model context)
G_MAX_SOURCE_CHARS = 12000

G_JUDGE_SYSTEM_PROMPT = """You are a meticulous compliance auditor acting as an impartial judge.

Your job is to check whether a control that was automatically extracted from a document (matching the
JSON schema below) is a FAITHFUL, COMPLETE and CORRECT representation of the original SOURCE TEXT.
Look specifically for:
- hallucinated content: text in the structured control that is not present in the source text;
- missing content: information of this control present in the source text but absent from the structured fields;
- misplaced content: text stored in the wrong field (e.g. guidance stored as description, or text belonging to another control);
- an incoherent ref_code or title given the source text.

Ignore differences in whitespace, line breaks, hyphenation, letter case, page break markers and table formatting.
The section headers ("Control", "Purpose", "Guidance", "Other information") are not part of the content.
NOTE paragraphs, lists and tables belong to the field of the section they appear in.

When the source gives no separate name for a control (e.g. "o GV.OC-01: Statement..."), the "title" is set to the
ref_code by design and the statement is stored in "description"; this is correct and must never be reported as an issue.
Documents cited inside the text (e.g. "(see 8.10)", "ISO/IEC 27040") stay in the text of their section.
"references" and "means_of_verification" are not extracted and are always left empty; this is correct and must never
be reported as missing content.
Fields left empty because the source text has no such section are correct (e.g. a clause heading with no content).
Judge only the fields present in the structured control; do not report fields that are not shown.

First write a short justification and list the concrete issues, THEN decide the verdict:
'fail' if there is any hallucinated, missing or misplaced content, 'pass' otherwise.
Every 'fail' must be backed by at least one issue quoting the offending text; if you cannot quote one, the verdict is 'pass'.

Schema of the structured control:
"""


class JudgeVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class ValidationStatus(str, Enum):
    """Outcome of validating a single control: the judge verdict, or ERROR when no verdict could be obtained."""
    PASS  = "pass"
    FAIL  = "fail"
    ERROR = "error"  # judge call failed, so the control is excluded from the pass rate


class ControlJudgement(BaseModel):
    """Structured verdict produced by the LLM judge for a single control."""
    model_config = ConfigDict(title="ControlJudgement")

    # reasoning fields come first so the model writes them before committing to a verdict
    justification: str   = Field(..., title="Justification", description="Short comparison (max 5 sentences) of the structured control against the source text.")
    issues: List[str]     = Field(default=[], title="Issues", description="One entry per concrete problem mentioned in the justification (e.g. \"hallucinated content in description: '...'\"). Must not be empty when the verdict is 'fail'.")
    verdict: JudgeVerdict = Field(..., title="Verdict", description="'fail' if any issue was found, 'pass' otherwise.")


class ControlValidationResult(BaseModel):
    """Judgement for a single control, together with its identity."""
    model_config = ConfigDict(title="Control Validation Result")

    catalog_uuid: str | None   = Field(default=None, title="Catalog UUID")
    ref_code: str              = Field(..., title="Reference Code")
    slug: str                  = Field(..., title="Slug")
    source_line: Optional[int] = Field(default=None, title="Source Line", description="1-based line of the control heading in the source text.")
    verdict: ValidationStatus  = Field(..., title="Verdict")
    issues: List[str]          = Field(default=[], title="Issues")
    justification: str         = Field(default="", title="Justification")


# ---------------------------------------------------------------------------
# source span location
# ---------------------------------------------------------------------------

def UTIL_norm_line(strg: str) -> str:
    strg = html.unescape(strg)
    strg = re.sub(r"<!--.*?-->", " ", strg)  # drop markdown comments (e.g. page breaks)
    return ' '.join(re.findall(r"[a-z0-9]+", strg.lower()))


def UTIL_is_heading_candidate(line: str) -> bool:
    line = line.strip()
    # table of contents entries ("5.5 Contact with authorities......14") and table rows (annex mappings) are never headings
    return bool(line) and not line.startswith('|') and not re.search(r"\.{5,}", line)


def UTIL_is_control_heading(norm_line: str, control: ControlModel) -> bool:
    norm_ref = UTIL_norm_line(control.ref_code)
    norm_title = UTIL_norm_line(control.title)

    if not norm_ref:
        return False

    norm_line = re.sub(r"^[a-z] ", "", norm_line) + " "  # drop a single char bullet (e.g. "o GV.OC-01: ...")

    # heading usually starts with the reference code (e.g. "5.5 Contact with authorities")
    if norm_line.startswith(norm_ref + " "):
        return not norm_title or norm_title == norm_ref or norm_title in norm_line
    # otherwise the title is immediately followed by the reference code (e.g. "Govern (GV)")
    return bool(norm_title) and norm_line.startswith(f"{norm_title} {norm_ref} ")


def locate_control_spans(source_lines: List[str], controls_list: List[ControlModel],
                         doc_start_controls: Optional[Callable[[str], Any]] = None,
                         doc_end_controls: Optional[Callable[[str], Any]] = None) -> List[Optional[Tuple[int, int]]]:
    """Finds, for every control (in extraction order), the [start, end) line range of its source text.

    Controls are searched sequentially from a moving cursor, so cross references (e.g. "see 5.24")
    appearing before the real heading are not mistaken for it. The search starts at the first
    `doc_start_controls` match outside the table of contents. A span ends where the next located
    control starts; the last one ends at the first `doc_end_controls` match after it (or at the end of the text).
    Both conditions are the transform step line predicates (see G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS).
    """
    norm_lines = [UTIL_norm_line(line) if UTIL_is_heading_candidate(line) else '' for line in source_lines]

    cursor = 0
    if doc_start_controls:
        cursor = next((i for i, line in enumerate(source_lines)
                       if UTIL_is_heading_candidate(line) and doc_start_controls(line.strip())), 0)

    starts: List[Optional[int]] = []
    for control in controls_list:
        found = next((i for i in range(cursor, len(source_lines)) if UTIL_is_control_heading(norm_lines[i], control)), None)
        starts.append(found)
        if found is not None:
            cursor = found + 1

    spans: List[Optional[Tuple[int, int]]] = []
    for idx, start in enumerate(starts):
        if start is None:
            spans.append(None)
            continue
        end = next((s for s in starts[idx + 1:] if s is not None), None)
        if end is None:
            end = next((i for i in range(start + 1, len(source_lines))
                        if doc_end_controls and doc_end_controls(source_lines[i].strip())), len(source_lines))
        spans.append((start, end))

    return spans


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------

def build_judge_llm():
    """Binds the ControlJudgement schema to the LLM via tool calling."""
    return build_structured_llm(build_llm(), ControlJudgement)


def validate_control(judge_llm, control: ControlModel, source_context: str) -> ControlJudgement:
    """Asks the LLM judge to compare a single structured control against its source text.

    Raises if the judge call fails or returns no structured output.
    """
    schema = ControlModel.model_json_schema()
    schema["properties"] = {k: v for k, v in schema["properties"].items() if k not in G_JUDGE_EXCLUDED_FIELDS}
    schema["required"] = [k for k in schema.get("required", []) if k not in G_JUDGE_EXCLUDED_FIELDS]

    system_message = SystemMessage(content=G_JUDGE_SYSTEM_PROMPT + json.dumps(schema))
    human_message = HumanMessage(content=(
        'SOURCE TEXT (ground truth, as extracted from the original document):\n"""\n'
        + source_context
        + '\n"""\n\nSTRUCTURED CONTROL PRODUCED BY THE TRANSFORM STEP:\n'
        + control.model_dump_json(indent=2, exclude=G_JUDGE_EXCLUDED_FIELDS)
        + '\n\nJudge whether this structured control faithfully and completely represents the source text above.'
    ))

    for _ in range(G_JUDGE_MAX_ATTEMPTS):
        judgement = judge_llm.invoke([system_message, human_message])
        if judgement is None:
            raise ValueError("empty structured output")
        if judgement.verdict == JudgeVerdict.PASS or judgement.issues:
            return judgement
        logger.info("Judge returned 'fail' without issues for control '%s', retrying", control.slug)

    # still unsupported after retrying: keep the fail, but flag it so it can be reviewed by hand
    judgement.issues = ["Judge returned 'fail' without listing a concrete issue (needs manual review)."]
    return judgement


def check_slug_fields(control: ControlModel, controls_by_slug: Dict[str, ControlModel]) -> List[str]:
    """Checks the identity fields (slug, parent_slug), which are derived deterministically and hidden from the LLM judge."""
    issues = []

    # controls without a name of their own use the ref_code as title, and then the slug is just the ref_code
    expected_slug = control.ref_code if control.title in ("", control.ref_code) else f"{control.ref_code} {control.title}"
    if UTIL_norm_line(control.slug) != UTIL_norm_line(expected_slug):
        issues.append(f"slug '{control.slug}' does not match ref_code '{control.ref_code}' and title '{control.title}'.")

    if control.parent_slug is not None and control.parent_slug not in controls_by_slug:
        issues.append(f"parent_slug '{control.parent_slug}' does not match any extracted control.")
    elif control.parent_slug == control.slug:
        issues.append(f"parent_slug '{control.parent_slug}' points to the control itself.")

    return issues


def UTIL_get_doc_bounds(framework_details: dict) -> Tuple[Optional[Callable[[str], Any]], Optional[Callable[[str], Any]]]:
    """Returns the same controls section start/end conditions the transform step used for this framework."""
    conditions = G_FRAMEWORKS_SEQUENCE_STATE_CONDITIONS.get(framework_details.get("name"), {})
    return conditions.get("doc_start_controls"), conditions.get("doc_end_controls")


def validate_cdm_instances(md_path: str, cdm_instances: Dict, framework_details: Optional[dict] = None,
                           judge_llm=None) -> List[ControlValidationResult]:
    """Runs the LLM judge over every control, comparing it against the markdown text it was parsed from."""
    with open(md_path, "r", encoding="utf-8") as f:
        source_lines = f.read().split('\n')

    controls_list: List[ControlModel] = cdm_instances["controls_list"]
    framework_details = framework_details or {}
    judge_llm = judge_llm or build_judge_llm()

    spans = locate_control_spans(source_lines, controls_list, *UTIL_get_doc_bounds(framework_details))
    controls_by_slug = {c.slug: c for c in controls_list}

    results = []
    for control, span in tqdm(list(zip(controls_list, spans)), desc="Validating controls"):
        result = { "catalog_uuid": control.catalog_uuid, "ref_code": control.ref_code, "slug": control.slug,
                   "source_line": span[0] + 1 if span else None }

        # heading not found: the extracted ref_code/title do not exist in the source, so it counts as an extraction failure
        if span is None:
            results.append(ControlValidationResult(
                **result, verdict=ValidationStatus.FAIL,
                issues=["Control heading not found in the source text."],
                justification="Source context lookup failed, so the control could not be judged."
            ))
            continue

        source_context = '\n'.join(line for line in source_lines[span[0]:span[1]] if line.strip())
        if len(source_context) > G_MAX_SOURCE_CHARS:
            logger.warning("Source context for control '%s' truncated to %d chars", control.slug, G_MAX_SOURCE_CHARS)
            source_context = source_context[:G_MAX_SOURCE_CHARS]

        try:
            judgement = validate_control(judge_llm, control, source_context)
        except Exception as e:
            # no verdict was produced, so this says nothing about the extraction quality
            logger.warning("Judge invocation failed for control '%s': %s", control.slug, e)
            results.append(ControlValidationResult(
                **result, verdict=ValidationStatus.ERROR,
                issues=["LLM judge call failed or returned an unparsable result."],
                justification=f"Validation could not be completed due to an error invoking the judge LLM: {e}"
            ))
            continue

        # derived field errors are deterministic, so they override a judge 'pass'
        judgement_dict = judgement.model_dump()
        if slug_issues := check_slug_fields(control, controls_by_slug):
            judgement_dict["verdict"] = ValidationStatus.FAIL
            judgement_dict["issues"] = slug_issues + judgement_dict["issues"]

        results.append(ControlValidationResult(**result, **judgement_dict))

    return results


def summarize_validation(results: List[ControlValidationResult]) -> Dict:
    """Aggregates individual judgements into a pass-rate summary.

    Controls in ERROR state have no verdict, so the pass rate is computed over the judged controls only.
    """
    passed = sum(r.verdict == ValidationStatus.PASS for r in results)
    failed = sum(r.verdict == ValidationStatus.FAIL for r in results)
    judged = passed + failed
    return {
        "total_controls": len(results),
        "judged": judged,
        "passed": passed,
        "failed": failed,
        "errors": sum(r.verdict == ValidationStatus.ERROR for r in results),
        "not_found_in_source": sum(r.source_line is None for r in results),
        "pass_rate": round(passed / judged, 4) if judged else None,
    }


def dump_validation_report(file_path: str, results: List[ControlValidationResult]) -> Dict:
    summary = summarize_validation(results)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump({
            "summary": summary,
            "results": [r.model_dump(mode="json") for r in results]
        }, f, indent=2)

    return summary


if __name__ == "__main__":
    from components.load_compoment import load_cdm_instances

    logging.basicConfig(level=logging.INFO)
    document_path = "./data-output/01-markdown/i.s.eniso-iec27002-2022-v2.00_pdf.md"
    cdm_file = "./data-output/02-cdm-instances/i.s.eniso-iec27002-2022-v2.00_pdf.json"
    report_file = "./data-output/03-validation/i.s.eniso-iec27002-2022-v2.00_pdf.json"

    results = validate_cdm_instances(document_path, load_cdm_instances(cdm_file), {"name": "iso27002"})
    print(dump_validation_report(report_file, results))
