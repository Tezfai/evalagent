"""Synchronous MCP client for the evalagent investigation tool server."""

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client


SERVER_MODULE = "backend.evalagent_mcp_server"
SERVER_ROOT = Path(__file__).resolve().parents[1]
TOOL_NAMES = (
    "get_incident",
    "get_deployment",
    "get_runbook",
    "get_work_item",
    "get_pull_request",
    "get_release",
)


def _server_parameters():
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", SERVER_MODULE],
        cwd=SERVER_ROOT,
    )


def _decode_result(result):
    if getattr(result, "is_error", False):
        raise RuntimeError("MCP tool call failed")

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


async def _call_tool_async(name, arguments):
    if name not in TOOL_NAMES:
        raise ValueError(f"Unsupported MCP tool: {name}")

    try:
        async with stdio_client(_server_parameters()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments=arguments)
                return _decode_result(result)
    except ValueError:
        raise
    except Exception as error:
        raise RuntimeError(f"MCP tool '{name}' is unavailable") from error


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


if __name__ == "__main__":
    print("\n".join(list_tool_names()))
