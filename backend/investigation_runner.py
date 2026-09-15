import json
import re

from dotenv import load_dotenv

try:
    from .deployment_agent import analyze_deployment
    from .investigator_agent import (
        GPT5_MINI_DEPLOYMENT,
        client,
        create_investigation_plan,
    )
    from .critic_agent import review_report
    from .runbook_agent import analyze_runbook
    from .tool_registry import tool_registry
except ImportError:
    from deployment_agent import analyze_deployment
    from investigator_agent import (
        GPT5_MINI_DEPLOYMENT,
        client,
        create_investigation_plan,
    )
    from critic_agent import review_report
    from runbook_agent import analyze_runbook
    from tool_registry import tool_registry

load_dotenv()

DEPLOYMENT_PATTERN = re.compile(r"\bdeployment[- ](\d+)\b", re.IGNORECASE)
INCIDENT_PATTERN = re.compile(r"\bincident[- ](\d+)\b", re.IGNORECASE)
RUNBOOK_PATTERN = re.compile(
    r"\b[a-z0-9][a-z0-9-]*-runbook(?:\.md)?\b",
    re.IGNORECASE,
)
AZDO_WORK_ITEM_PATTERN = re.compile(
    r"Azure DevOps Work Item:\s*(\d+)",
    re.IGNORECASE,
)
AZDO_PULL_REQUEST_PATTERN = re.compile(
    r"Azure DevOps Pull Request:\s*(\d+)",
    re.IGNORECASE,
)
AZDO_REPOSITORY_PATTERN = re.compile(
    r"Azure DevOps Repository:\s*([^\s]+)",
    re.IGNORECASE,
)


REPORT_SECTIONS = (
    "Primary Evidence",
    "Deployment Analysis",
    "Runbook Analysis",
    "Incident",
    "Root Cause",
    "Impact",
    "Resolution",
    "Related Documents",
    "Recommendations",
    "Azure DevOps Evidence",
    "Report Review",
)


REPORT_SYSTEM_PROMPT = """You are an incident investigation report writer.
Use only the investigation plan and evidence provided by the user.
Return a valid JSON object with exactly these keys:
- Deployment Analysis
- Runbook Analysis
- Incident
- Root Cause
- Impact
- Resolution
- Related Documents
- Recommendations
- Azure DevOps Evidence
- Report Review
- Primary Evidence

Each value must be a concise markdown-ready string. Clearly state when the
available evidence does not establish an answer. Do not invent facts.
Focus the report on the PRIMARY EVIDENCE.
Supporting documents provide additional context only.
The Deployment Analysis value must include Change Summary, Risk Rating,
Related Incidents, and Rollback Status when deployment evidence is available.
The Runbook Analysis value must include Purpose, Immediate Actions,
Escalation Conditions, Recovery Steps, and Risk Level when runbook evidence is
available.
Keep each report section distinct. Deployment Analysis summarizes the change,
assessed risk, related incident IDs, and rollback status. Incident contains
only retrieved incident information. Root Cause contains only a supported
causal mechanism. Impact contains only observed effects. Resolution contains
completed actions. Recommendations contain only future or incomplete actions,
with at most five high-value items; do not repeat completed actions. Related
Documents must distinguish retrieved documents from referenced-but-unretrieved
documents. Report Review is a concise assessment.
Use only selected evidence and normalized Azure DevOps records supplied in the
prompt. A reference proves only that a document exists. Mark unavailable,
unknown, unverified, or not established information explicitly.
"""


def _mark_primary(evidence):
    return [
        {**item, "primary": True}
        for item in evidence
    ]


def _as_file_name(value, prefix=None):
    if value is None:
        return None

    value = str(value).strip()
    if not value:
        return None

    if value.endswith(".md"):
        return value

    if prefix and value.isdigit():
        return f"{prefix}-{value}.md"

    return f"{value}.md"


def _plan_value(plan, *keys):
    for key in keys:
        value = plan.get(key)
        if value:
            return value
    return None


def _basename(value):
    return str(value).replace("\\", "/").rsplit("/", 1)[-1]


