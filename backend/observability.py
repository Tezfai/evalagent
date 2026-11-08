"""Lightweight structured logging and per-operation LLM metrics."""

from __future__ import annotations

import contextvars
import json
import logging
import math
import os
import re
import sys
import time
import traceback
from collections import defaultdict
from functools import wraps
from threading import Lock
from uuid import uuid4


_LOGGER_NAME = "evalagent"
_CURRENT_OPERATION = contextvars.ContextVar(
    "evalagent_current_operation",
    default=None,
)
_COMPLETED_METRICS = contextvars.ContextVar(
    "evalagent_completed_metrics",
    default=None,
)

_EVENT_FIELDS = {
    "llm.request.finished": (
        "evalagent.llm",
        {
            "request_id",
            "stage",
            "request_type",
            "deployment",
            "duration_ms",
            "status",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "usage_available",
            "finish_reason",
            "error_type",
            "http_status",
            "traceback",
        },
    ),
    "agent.started": ("evalagent.agent", {"stage"}),
    "agent.finished": (
        "evalagent.agent",
        {"stage", "status", "duration_ms", "error_type", "http_status", "traceback"},
    ),
    "agent.response_empty": (
        "evalagent.agent",
        {"stage", "finish_reason"},
    ),
    "investigation.started": ("evalagent.investigation", set()),
    "investigation.failed": (
        "evalagent.investigation",
        {"error_type", "http_status", "traceback"},
    ),
    "investigation.finished": (
        "evalagent.investigation",
        {
            "status",
            "duration_ms",
            "calls_attempted",
            "calls_successful",
            "calls_failed",
            "request_metrics_complete",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "token_totals_complete",
            "estimated_cost",
        },
    ),
    "tool.finished": (
        "evalagent.tool",
        {"tool", "status", "duration_ms", "error_type"},
    ),
    "mcp.telemetry.finished": (
        "evalagent.mcp",
        {"calls_attempted", "request_metrics_complete"},
    ),
    "mcp.child_stderr.suppressed": ("evalagent.mcp", {"line_count"}),
    "mcp.stderr_relay.failed": ("evalagent.mcp", {"error_type"}),
    "mcp.stderr_capture.unavailable": ("evalagent.mcp", {"error_type"}),
    "mcp.stderr_sink.unavailable": ("evalagent.mcp", {"error_type"}),
    "mcp.stderr_capture.close_failed": ("evalagent.mcp", {"error_type"}),
    "evidence.primary_selected": (
        "evalagent.investigation",
        {"status"},
    ),
    "retrieval.document_not_found": (
        "evalagent.retrieval",
        {"candidate_count"},
    ),
}

_STAGE_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z")
_REQUEST_ID_PATTERN = re.compile(r"[A-Fa-f0-9-]{36}\Z")
_TRACE_FRAME_PATTERN = re.compile(
    r"(?:[A-Za-z0-9_.-]{1,255}:\d+:[A-Za-z0-9_<>.-]{1,128})(?:\n"
    r"[A-Za-z0-9_.-]{1,255}:\d+:[A-Za-z0-9_<>.-]{1,128})*\Z"
)
_TOOL_NAMES = {
    "get_incident",
    "get_deployment",
    "get_runbook",
    "get_work_item",
    "get_pull_request",
    "get_release",
    "get_application_insights_telemetry",
}


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        return record.getMessage()


def configure_logging(process_role=None):
    """Configure one JSON console handler for this process."""
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    role = process_role or os.getenv("EVALAGENT_PROCESS_ROLE", "web")
    if not logger.handlers:
        stream = sys.stderr if role == "mcp_server" else sys.stdout
        handler = logging.StreamHandler(stream)
        handler.setFormatter(_JsonFormatter())
        handler._evalagent_handler = True
        logger.addHandler(handler)

    return logger


def _correlation_id():
    operation = _CURRENT_OPERATION.get()
    if operation is not None:
        candidate = operation.operation_id
        return (
            candidate
            if isinstance(candidate, str)
            and _REQUEST_ID_PATTERN.fullmatch(candidate)
            else None
        )
    candidate = os.getenv("EVALAGENT_INVESTIGATION_ID")
    return candidate if _REQUEST_ID_PATTERN.fullmatch(candidate or "") else None


