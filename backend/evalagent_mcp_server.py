"""MCP server exposing evalagent investigation tools."""

from mcp.server.mcpserver import MCPServer

try:
    from . import tool_implementations
    from .observability import configure_logging, mcp_tool_telemetry
except ImportError:
    import tool_implementations
    from observability import configure_logging, mcp_tool_telemetry


mcp = MCPServer(
    name="evalagent-investigation-tools",
    description=(
        "Investigation retrieval tools for incidents, deployments, runbooks, "
        "Azure DevOps, and Application Insights evidence."
    ),
)


@mcp.tool()
@mcp_tool_telemetry
def get_incident(incident_id: str) -> list[dict]:
    """Retrieve an incident by ID or search incident evidence by question."""
    return tool_implementations.get_incident(incident_id)


@mcp.tool()
@mcp_tool_telemetry
def get_deployment(deployment_id: str) -> list[dict]:
    """Retrieve deployment evidence by ID or document name."""
    return tool_implementations.get_deployment(deployment_id)


@mcp.tool()
@mcp_tool_telemetry
def get_runbook(runbook_name: str) -> list[dict]:
    """Retrieve runbook evidence by name."""
    return tool_implementations.get_runbook(runbook_name)


@mcp.tool()
@mcp_tool_telemetry
def get_work_item(work_item_id: str) -> dict:
    """Retrieve an Azure DevOps work item."""
    return tool_implementations.get_work_item(work_item_id)


@mcp.tool()
@mcp_tool_telemetry
def get_pull_request(repository_id: str, pr_id: str) -> dict:
    """Retrieve an Azure DevOps pull request."""
    return tool_implementations.get_pull_request(repository_id, pr_id)


@mcp.tool()
@mcp_tool_telemetry
def get_release(release_id: str) -> dict:
    """Retrieve an Azure DevOps release for future investigation workflows."""
    return tool_implementations.get_release(release_id)


@mcp.tool()
@mcp_tool_telemetry
def get_application_insights_telemetry(
    service_name: str,
    start_time: str,
    end_time: str,
    incident_id: str | None = None,
    max_records: int = 200,
) -> dict:
    """Retrieve normalized Application Insights telemetry for a time range."""
    return tool_implementations.get_application_insights_telemetry(
        service_name,
        start_time,
        end_time,
        incident_id,
        max_records,
    )


if __name__ == "__main__":
    configure_logging("mcp_server")
    mcp.run("stdio")
