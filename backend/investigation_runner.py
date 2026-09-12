import json
import os
import re

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv

try:
    from .deployment_agent import analyze_deployment
    from .investigator_agent import (
        GPT5_MINI_DEPLOYMENT,
        client,
        create_investigation_plan,
    )
    from .search_ai_search import search_chunks
except ImportError:
    from deployment_agent import analyze_deployment
    from investigator_agent import (
        GPT5_MINI_DEPLOYMENT,
        client,
        create_investigation_plan,
    )
    from search_ai_search import search_chunks

load_dotenv()

DEPLOYMENT_PATTERN = re.compile(r"\bdeployment[- ](\d+)\b", re.IGNORECASE)
RUNBOOK_PATTERN = re.compile(
    r"\b[a-z0-9][a-z0-9-]*-runbook(?:\.md)?\b",
    re.IGNORECASE,
)


REPORT_SECTIONS = (
    "Primary Evidence",
    "Deployment Analysis",
    "Incident",
    "Root Cause",
    "Impact",
    "Resolution",
    "Related Documents",
    "Recommendations",
)


REPORT_SYSTEM_PROMPT = """You are an incident investigation report writer.
Use only the investigation plan and evidence provided by the user.
Return a valid JSON object with exactly these keys:
- Deployment Analysis
- Incident
- Root Cause
- Impact
- Resolution
- Related Documents
- Recommendations
- Primary Evidence

Each value must be a concise markdown-ready string. Clearly state when the
available evidence does not establish an answer. Do not invent facts.
Focus the report on the PRIMARY EVIDENCE.
Supporting documents provide additional context only.
The Deployment Analysis value must include Change Summary, Risk Rating,
Related Incidents, and Rollback Status when deployment evidence is available.
"""


def _search_with_category(query, category):
    return [
        {
            "category": category,
            "file": result.get("file"),
            "chunk_id": result.get("chunk_id"),
            "content": result.get("content", ""),
        }
        for result in search_chunks(query)
    ]


def _search_document(file_name, category):
    search_client = SearchClient(
        endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        index_name=os.getenv("AZURE_SEARCH_INDEX"),
        credential=AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY")),
    )

    results = search_client.search(
        search_text="*",
        select=["file", "chunk_id", "content"],
        top=1000,
    )

    return [
        {
            "category": category,
            "primary": False,
            "file": result.get("file"),
            "chunk_id": result.get("chunk_id"),
            "content": result.get("content", ""),
        }
        for result in results
        if file_name.lower() in str(result.get("file", "")).lower()
    ]


def _mark_primary(evidence):
    for item in evidence:
        item["primary"] = True
    return evidence


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


def _extract_references(evidence):
    document_text = "\n".join(item["content"] for item in evidence)
    deployment_files = {
        f"deployment-{deployment_id}.md"
        for deployment_id in DEPLOYMENT_PATTERN.findall(document_text)
    }
    runbook_files = {
        runbook if runbook.endswith(".md") else f"{runbook}.md"
        for runbook in RUNBOOK_PATTERN.findall(document_text)
    }
    return sorted(deployment_files), sorted(runbook_files)


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

    for item in evidence:
        file_name = item.get("file")
        document = documents.setdefault(
            file_name,
            {
                **item,
                "content": "",
                "chunk_ids": [],
            },
        )

        content = item.get("content", "")
        if content:
            if document["content"]:
                document["content"] += f"\n\n{content}"
            else:
                document["content"] = content

        chunk_id = item.get("chunk_id")
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


def _format_deployment_analysis(analysis):
    if not analysis:
        return "No deployment evidence available."

    return (
        f"Change Summary: {analysis.get('change_summary', '')}\n"
        f"Risk Rating: {analysis.get('risk_rating', '')}\n"
        f"Related Incidents: {', '.join(analysis.get('related_incidents', []))}\n"
        f"Rollback Status: {analysis.get('rollback_status', '')}"
    )


def run_investigation(question):
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
    primary_evidence = None
    primary_evidence_items = []
    if incident_id:
        incident_file = _as_file_name(incident_id, "incident")
        incident_evidence = _search_document(incident_file, "incident")

    if incident_evidence:
        initial_evidence = incident_evidence.copy()
    else:
        initial_evidence = _search_with_category(question, "incident")

    deployment_files, runbook_files = _extract_references(initial_evidence)

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

    if primary_deployment or plan.get("search_deployment"):
        if primary_deployment:
            deployment_evidence = _search_document(
                primary_deployment,
                "deployment",
            )
            if deployment_evidence:
                primary_evidence = deployment_evidence[0]
                primary_evidence_items = _mark_primary(deployment_evidence)
            else:
                primary_evidence = None
                primary_evidence_items = []
        else:
            primary_evidence = None
            primary_evidence_items = []
        for deployment_file in deployment_files:
            if deployment_file != primary_deployment:
                initial_evidence.extend(
                    _search_document(deployment_file, "deployment")
                )

    if primary_runbook or plan.get("search_runbooks"):
        if primary_runbook:
            runbook_evidence = _search_document(
                primary_runbook,
                "runbook",
            )
            if runbook_evidence and primary_evidence is None:
                primary_evidence = runbook_evidence[0]
                primary_evidence_items = _mark_primary(runbook_evidence)
            else:
                initial_evidence.extend(runbook_evidence)
        for runbook_file in runbook_files:
            if runbook_file != primary_runbook:
                initial_evidence.extend(
                    _search_document(runbook_file, "runbook")
                )

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

    if selected_deployment:
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
        deployment_content = "\n\n".join(
            item.get("content", "")
            for item in evidence_candidates
            if item.get("file") == deployment_file
        )
        deployment_analysis = analyze_deployment(
            deployment_file,
            deployment_content,
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

    if primary_evidence:
        print(f"Primary Evidence: {primary_evidence['file']}")
    else:
        print("Primary Evidence: None identified")

    response = client.chat.completions.create(
        model=GPT5_MINI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": REPORT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Investigation plan:\n{json.dumps(plan, indent=2)}\n\n"
                    f"Primary Evidence Files: {', '.join(primary_files) or 'None'}\n\n"
                    f"Deployment Analysis:\n"
                    f"{json.dumps(deployment_analysis, indent=2) if deployment_analysis else 'None available.'}\n\n"
                    f"{_format_context(primary_evidence_items, supporting_evidence)}"
                ),
            },
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=3000,
    )

    report_text = response.choices[0].message.content
    if not report_text:
        raise ValueError("The investigation report generator returned an empty response")

    report = json.loads(report_text)
    report["Deployment Analysis"] = _format_deployment_analysis(
        deployment_analysis
    )
    return _format_report(report, primary_files), [
        *primary_evidence_items,
        *supporting_evidence,
    ]


if __name__ == "__main__":
    user_question = input("Question: ")
    report_text, evidence = run_investigation(user_question)

    print("\nInvestigation Report:\n")
    print(report_text)
    print("\nEvidence:")

    for item in evidence:
        print(
            f"- [{item['category']}] {item['file']} "
            f"(chunk {item['chunk_id']})"
        )