def current_investigation_id():
    return _correlation_id()


def _error_fields(error):
    try:
        status_code = getattr(error, "status_code", None)
        if status_code is None:
            status_code = getattr(
                getattr(error, "response", None),
                "status_code",
                None,
            )
        frames = traceback.extract_tb(error.__traceback__)
        safe_traceback = "\n".join(
            f"{os.path.basename(frame.filename)}:{frame.lineno}:{frame.name}"
            for frame in frames
        )
        result = {
            "error_type": type(error).__name__,
            "http_status": (
                status_code
                if isinstance(status_code, int) and not isinstance(status_code, bool)
                else None
            ),
            "traceback": safe_traceback,
        }
        return result
    except Exception:
        return {"error_type": type(error).__name__}


def _safe_event_fields(event, fields):
    schema = _EVENT_FIELDS.get(event)
    if schema is None:
        return {}
    allowed_fields = schema[1]
    safe = {}
    for name, value in fields.items():
        if name not in allowed_fields:
            continue
        if value is None:
            safe[name] = None
        elif name in {
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "calls_attempted",
            "calls_successful",
            "calls_failed",
            "http_status",
            "line_count",
            "candidate_count",
        }:
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                safe[name] = value
        elif name in {"duration_ms", "estimated_cost"}:
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            ):
                safe[name] = value
        elif name in {
            "usage_available",
            "request_metrics_complete",
            "token_totals_complete",
        }:
            if isinstance(value, bool):
                safe[name] = value
        elif name == "request_id":
            if isinstance(value, str) and _REQUEST_ID_PATTERN.fullmatch(value):
                safe[name] = value
        elif name == "stage":
            if isinstance(value, str) and _STAGE_PATTERN.fullmatch(value):
                safe[name] = value
        elif name == "request_type":
            if value in {"chat", "embeddings"}:
                safe[name] = value
        elif name == "deployment":
            if (
                isinstance(value, str)
                and _IDENTIFIER_PATTERN.fullmatch(value)
                and len(value) <= 64
            ):
                safe[name] = value
        elif name == "finish_reason":
            if value in {"stop", "length", "content_filter", "tool_calls", "function_call"}:
                safe[name] = value
        elif name == "status":
            allowed_statuses = {
                "success",
                "failed",
                "selected",
                "unavailable",
            }
            if value in allowed_statuses:
                safe[name] = value
        elif name == "tool":
            if value in _TOOL_NAMES:
                safe[name] = value
        elif name == "error_type":
            if isinstance(value, str) and _STAGE_PATTERN.fullmatch(value):
                safe[name] = value
        elif name == "traceback":
            if (
                isinstance(value, str)
                and len(value) <= 4096
                and _TRACE_FRAME_PATTERN.fullmatch(value)
            ):
                safe[name] = value
    return safe


def emit_event(event, *, component, level=logging.INFO, **fields):
    """Write an allowlisted JSON event without logging request or evidence text."""
    tool_collected = False
    try:
        schema = _EVENT_FIELDS.get(event)
        if (
            schema is None
            or component != schema[0]
            or level not in {logging.INFO, logging.WARNING, logging.ERROR}
        ):
            return
        process_role = os.getenv("EVALAGENT_PROCESS_ROLE", "web")
        if process_role not in {"web", "mcp_server"}:
            process_role = "web"
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "severity": logging.getLevelName(level),
            "component": component,
            "event": event,
            "process_role": process_role,
            "investigation_id": _correlation_id(),
        }
        payload.update(_safe_event_fields(event, fields))
        if event == "tool.finished":
            _record_execution("tools", payload)
            tool_collected = True
        configure_logging().log(
            level,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )
    except Exception:
        if event == "tool.finished" and not tool_collected:
            _mark_execution_incomplete(_CURRENT_OPERATION.get(), "tools")
        return


def _usage_value(usage, name):
    if usage is None:
        return None
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _request_metrics(response, request_type):
    usage = getattr(response, "usage", None)
    choices = getattr(response, "choices", None)
    finish_reason = (
        getattr(choices[0], "finish_reason", None)
        if choices
        else None
    )
    prompt_tokens = _usage_value(usage, "prompt_tokens")
    completion_tokens = (
        _usage_value(usage, "completion_tokens")
        if request_type == "chat"
        else None
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": _usage_value(usage, "total_tokens"),
        "usage_available": usage is not None,
        "finish_reason": finish_reason,
    }