def _reference_file_names(content):
    linked_targets = re.findall(r"\[[^\]]+\]\(([^)]+)\)", content)
    return [_basename(target.split("#", 1)[0]) for target in linked_targets]


def _ordered_unique(values):
    return list(dict.fromkeys(value for value in values if value))


def _extract_references(evidence, primary_evidence=None):
    ordered_evidence = []
    if primary_evidence:
        primary_file = primary_evidence.get("file")
        ordered_evidence.extend(
            item for item in evidence
            if item.get("file") == primary_file
        )
    ordered_evidence.extend(
        item for item in evidence
        if item not in ordered_evidence
    )

    linked_names = _ordered_unique(
        reference
        for item in ordered_evidence
        for reference in _reference_file_names(item.get("content", ""))
    )
    document_text = "\n".join(
        item.get("content", "") for item in ordered_evidence
    )

    deployment_files = _ordered_unique(
        [
            name for name in linked_names
            if re.fullmatch(r"deployment-\d+\.md", name, re.IGNORECASE)
        ]
        + [
            f"deployment-{deployment_id}.md"
            for deployment_id in DEPLOYMENT_PATTERN.findall(document_text)
        ]
    )
    incident_files = _ordered_unique(
        [
            name for name in linked_names
            if re.fullmatch(r"incident-\d+\.md", name, re.IGNORECASE)
        ]
        + [
            f"incident-{incident_id}.md"
            for incident_id in INCIDENT_PATTERN.findall(document_text)
        ]
    )
    runbook_files = _ordered_unique(
        [
            name for name in linked_names
            if RUNBOOK_PATTERN.fullmatch(name)
        ]
        + [
            runbook if runbook.endswith(".md") else f"{runbook}.md"
            for runbook in RUNBOOK_PATTERN.findall(document_text)
        ]
    )
    return deployment_files, incident_files, runbook_files


def _select_primary_deployment(evidence, deployment_id):
    if deployment_id is None:
        return None, []

    deployment_marker = f"deployment-{str(deployment_id).strip()}".lower()
    matches = [
        item
        for item in evidence
        if deployment_marker in str(item.get("file", "")).lower()
    ]

    if not matches:
        return None, []

    return matches[0], _mark_primary(matches)


def _format_evidence(evidence):
    formatted_evidence = []

    for index, item in enumerate(evidence, start=1):
        formatted_evidence.append(
            f"Evidence {index} ({item['category']}"
            f"{' PRIMARY' if item.get('primary') else ''}): "
            f"{item['file']} (chunk {item['chunk_id']})\n"
            f"{item['content']}"
        )

    return "\n\n".join(formatted_evidence)


def _limit_supporting_evidence(evidence, maximum_documents=3):
    supporting_evidence = []
    included_files = set()

    for item in evidence:
        file_name = item.get("file")
        if file_name not in included_files:
            if len(included_files) >= maximum_documents:
                break
            included_files.add(file_name)
        supporting_evidence.append(item)

    return supporting_evidence


def _deduplicate_evidence(evidence):
    documents = {}
    seen_chunks = set()

    for item in evidence:
        file_name = item.get("file")
        chunk_id = item.get("chunk_id")
        chunk_key = (file_name, str(chunk_id))
        if chunk_key in seen_chunks:
            if item.get("primary") and file_name in documents:
                documents[file_name]["primary"] = True
            continue
        seen_chunks.add(chunk_key)

        document = documents.setdefault(
            file_name,
            {
                **item,
                "content": "",
                "chunk_ids": [],
            },
        )
        if item.get("primary"):
            document["primary"] = True

        content = item.get("content", "")
        if content and content not in document["content"].split("\n\n"):
            document["content"] = (
                f"{document['content']}\n\n{content}"
                if document["content"]
                else content
            )

        if chunk_id is not None:
            document["chunk_ids"].append(str(chunk_id))

    deduplicated = []
    for document in documents.values():
        chunk_ids = document.pop("chunk_ids")
        document["chunk_id"] = ", ".join(chunk_ids)
        deduplicated.append(document)

    return deduplicated


