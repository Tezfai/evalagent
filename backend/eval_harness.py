"""Small deterministic evaluation harness for the investigation workflow.

Runs the existing `run_investigation` workflow against a set of predefined
incident questions with known expected evidence/root-cause facts, and scores
the result using deterministic checks (evidence file matching, keyword
coverage, and the critic verdict already embedded in the report). This does
not duplicate any agent logic and does not call a second LLM judge.
"""

import json
import os
import re

try:
    from .investigation_runner import run_investigation
except ImportError:
    from investigation_runner import run_investigation

DEFAULT_CASES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "tests",
    "eval_cases.json",
)

ROOT_CAUSE_KEYWORD_THRESHOLD = 0.5


def load_cases(path=None):
    """Load evaluation cases from a JSON file."""
    with open(path or DEFAULT_CASES_PATH, encoding="utf-8") as cases_file:
        return json.load(cases_file)


def _basename(value):
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1].lower()


def _primary_evidence_file(evidence):
    primary_item = next(
        (item for item in evidence if item.get("primary")),
        evidence[0] if evidence else None,
    )
    return primary_item.get("file") if primary_item else None


def _evidence_files(evidence):
    return {_basename(item.get("file")) for item in evidence}


def _normalize_for_matching(text):
    """Normalize text for deterministic keyword matching only.

    Lowercases, treats hyphens/underscores as spaces, and collapses repeated
    whitespace so equivalent phrasing ("deployment 882" vs "deployment-882")
    matches without fuzzy matching or another LLM judge.
    """
    normalized = re.sub(r"[-_]", " ", text.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _section(report_text, section_name):
    """Extract the body of a `## <section_name>` block from the report text.

    "Report Review" is always the last section written by `_format_report`,
    so it is returned to the end of the text rather than being bounded by a
    search for the next header - a free-text critic field that happens to
    contain a blank line followed by "##" must not truncate it early.
    """
    marker = f"## {section_name}\n"
    start = report_text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    if section_name == "Report Review":
        return report_text[start:].strip()
    end = report_text.find("\n\n## ", start)
    return report_text[start:end if end != -1 else len(report_text)].strip()


_REVIEW_FIELD_LABELS = (
    "Confidence",
    "Report Quality",
    "Evidence Coverage",
    "Missing Evidence",
    "Unsupported Claims",
    "Recommended Next Steps",
    "Review Summary",
)


def _review_field(review_text, label):
    """Extract one labeled field from the Report Review text.

    Anchored on line-start labels (not literal "\\n\\n<label>" substrings) so
    free-text field values containing blank lines can't shift the boundary.
    """
    other_labels = "|".join(
        re.escape(other) for other in _REVIEW_FIELD_LABELS if other != label
    )
    pattern = re.compile(
        rf"^{re.escape(label)}:\n?(.*?)(?=\n^(?:{other_labels}):|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(review_text)
    return match.group(1).strip() if match else ""


def _grounding_details(report_text):
    """Read the critic verdict already embedded in the report's Report Review.

    Returns the pass/fail verdict plus the evidence coverage and unsupported
    claims that drove it, so a FAIL can be explained without a second
    evaluator or LLM call.
    """
    review_text = _section(report_text, "Report Review")
    if not review_text:
        return {"pass": None, "evidence_coverage": "", "unsupported_claims": []}

    unsupported_claims_text = _review_field(review_text, "Unsupported Claims")
    evidence_coverage = _review_field(review_text, "Evidence Coverage")

    no_unsupported_claims = unsupported_claims_text == "- None identified."
    unsupported_claims = (
        []
        if no_unsupported_claims
        else [
            line[2:] if line.startswith("- ") else line
            for line in unsupported_claims_text.splitlines()
            if line.strip()
        ]
    )

    return {
        "pass": no_unsupported_claims and evidence_coverage != "Weak",
        "evidence_coverage": evidence_coverage,
        "unsupported_claims": unsupported_claims,
    }


def _grounding_pass(report_text):
    """Backward-compatible boolean-only view of `_grounding_details`."""
    return _grounding_details(report_text)["pass"]


def evaluate_case(case, report_text, evidence):
    """Score one investigation result against its expected values.

    Pure and deterministic: takes the already-produced report/evidence and
    does not call any LLM itself.
    """
    primary_file = _primary_evidence_file(evidence)
    evidence_files = _evidence_files(evidence)
    root_cause_text = _normalize_for_matching(
        _section(report_text, "Root Cause")
    )

    result = {"id": case["id"]}

    result["primary_evidence_pass"] = (
        _basename(primary_file) == _basename(case.get("expected_primary_evidence"))
    )

    expected_deployment = case.get("expected_deployment")
    result["deployment_pass"] = (
        _basename(expected_deployment) in evidence_files
        if expected_deployment
        else None
    )

    expected_runbook = case.get("expected_runbook")
    result["runbook_pass"] = (
        _basename(expected_runbook) in evidence_files
        if expected_runbook
        else None
    )

    expected_service = case.get("expected_service")
    primary_content = next(
        (
            item.get("content", "")
            for item in evidence
            if item.get("file") == primary_file
        ),
        "",
    )
    result["service_pass"] = (
        bool(expected_service)
        and expected_service.lower() in primary_content.lower()
    )

    keywords = case.get("root_cause_keywords") or []
    matched_keywords = [
        keyword for keyword in keywords
        if _normalize_for_matching(keyword) in root_cause_text
    ]
    coverage = len(matched_keywords) / len(keywords) if keywords else None
    result["root_cause_coverage"] = coverage
    result["root_cause_pass"] = (
        coverage is not None and coverage >= ROOT_CAUSE_KEYWORD_THRESHOLD
    )

    grounding = _grounding_details(report_text)
    result["grounding_pass"] = grounding["pass"]
    result["grounding_evidence_coverage"] = grounding["evidence_coverage"]
    result["grounding_unsupported_claims"] = grounding["unsupported_claims"]

    return result


def run_case(case):
    """Run the real investigation workflow for one case and score it."""
    report_text, evidence = run_investigation(case["question"])
    result = evaluate_case(case, report_text, evidence)
    result["status"] = "OK"
    result["report_text"] = report_text
    return result


def _rate(results, key):
    applicable = [r[key] for r in results if r.get(key) is not None]
    if not applicable:
        return None
    return sum(1 for value in applicable if value) / len(applicable)


def aggregate_results(results):
    return {
        "Primary Evidence Accuracy": _rate(results, "primary_evidence_pass"),
        "Deployment Retrieval": _rate(results, "deployment_pass"),
        "Runbook Retrieval": _rate(results, "runbook_pass"),
        "Service Accuracy": _rate(results, "service_pass"),
        "Root Cause Accuracy": _rate(results, "root_cause_pass"),
        "Grounding Pass Rate": _rate(results, "grounding_pass"),
        "Execution Error Rate": (
            sum(1 for r in results if r.get("status") == "ERROR") / len(results)
            if results
            else None
        ),
    }


def _format_pass(value):
    if value is None:
        return "N/A"
    return "PASS" if value else "FAIL"


def format_report(results, aggregate):
    lines = []
    for result in results:
        lines.append(f"Incident {result['id'].replace('incident-', '')}")
        if result.get("status") == "ERROR":
            lines.append(f"Status: ERROR ({result.get('error', 'unknown error')})")
            lines.append("")
            continue
        lines.append(f"Primary Evidence: {_format_pass(result['primary_evidence_pass'])}")
        lines.append(f"Deployment: {_format_pass(result['deployment_pass'])}")
        lines.append(f"Runbook: {_format_pass(result['runbook_pass'])}")
        lines.append(f"Service: {_format_pass(result.get('service_pass'))}")
        lines.append(f"Root Cause: {_format_pass(result['root_cause_pass'])}")
        lines.append(f"Grounding: {_format_pass(result['grounding_pass'])}")
        if result["grounding_pass"] is False:
            lines.append(
                f"Evidence Coverage: {result.get('grounding_evidence_coverage') or 'Unknown'}"
            )
            lines.append("Unsupported Claims:")
            for claim in result.get("grounding_unsupported_claims") or []:
                lines.append(f"- {claim}")
        lines.append("")

    lines.append("Overall:")
    for label, value in aggregate.items():
        lines.append(f"{label}: {'N/A' if value is None else f'{value:.0%}'}")

    return "\n".join(lines)


def run_all(cases=None):
    """Run and score every case.

    Execution errors (e.g. a transport failure) are recorded with
    status="ERROR" and excluded from accuracy metrics, since they represent
    infrastructure failures rather than evaluation FAILs.
    """
    cases = cases if cases is not None else load_cases()
    results = []
    for case in cases:
        try:
            results.append(run_case(case))
        except Exception as error:  # noqa: BLE001 - surfaced as an execution error
            results.append({
                "id": case["id"],
                "status": "ERROR",
                "primary_evidence_pass": None,
                "deployment_pass": None,
                "runbook_pass": None,
                "service_pass": None,
                "root_cause_pass": None,
                "grounding_pass": None,
                "error": str(error),
            })
    return results, aggregate_results(results)


if __name__ == "__main__":
    all_results, all_aggregate = run_all()
    print(format_report(all_results, all_aggregate))