class OperationMetrics:
    def __init__(self, operation_id):
        self.operation_id = operation_id
        try:
            self.started = time.perf_counter()
        except Exception:
            self.started = None
        self.requests = []
        self.agent_executions = []
        self.tool_executions = []
        self.execution_metrics_incomplete = set()
        self.request_metrics_incomplete = False
        self._lock = Lock()

    def record_request(self, request):
        with self._lock:
            self.requests.append(dict(request))

    def mark_request_metrics_incomplete(self):
        with self._lock:
            self.request_metrics_incomplete = True

    def record_execution(self, kind, record):
        with self._lock:
            records = (
                self.agent_executions if kind == "agents" else self.tool_executions
            )
            records.append(dict(record))

    def mark_execution_metrics_incomplete(self, kind):
        with self._lock:
            self.execution_metrics_incomplete.add(kind)

    def summary(self, status):
        with self._lock:
            requests = [dict(request) for request in self.requests]
            request_metrics_incomplete = self.request_metrics_incomplete
            agents = [dict(record) for record in self.agent_executions]
            tools = [dict(record) for record in self.tool_executions]
            execution_incomplete = set(self.execution_metrics_incomplete)

        by_stage = defaultdict(list)
        for request in requests:
            by_stage[request["stage"]].append(request)

        def summarize_requests(records):
            token_values = [record["total_tokens"] for record in records]
            tokens_complete = (
                not request_metrics_incomplete
                and all(value is not None for value in token_values)
            )
            prompt_values = [record["prompt_tokens"] for record in records]
            prompt_complete = (
                not request_metrics_incomplete
                and all(value is not None for value in prompt_values)
            )
            chat_records = [
                record for record in records if record["request_type"] == "chat"
            ]
            completion_values = [
                record["completion_tokens"] for record in chat_records
            ]
            completion_complete = all(
                value is not None for value in completion_values
            ) and not request_metrics_incomplete
            return {
                "calls_attempted": len(records),
                "calls_successful": sum(
                    record["status"] == "success" for record in records
                ),
                "calls_failed": sum(
                    record["status"] == "failed" for record in records
                ),
                "prompt_tokens": (
                    sum(prompt_values) if prompt_complete else None
                ),
                "prompt_tokens_complete": prompt_complete,
                "completion_tokens": (
                    sum(completion_values)
                    if completion_complete
                    else None
                ),
                "completion_tokens_complete": completion_complete,
                "total_tokens": sum(token_values) if tokens_complete else None,
                "token_totals_complete": tokens_complete,
                "duration_ms": round(
                    sum(record["duration_ms"] for record in records),
                    2,
                ),
            }

        def summarize_executions(records, kind, name):
            grouped = defaultdict(list)
            for record in records:
                grouped[record[name]].append(record)
            complete = kind not in execution_incomplete
            result = {}
            for label, executions in grouped.items():
                durations = [record["duration_ms"] for record in executions]
                duration_complete = complete and all(
                    duration is not None for duration in durations
                )
                successful = sum(record["status"] == "success" for record in executions)
                failed = sum(record["status"] == "failed" for record in executions)
                total_duration = (
                    round(sum(durations), 2) if duration_complete else None
                )
                result[label] = {
                    "calls_attempted": len(executions) if complete else None,
                    "calls_successful": successful if complete else None,
                    "calls_failed": failed if complete else None,
                    "duration_ms": total_duration,
                    "average_duration_ms": (
                        round(total_duration / len(executions), 2)
                        if total_duration is not None else None
                    ),
                    "status": (
                        ("mixed" if successful and failed else
                         "failed" if failed else "success")
                        if complete else "unavailable"
                    ),
                }
            return dict(sorted(result.items()))

        summary = summarize_requests(requests)
        llm_duration = summary["duration_ms"] if not request_metrics_incomplete else None
        agent_summary = summarize_executions(agents, "agents", "stage")
        tool_summary = summarize_executions(tools, "tools", "tool")
        tool_durations = [item["duration_ms"] for item in tool_summary.values()]
        tool_duration = (
            round(sum(tool_durations), 2)
            if "tools" not in execution_incomplete
            and all(duration is not None for duration in tool_durations)
            else None
        )
        operation_duration = (
            _elapsed_ms(self.started)
            if self.started is not None
            else None
        )
        summary.update({
            "investigation_id": self.operation_id,
            "status": status,
            "request_metrics_complete": not request_metrics_incomplete,
            "duration_ms": operation_duration,
            "llm_duration_ms": llm_duration,
            "tool_duration_ms": tool_duration,
            "unattributed_duration_ms": None,
            "agent_metrics_complete": "agents" not in execution_incomplete,
            "tool_metrics_complete": "tools" not in execution_incomplete,
            "agent_stages": agent_summary,
            "tools": tool_summary,
            "requests": [
                {
                    name: value for name, value in
                    _safe_event_fields("llm.request.finished", request).items()
                    if name not in {"request_id", "error_type", "http_status", "traceback"}
                }
                for request in requests
            ],
            "estimated_cost": None,
            "cost_status": "not_configured",
            "stages": {
                stage: summarize_requests(records)
                for stage, records in sorted(by_stage.items())
            },
        })
        return summary