def _format_context(primary_evidence, supporting_evidence):
    return (
        "PRIMARY EVIDENCE\n\n"
        f"{_format_evidence(primary_evidence) or 'None available.'}\n\n"
        "SUPPORTING EVIDENCE\n\n"
        f"{_format_evidence(supporting_evidence) or 'None available.'}"
    )


def _format_report(report, primary_files):
    primary_label = ", ".join(primary_files) or "None identified"
    sections = [f"Primary Evidence: {primary_label}"]

    sections.extend(
        f"## {section}\n"
        f"{report.get(section, 'No information available.') }"
        for section in REPORT_SECTIONS
        if section != "Primary Evidence"
    )

    return "\n\n".join(sections)


def _format_deployment_analysis(analysis, has_evidence=False):
    if not analysis:
        if not has_evidence:
            return "No deployment evidence available."
        return (
            "Automated deployment analysis was unavailable because the "
            "analyzer returned no valid structured output."
        )

    return (
        f"Change Summary: {analysis.get('change_summary', '')}\n"
        f"Assessed Risk Rating: {analysis.get('risk_rating', '')}\n"
        f"Related Incidents: {', '.join(analysis.get('related_incidents', []))}\n"
        f"Rollback Status: {analysis.get('rollback_status', '')}"
    )


def _format_runbook_list(values):
    if not values:
        return "- None available."
    return "\n".join(f"- {value}" for value in values)


def _format_runbook_analysis(analysis):
    if not analysis:
        return "No runbook evidence available."

    return (
        f"Purpose: {analysis.get('purpose', '')}\n\n"
        f"Immediate Actions:\n"
        f"{_format_runbook_list(analysis.get('immediate_actions', []))}\n\n"
        f"Escalation Conditions:\n"
        f"{_format_runbook_list(analysis.get('escalation_conditions', []))}\n\n"
        f"Recovery Steps:\n"
        f"{_format_runbook_list(analysis.get('recovery_steps', []))}\n\n"
        f"Risk Level: {analysis.get('risk_level', '')}"
    )


def _format_review_list(values):
    if not values:
        return "- None identified."
    return "\n".join(f"- {value}" for value in values)


def _limit_recommendations(value, maximum=5):
    if not isinstance(value, str):
        return value

    lines = value.splitlines()
    bullet_lines = [
        line for line in lines
        if re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line)
    ]
    if len(bullet_lines) <= maximum:
        return value

    prefix = []
    for line in lines:
        if re.match(r"^\s*(?:[-*]|\d+[.)])\s+", line):
            break
        prefix.append(line)
    return "\n".join([*prefix, *bullet_lines[:maximum]])


def _format_azure_devops_evidence(evidence):
    if not evidence:
        return "No Azure DevOps evidence available."

    sections = []
    for item in evidence:
        identifier_label = (
            "Pull Request ID"
            if item.get("type") == "pull_request"
            else "Work Item ID"
        )
        sections.append(
            f"{identifier_label}: {item.get('id', '')}\n"
            f"Title: {item.get('title', '')}\n"
            f"State: {item.get('state', '')}\n"
            f"Description: {item.get('description', '')}\n"
            "Referenced By:\n"
            f"{_format_runbook_list(item.get('referenced_by', []))}"
        )
    return "\n\n".join(sections)


def _format_report_review(review):
    if not review:
        return "No report review available."

    return (
        f"Confidence: {review.get('confidence', '')}\n"
        f"Report Quality: {review.get('report_quality', '')}\n"
        f"Evidence Coverage: {review.get('evidence_coverage', '')}\n\n"
        f"Missing Evidence:\n"
        f"{_format_review_list(review.get('missing_evidence', [])[:5])}\n\n"
        f"Unsupported Claims:\n"
        f"{_format_review_list(review.get('unsupported_claims', []))}\n\n"
        f"Recommended Next Steps:\n"
        f"{_format_review_list(review.get('recommended_next_steps', [])[:5])}\n\n"
        f"Review Summary: {review.get('review_summary', '')}"
    )


