"""Synchronous MCP client for the evalagent investigation tool server."""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client

try:
    from .observability import (
        current_investigation_id,
        emit_event,
        mark_request_metrics_incomplete,
        record_remote_request,
    )
except ImportError:
    from observability import (
        current_investigation_id,
        emit_event,
        mark_request_metrics_incomplete,
        record_remote_request,
    )


SERVER_MODULE = "backend.evalagent_mcp_server"
SERVER_ROOT = Path(__file__).resolve().parents[1]
SERVER_ENVIRONMENT_VARIABLES = (
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
    "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY", "AZURE_SEARCH_INDEX",
    "AZDO_ORG", "AZDO_PROJECT", "AZDO_PAT", "APPLICATIONINSIGHTS_WORKSPACE_ID",
    "AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_CLIENT_SECRET", "AZURE_AUTHORITY_HOST",
    "AZURE_CLIENT_CERTIFICATE_PATH", "AZURE_CLIENT_CERTIFICATE_PASSWORD",
    "AZURE_CLIENT_SEND_CERTIFICATE_CHAIN", "AZURE_FEDERATED_TOKEN_FILE", "AZURE_TOKEN_CREDENTIALS",
    "IDENTITY_ENDPOINT", "IDENTITY_HEADER", "IDENTITY_SERVER_THUMBPRINT",
    "MSI_ENDPOINT", "MSI_SECRET", "IMDS_ENDPOINT",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "PYTHON_DOTENV_DISABLED", "PYTHONDONTWRITEBYTECODE",
)
TOOL_NAMES = (
    "get_incident",
    "get_deployment",
    "get_runbook",
    "get_work_item",
    "get_pull_request",
    "get_release",
    "get_application_insights_telemetry",
)


def _server_parameters():
    environment = {
        name: os.environ[name]
        for name in SERVER_ENVIRONMENT_VARIABLES
        if name in os.environ
    }
    environment["EVALAGENT_PROCESS_ROLE"] = "mcp_server"
    investigation_id = current_investigation_id()
    if investigation_id:
        environment["EVALAGENT_INVESTIGATION_ID"] = investigation_id

    return StdioServerParameters(
        command=sys.executable,
        args=["-m", SERVER_MODULE],
        cwd=SERVER_ROOT,
        env=environment,
    )


def _decode_result(result):
    if getattr(result, "is_error", False):
        raise RuntimeError("MCP tool call failed")
    # If the result is neither an error nor contains structured content, fall back to text content.
    structured_content = getattr(result, "structured_content", None)
    if structured_content is not None:
        if isinstance(structured_content, dict) and "result" in structured_content:
            return structured_content["result"]
        return structured_content

    text_parts = [
        item.text
        for item in getattr(result, "content", [])
        if getattr(item, "type", None) == "text"
    ]
    if not text_parts:
        raise RuntimeError("MCP tool returned no result")

    import json

    try:
        return json.loads("".join(text_parts))
    except json.JSONDecodeError as error:
        raise RuntimeError("MCP tool returned an invalid result") from error


def _relay_child_stderr(capture, investigation_id):
    """Collect recognized metrics without forwarding unstructured child output."""
    complete = False
    try:
        capture.flush()
        capture.seek(0)
        contents = capture.read()
        if isinstance(contents, bytes):
            contents = contents.decode("utf-8", errors="replace")
        suppressed_lines = 0
        request_ids = set()
        checkpoints = []
        records_valid = True
        for line in contents.splitlines():
            try:
                payload = json.loads(line)
            except (TypeError, json.JSONDecodeError):
                suppressed_lines += 1
                continue
            if (
                isinstance(payload, dict)
                and payload.get("event") == "llm.request.finished"
                and payload.get("component") == "evalagent.llm"
            ):
                request_id = payload.get("request_id")
                if (
                    not isinstance(request_id, str)
                    or request_id in request_ids
                    or not record_remote_request(payload, investigation_id)
                ):
                    records_valid = False
                    suppressed_lines += 1
                else:
                    request_ids.add(request_id)
            elif (
                isinstance(payload, dict)
                and payload.get("event") == "mcp.telemetry.finished"
                and payload.get("component") == "evalagent.mcp"
                and payload.get("investigation_id") == investigation_id
            ):
                checkpoints.append(payload)
            else:
                suppressed_lines += 1
        if len(checkpoints) == 1:
            checkpoint = checkpoints[0]
            count = checkpoint.get("calls_attempted")
            complete = (
                records_valid
                and checkpoint.get("request_metrics_complete") is True
                and isinstance(count, int) and not isinstance(count, bool)
                and count == len(request_ids)
            )
        if suppressed_lines:
            emit_event(
                "mcp.child_stderr.suppressed",
                component="evalagent.mcp",
                line_count=suppressed_lines,
            )
    except Exception as error:
        emit_event(
            "mcp.stderr_relay.failed",
            component="evalagent.mcp",
            level=40,
            error_type=type(error).__name__,
        )
    finally:
        if not complete:
            mark_request_metrics_incomplete(investigation_id)