def _mark_operation_incomplete(operation):
    if operation is None:
        return
    try:
        operation.mark_request_metrics_incomplete()
    except Exception:
        try:
            operation.request_metrics_incomplete = True
        except Exception:
            pass


def _record_request(request):
    operation = _CURRENT_OPERATION.get()
    if operation is None:
        return True
    try:
        duration_ms = request.get("duration_ms")
        if (
            not isinstance(duration_ms, (int, float))
            or isinstance(duration_ms, bool)
            or not math.isfinite(duration_ms)
            or duration_ms < 0
        ):
            _mark_operation_incomplete(operation)
            return False
        operation.record_request(request)
        return True
    except Exception:
        _mark_operation_incomplete(operation)
        return False


def mark_request_metrics_incomplete(operation_id=None):
    operation = _CURRENT_OPERATION.get()
    if operation_id is not None and (
        operation is None or operation.operation_id != operation_id
    ):
        return
    _mark_operation_incomplete(operation)


def _mark_execution_incomplete(operation, kind):
    if operation is None:
        return
    try:
        operation.mark_execution_metrics_incomplete(kind)
    except Exception:
        try:
            operation.execution_metrics_incomplete.add(kind)
        except Exception:
            pass


def _record_execution(kind, fields):
    operation = _CURRENT_OPERATION.get()
    if operation is None:
        return
    try:
        event = "agent.finished" if kind == "agents" else "tool.finished"
        safe = _safe_event_fields(event, fields)
        name = "stage" if kind == "agents" else "tool"
        if name not in safe or safe.get("status") not in {"success", "failed"}:
            raise ValueError("Invalid execution metadata")
        operation.record_execution(kind, {
            name: safe[name],
            "status": safe["status"],
            "duration_ms": safe.get("duration_ms"),
        })
    except Exception:
        _mark_execution_incomplete(operation, kind)


def _safe_emit_event(event, *, component, level=logging.INFO, **fields):
    try:
        emit_event(event, component=component, level=level, **fields)
    except Exception:
        if event == "tool.finished":
            _mark_execution_incomplete(_CURRENT_OPERATION.get(), "tools")
        return False
    return True


def _elapsed_ms(started):
    try:
        elapsed = (time.perf_counter() - started) * 1000
        if math.isfinite(elapsed) and elapsed >= 0:
            return round(elapsed, 2)
    except Exception:
        pass
    return None


class _UnavailableOperation:
    """Keep a disabled scope active without allocating a metrics collector."""

    def __init__(self, operation_id):
        self.operation_id = operation_id

    def summary(self, status):
        return _unavailable_summary(self, status)


def _create_operation(operation_id=None):
    try:
        if operation_id is None:
            operation_id = str(uuid4())
        return OperationMetrics(operation_id)
    except Exception:
        return _UnavailableOperation(operation_id)