def _combine_document_content(evidence, file_name):
    contents = []
    seen_chunks = set()

    for item in evidence:
        if item.get("file") != file_name:
            continue

        chunk_id = item.get("chunk_id")
        if chunk_id is not None:
            chunk_key = str(chunk_id)
            if chunk_key in seen_chunks:
                continue
            seen_chunks.add(chunk_key)

        content = item.get("content", "")
        if content:
            contents.append(content)

    return "\n\n".join(contents)


def _generate_report(messages):
    def request(max_completion_tokens):
        response = client.chat.completions.create(
            model=GPT5_MINI_DEPLOYMENT,
            messages=messages,
            response_format={"type": "json_object"},
            max_completion_tokens=max_completion_tokens,
        )
        choice = response.choices[0]
        content = getattr(choice.message, "content", None)
        finish_reason = getattr(choice, "finish_reason", None)
        print(
            "Report generator: "
            f"finish_reason={finish_reason}, "
            f"has_content={bool(content)}"
        )
        return response, content, finish_reason

    response, report_text, finish_reason = request(5000)
    if report_text:
        return report_text

    if finish_reason == "length":
        response, report_text, finish_reason = request(7000)
        if report_text:
            return report_text

    raise ValueError(
        "The investigation report generator returned an empty response "
        f"(finish_reason={finish_reason})"
    )


