"""Direct implementations behind the ToolRegistry and MCP server."""

import re

try:
    from .application_insights_client import (
        get_application_insights_telemetry as query_application_insights,
    )
    from .azure_devops_client import azure_devops_client
    from .search_ai_search import search_chunks, search_document
except ImportError:
    from application_insights_client import (
        get_application_insights_telemetry as query_application_insights,
    )
    from azure_devops_client import azure_devops_client
    from search_ai_search import search_chunks, search_document


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


def _is_incident_file(file_name):
    return bool(
        file_name
        and re.fullmatch(r"incident-\d+\.md", file_name, re.IGNORECASE)
    )


def _with_category(results, category):
    return [
        {
            **result,
            "source": "azure_ai_search",
            "category": category,
            "primary": False,
        }
        for result in results
    ]


def get_incident(incident_id):
    if incident_id is None:
        return []

    incident_file = _as_file_name(incident_id, "incident")
    if incident_file and (
        str(incident_id).strip().isdigit()
        or _is_incident_file(incident_file)
    ):
        return _with_category(search_document(incident_file), "incident")

    return _with_category(search_chunks(incident_id), "incident")


def get_deployment(deployment_id):
    if deployment_id is None:
        return []

    deployment_file = _as_file_name(deployment_id, "deployment")
    return _with_category(search_document(deployment_file), "deployment")


def get_runbook(runbook_name):
    if runbook_name is None:
        return []

    runbook_file = _as_file_name(runbook_name)
    return _with_category(search_document(runbook_file), "runbook")


def get_work_item(work_item_id):
    return azure_devops_client.get_work_item(work_item_id)


def get_pull_request(repository_id, pr_id):
    return azure_devops_client.get_pull_request(repository_id, pr_id)


def get_release(release_id):
    return azure_devops_client.get_release(release_id)


def get_application_insights_telemetry(
    service_name,
    start_time,
    end_time,
    incident_id=None,
    max_records=200,
):
    return query_application_insights(
        service_name,
        start_time,
        end_time,
        incident_id,
        max_records,
    )