def _unavailable_summary(operation, status):
    return {
        "investigation_id": operation.operation_id,
        "status": status,
        "duration_ms": None,
        "calls_attempted": None,
        "calls_successful": None,
        "calls_failed": None,
        "request_metrics_complete": False,
        "prompt_tokens": None,
        "prompt_tokens_complete": False,
        "completion_tokens": None,
        "completion_tokens_complete": False,
        "total_tokens": None,
        "token_totals_complete": False,
        "estimated_cost": None,
        "cost_status": "unavailable",
        "stages": {},
        "agent_stages": {},
        "tools": {},
        "requests": [],
        "llm_duration_ms": None,
        "tool_duration_ms": None,
        "unattributed_duration_ms": None,
        "agent_metrics_complete": False,
        "tool_metrics_complete": False,
    }


def _safe_summary(operation, status):
    try:
        summary = operation.summary(status)
        if not isinstance(summary, dict):
            raise TypeError("Operation metrics summary is not a mapping")
        if summary.get("request_metrics_complete") is not True:
            summary["calls_attempted"] = None
            summary["calls_successful"] = None
            summary["calls_failed"] = None
            summary["stages"] = {}
        return summary
    except Exception:
        _mark_operation_incomplete(operation)
        return _unavailable_summary(operation, status)


def _tracked_request(stage, request_type, call, *args, **kwargs):
    try:
        request_id = str(uuid4())
    except Exception:
        request_id = None
        mark_request_metrics_incomplete()
    deployment = kwargs.get("model")
    try:
        started = time.perf_counter()
    except Exception:
        started = None
        mark_request_metrics_incomplete()
    try:
        response = call(*args, **kwargs)
    except Exception as error:
        request = {
            "request_id": request_id,
            "stage": stage,
            "request_type": request_type,
            "deployment": deployment,
            "duration_ms": _elapsed_ms(started) if started is not None else None,
            "status": "failed",
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "usage_available": False,
            "finish_reason": None,
        }
        _record_request(request)
        _safe_emit_event(
            "llm.request.finished",
            component="evalagent.llm",
            level=logging.ERROR,
            **request,
            **_error_fields(error),
        )
        raise

    try:
        request_metrics = _request_metrics(response, request_type)
    except Exception:
        mark_request_metrics_incomplete()
        request_metrics = {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "usage_available": False,
            "finish_reason": None,
        }
    request = {
        "request_id": request_id,
        "stage": stage,
        "request_type": request_type,
        "deployment": deployment,
        "duration_ms": _elapsed_ms(started) if started is not None else None,
        "status": "success",
        **request_metrics,
    }
    _record_request(request)
    _safe_emit_event(
        "llm.request.finished",
        component="evalagent.llm",
        **request,
    )
    return response


def tracked_chat_completion(stage, client, **kwargs):
    return _tracked_request(
        stage,
        "chat",
        client.chat.completions.create,
        **kwargs,
    )


def tracked_embeddings_create(stage, client, **kwargs):
    return _tracked_request(
        stage,
        "embeddings",
        client.embeddings.create,
        **kwargs,
    )


def record_remote_request(payload, operation_id):
    """Add one validated MCP child request record to the parent operation."""
    try:
        operation = _CURRENT_OPERATION.get()
        if (
            operation is None
            or operation.operation_id != operation_id
            or not isinstance(payload, dict)
            or payload.get("event") != "llm.request.finished"
            or payload.get("component") != "evalagent.llm"
            or payload.get("investigation_id") != operation_id
        ):
            return False

        request = {
            "request_id": payload.get("request_id"),
            "stage": payload.get("stage"),
            "request_type": payload.get("request_type"),
            "deployment": payload.get("deployment"),
            "duration_ms": payload.get("duration_ms"),
            "status": payload.get("status"),
            "prompt_tokens": payload.get("prompt_tokens"),
            "completion_tokens": payload.get("completion_tokens"),
            "total_tokens": payload.get("total_tokens"),
            "usage_available": payload.get("usage_available") is True,
            "finish_reason": payload.get("finish_reason"),
        }
        if (
            not isinstance(request["request_id"], str)
            or not _REQUEST_ID_PATTERN.fullmatch(request["request_id"])
            or not isinstance(request["stage"], str)
            or not _STAGE_PATTERN.fullmatch(request["stage"])
            or request["request_type"] not in {"chat", "embeddings"}
            or request["status"] not in {"success", "failed"}
            or not isinstance(request["duration_ms"], (int, float))
            or isinstance(request["duration_ms"], bool)
            or not math.isfinite(request["duration_ms"])
            or request["duration_ms"] < 0
        ):
            return False
        for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = request[name]
            if isinstance(value, bool) or (
                value is not None and (not isinstance(value, int) or value < 0)
            ):
                request[name] = None
        return _record_request(request)
    except Exception:
        _mark_operation_incomplete(_CURRENT_OPERATION.get())
        return False