def run_investigation(question, include_azure_devops=False):
    """Create an investigation plan, gather evidence, and generate a report."""
    plan = create_investigation_plan(question)
    incident_id = _plan_value(plan, "incident_id")
    deployment_id = _plan_value(plan, "deployment_id")
    planned_runbook = _plan_value(
        plan,
        "runbook_reference",
        "runbook",
        "runbook_id",
    )

    incident_evidence = []
    deployment_evidence = []
    primary_evidence = None
    primary_evidence_items = []
    if incident_id:
        incident_file = _as_file_name(incident_id, "incident")
        incident_evidence = tool_registry.get_incident(incident_file)
        if incident_evidence:
            primary_evidence = incident_evidence[0]
            primary_evidence_items = _mark_primary(incident_evidence)

    direct_deployment = (
        not incident_id
        and (
            deployment_id
            or plan.get("investigation_type") == "deployment"
        )
    )

    if incident_id:
        initial_evidence = incident_evidence.copy()
    elif incident_evidence:
        initial_evidence = incident_evidence.copy()
    elif direct_deployment:
        initial_evidence = []
    else:
        initial_evidence = tool_registry.get_incident(question)

    deployment_files, incident_files, runbook_files = _extract_references(
        initial_evidence,
        primary_evidence=primary_evidence,
    )

    primary_deployment = _as_file_name(deployment_id, "deployment")
    if primary_deployment:
        deployment_files = [
            primary_deployment,
            *[file_name for file_name in deployment_files
              if file_name != primary_deployment],
        ]

    primary_runbook = _as_file_name(planned_runbook)
    if primary_runbook:
        runbook_files = [
            primary_runbook,
            *[file_name for file_name in runbook_files
              if file_name != primary_runbook],
        ]

    if deployment_files or primary_deployment or plan.get("search_deployment"):
        if primary_deployment:
            if not deployment_evidence:
                deployment_evidence = tool_registry.get_deployment(
                    primary_deployment
                )
            if deployment_evidence:
                primary_evidence = deployment_evidence[0]
                primary_evidence_items = _mark_primary(deployment_evidence)
                initial_evidence.extend(deployment_evidence)
            elif not incident_id:
                primary_evidence = None
                primary_evidence_items = []
        else:
            primary_evidence = None
            primary_evidence_items = []
        if not primary_deployment:
            for deployment_file in deployment_files:
                additional_deployment_evidence = tool_registry.get_deployment(
                    deployment_file
                )
                deployment_evidence.extend(additional_deployment_evidence)
                initial_evidence.extend(additional_deployment_evidence)

    deployment_files, incident_files, runbook_files = _extract_references(
        initial_evidence,
        primary_evidence=primary_evidence,
    )

    for incident_file in incident_files:
        if incident_id and incident_file == _as_file_name(incident_id, "incident"):
            continue
        linked_incident_evidence = tool_registry.get_incident(incident_file)
        initial_evidence.extend(linked_incident_evidence)

    azure_devops_evidence = []
    if include_azure_devops:
        deployment_text = "\n".join(
            item.get("content", "")
            for item in deployment_evidence
        )
        work_item_ids = set(
            AZDO_WORK_ITEM_PATTERN.findall(deployment_text)
        )
        pull_request_ids = set(
            AZDO_PULL_REQUEST_PATTERN.findall(deployment_text)
        )
        work_item_sources = {}
        pull_request_sources = {}

        for item in deployment_evidence:
            deployment_file = item.get("file", "")
            deployment_name = _basename(deployment_file)
            deployment_name = deployment_name.removesuffix(".md")

            for work_item_id in AZDO_WORK_ITEM_PATTERN.findall(
                item.get("content", "")
            ):
                work_item_ids.add(work_item_id)
                work_item_sources.setdefault(work_item_id, set()).add(
                    deployment_name
                )

            for pull_request_id in AZDO_PULL_REQUEST_PATTERN.findall(
                item.get("content", "")
            ):
                pull_request_ids.add(pull_request_id)
                pull_request_sources.setdefault(pull_request_id, set()).add(
                    deployment_name
                )

        repository_match = AZDO_REPOSITORY_PATTERN.search(deployment_text)
        repository_id = repository_match.group(1) if repository_match else None

        for work_item_id in sorted(work_item_ids):
            work_item = tool_registry.get_work_item(work_item_id)
            if work_item:
                work_item["type"] = "work_item"
                work_item["referenced_by"] = sorted(
                    work_item_sources.get(work_item_id, set())
                )
                azure_devops_evidence.append(work_item)

        if repository_id:
            for pull_request_id in sorted(pull_request_ids):
                pull_request = tool_registry.get_pull_request(
                    repository_id,
                    pull_request_id,
                )
                if pull_request:
                    pull_request["type"] = "pull_request"
                    pull_request["referenced_by"] = sorted(
                        pull_request_sources.get(pull_request_id, set())
                    )
                    azure_devops_evidence.append(pull_request)

    runbook_evidence = []
    if runbook_files or primary_runbook or plan.get("search_runbooks"):
        if primary_runbook:
            runbook_evidence = tool_registry.get_runbook(primary_runbook)
            if runbook_evidence and primary_evidence is None:
                primary_evidence = runbook_evidence[0]
                primary_evidence_items = _mark_primary(runbook_evidence)
            else:
                initial_evidence.extend(runbook_evidence)
        for runbook_file in runbook_files:
            if runbook_file != primary_runbook:
                additional_runbook_evidence = tool_registry.get_runbook(
                    runbook_file
                )
                runbook_evidence.extend(additional_runbook_evidence)
                initial_evidence.extend(additional_runbook_evidence)

    evidence_candidates = [
        *initial_evidence,
        *primary_evidence_items,
    ]
    selected_deployment, selected_deployment_items = (
        _select_primary_deployment(
            evidence_candidates,
            deployment_id,
        )
    )

    if selected_deployment and not incident_id:
        primary_evidence = selected_deployment
        primary_evidence_items = selected_deployment_items

    if primary_evidence is None and incident_evidence:
        primary_evidence = incident_evidence[0]
        primary_evidence_items = _mark_primary(incident_evidence)

    deployment_analysis = None
    deployment_evidence_item = selected_deployment
    if deployment_evidence_item is None:
        deployment_evidence_item = next(
            (
                item
                for item in evidence_candidates
                if item.get("category") == "deployment"
            ),
            None,
        )

    if deployment_evidence_item:
        deployment_file = deployment_evidence_item.get("file")
        deployment_content = _combine_document_content(
            evidence_candidates,
            deployment_file,
        )
        deployment_analysis = analyze_deployment(
            deployment_file,
            deployment_content,
        )

    runbook_analysis = None
    runbook_evidence_item = None
    if primary_runbook:
        runbook_evidence_item = next(
            (
                item
                for item in evidence_candidates
                if _basename(item.get("file", ""))
                == _basename(primary_runbook)
            ),
            None,
        )
    if runbook_evidence_item is None:
        runbook_evidence_item = next(
            (
                item
                for item in evidence_candidates
                if item.get("category") == "runbook"
            ),
            None,
        )

    if runbook_evidence_item:
        runbook_file = runbook_evidence_item.get("file")
        runbook_content = _combine_document_content(
            evidence_candidates,
            runbook_file,
        )
        runbook_analysis = analyze_runbook(
            runbook_file,
            runbook_content,
        )

    primary_files = (
        [primary_evidence["file"]]
        if primary_evidence
        else []
    )

    primary_file = primary_evidence["file"] if primary_evidence else None
    supporting_evidence = [
        item for item in initial_evidence
        if item.get("file") != primary_file
    ]
    primary_evidence_items = _deduplicate_evidence(
        primary_evidence_items
    )
    supporting_evidence = _deduplicate_evidence(supporting_evidence)
    supporting_evidence = _limit_supporting_evidence(supporting_evidence)

    if primary_evidence is None:
        primary_evidence_items = []

    selected_factual_evidence = _deduplicate_evidence(
        [*primary_evidence_items, *supporting_evidence]
    )
    retrieved_files = {
        _basename(item.get("file", ""))
        for item in selected_factual_evidence
    }
    referenced_files = _ordered_unique(
        [*deployment_files, *incident_files, *runbook_files]
    )
    unretrieved_references = [
        file_name
        for file_name in referenced_files
        if _basename(file_name) not in retrieved_files
    ]

    if primary_evidence:
        print(f"Primary Evidence: {primary_evidence['file']}")
    else:
        print("Primary Evidence: None identified")

    report_text = _generate_report([
        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Investigation plan:\n{json.dumps(plan, indent=2)}\n\n"
                f"Primary Evidence Files: {', '.join(primary_files) or 'None'}\n\n"
                f"Deployment Analysis:\n"
                f"{json.dumps(deployment_analysis, indent=2) if deployment_analysis else 'None available.'}\n\n"
                f"Runbook Analysis:\n"
                f"{json.dumps(runbook_analysis, indent=2) if runbook_analysis else 'None available.'}\n\n"
                f"Azure DevOps Evidence:\n"
                f"{_format_azure_devops_evidence(azure_devops_evidence)}\n\n"
                f"Referenced but not retrieved (existence only):\n"
                f"{', '.join(unretrieved_references) or 'None'}\n\n"
                f"{_format_context(primary_evidence_items, supporting_evidence)}"
            ),
        },
    ])

    report = json.loads(report_text)
    report["Recommendations"] = _limit_recommendations(
        report.get("Recommendations", "")
    )
    report["Deployment Analysis"] = _format_deployment_analysis(
        deployment_analysis,
        has_evidence=deployment_evidence_item is not None,
    )
    report["Runbook Analysis"] = _format_runbook_analysis(runbook_analysis)
    report["Azure DevOps Evidence"] = _format_azure_devops_evidence(
        azure_devops_evidence
    )
    report_text = _format_report(report, primary_files)
    evidence_text = (
        _format_evidence(selected_factual_evidence)
        or "None available."
    )
    if azure_devops_evidence:
        evidence_text += (
            "\n\nAZURE DEVOPS EVIDENCE\n\n"
            f"{_format_azure_devops_evidence(azure_devops_evidence)}"
        )
    report_review = review_report(report_text, evidence_text)
    report["Report Review"] = _format_report_review(report_review)
    report_text = _format_report(report, primary_files)

    return report_text, [
        *primary_evidence_items,
        *supporting_evidence,
    ]


if __name__ == "__main__":
    include_azure_devops = input(
        "Would you like to include Azure DevOps work item and pull request evidence? (y/n): "
    ).strip().lower() == "y"
    user_question = input("Question: ")
    report_text, evidence = run_investigation(
        user_question,
        include_azure_devops=include_azure_devops,
    )

    print("\nInvestigation Report:\n")
    print(report_text)
    print("\nEvidence:")

    for item in evidence:
        print(
            f"- [{item['category']}] {item['file']} "
            f"(chunk {item['chunk_id']})"
        )