async def _call_tool_async(name, arguments):
    if name not in TOOL_NAMES:
        raise ValueError(f"Unsupported MCP tool: {name}")

    investigation_id = current_investigation_id()
    capture = None
    relay_capture = False
    try:
        capture = tempfile.TemporaryFile(mode="w+b")
        relay_capture = True
    except OSError as error:
        mark_request_metrics_incomplete()
        emit_event(
            "mcp.stderr_capture.unavailable",
            component="evalagent.mcp",
            level=40,
            error_type=type(error).__name__,
        )
        try:
            capture = open(os.devnull, "w+b")
        except OSError as sink_error:
            emit_event(
                "mcp.stderr_sink.unavailable",
                component="evalagent.mcp",
                level=40,
                error_type=type(sink_error).__name__,
            )
            raise RuntimeError("MCP server stderr could not be isolated") from sink_error

    try:
        server_context = stdio_client(
            _server_parameters(),
            errlog=capture,
        )
        async with server_context as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=arguments)
                return _decode_result(result)
    except ValueError:
        raise
    except Exception as error:
        raise RuntimeError(f"MCP tool '{name}' is unavailable") from error
    finally:
        if capture is not None:
            if relay_capture:
                try:
                    _relay_child_stderr(capture, investigation_id)
                except Exception as error:
                    mark_request_metrics_incomplete()
                    emit_event(
                        "mcp.stderr_relay.failed",
                        component="evalagent.mcp",
                        level=40,
                        error_type=type(error).__name__,
                    )
            try:
                capture.close()
            except OSError as error:
                emit_event(
                    "mcp.stderr_capture.close_failed",
                    component="evalagent.mcp",
                    level=40,
                    error_type=type(error).__name__,
                )


def call_tool(name, **arguments):
    """Call one MCP tool synchronously without exposing transport details."""
    try:
        return asyncio.run(_call_tool_async(name, arguments))
    except ValueError:
        raise
    except Exception as error:
        raise RuntimeError(f"MCP tool '{name}' is unavailable") from error


def list_tool_names():
    """List server tools without invoking any investigation tool."""
    async def _list():
        try:
            async with stdio_client(_server_parameters()) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [tool.name for tool in result.tools]
        except Exception as error:
            raise RuntimeError("MCP tool listing is unavailable") from error

    return asyncio.run(_list())


def get_incident(incident_id):
    return call_tool("get_incident", incident_id=incident_id)


def get_deployment(deployment_id):
    return call_tool("get_deployment", deployment_id=deployment_id)


def get_runbook(runbook_name):
    return call_tool("get_runbook", runbook_name=runbook_name)


def get_work_item(work_item_id):
    return call_tool("get_work_item", work_item_id=work_item_id)


def get_pull_request(repository_id, pr_id):
    return call_tool(
        "get_pull_request",
        repository_id=repository_id,
        pr_id=pr_id,
    )


def get_release(release_id):
    return call_tool("get_release", release_id=release_id)


def get_application_insights_telemetry(
    service_name,
    start_time,
    end_time,
    incident_id=None, 
    max_records=200,
):
    return call_tool(
        "get_application_insights_telemetry",
        service_name=service_name,
        start_time=start_time,
        end_time=end_time,
        incident_id=incident_id,
        max_records=max_records,
    )


if __name__ == "__main__":
    print("\n".join(list_tool_names()))