def agent_span(stage):
    """Log the duration and outcome of one agent function."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                started = time.perf_counter()
            except Exception:
                started = None
            _safe_emit_event(
                "agent.started",
                component="evalagent.agent",
                stage=stage,
            )
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                duration_ms = _elapsed_ms(started) if started is not None else None
                _record_execution("agents", {
                    "stage": stage, "status": "failed", "duration_ms": duration_ms,
                })
                _safe_emit_event(
                    "agent.finished",
                    component="evalagent.agent",
                    level=logging.ERROR,
                    stage=stage,
                    status="failed",
                    duration_ms=duration_ms,
                    **_error_fields(error),
                )
                raise
            duration_ms = _elapsed_ms(started) if started is not None else None
            _record_execution("agents", {
                "stage": stage, "status": "success", "duration_ms": duration_ms,
            })
            _safe_emit_event(
                "agent.finished",
                component="evalagent.agent",
                stage=stage,
                status="success",
                duration_ms=duration_ms,
            )
            return result
        return wrapped
    return decorate


def observed_investigation(function):
    """Own one authoritative telemetry scope for each backend investigation."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _CURRENT_OPERATION.get() is not None:
            return function(*args, **kwargs)

        try:
            _COMPLETED_METRICS.set(None)
        except Exception:
            pass
        operation = _create_operation()
        token = _CURRENT_OPERATION.set(operation)
        status = "success"
        try:
            _safe_emit_event(
                "investigation.started",
                component="evalagent.investigation",
            )
            return function(*args, **kwargs)
        except Exception as error:
            status = "failed"
            _safe_emit_event(
                "investigation.failed",
                component="evalagent.investigation",
                level=logging.ERROR,
                **_error_fields(error),
            )
            raise
        finally:
            summary = _safe_summary(operation, status)
            try:
                _safe_emit_event(
                    "investigation.finished",
                    component="evalagent.investigation",
                    status=status,
                    duration_ms=summary.get("duration_ms"),
                    calls_attempted=summary.get("calls_attempted"),
                    calls_successful=summary.get("calls_successful"),
                    calls_failed=summary.get("calls_failed"),
                    request_metrics_complete=summary.get(
                        "request_metrics_complete"
                    ),
                    prompt_tokens=summary.get("prompt_tokens"),
                    completion_tokens=summary.get("completion_tokens"),
                    total_tokens=summary.get("total_tokens"),
                    token_totals_complete=summary.get("token_totals_complete"),
                    estimated_cost=None,
                )
            except Exception:
                pass
            finally:
                try:
                    _COMPLETED_METRICS.set(summary)
                except Exception:
                    pass
                finally:
                    _CURRENT_OPERATION.reset(token)
    return wrapped


def mcp_tool_telemetry(function):
    """Checkpoint child SDK accounting on stderr without changing tool results."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        operation = _create_operation(current_investigation_id())
        token = _CURRENT_OPERATION.set(operation)
        status = "success"
        try:
            return function(*args, **kwargs)
        except Exception:
            status = "failed"
            raise
        finally:
            try:
                summary = _safe_summary(operation, status)
                _safe_emit_event(
                    "mcp.telemetry.finished",
                    component="evalagent.mcp",
                    calls_attempted=summary.get("calls_attempted"),
                    request_metrics_complete=summary.get("request_metrics_complete"),
                )
            finally:
                _CURRENT_OPERATION.reset(token)
    return wrapped


def consume_completed_metrics():
    """Return and clear metrics from the most recent investigation in this context."""
    metrics = _COMPLETED_METRICS.get()
    _COMPLETED_METRICS.set(None)
    return metrics
