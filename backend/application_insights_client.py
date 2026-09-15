"""Read-only Application Insights telemetry queries via Azure Monitor Logs."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

try:
    from azure.identity import DefaultAzureCredential
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus
except ImportError:  # Allows unit tests to mock the SDK when it is not installed.
    DefaultAzureCredential = None
    LogsQueryClient = None
    LogsQueryStatus = None


DEFAULT_MAX_RECORDS = 200
TABLES = {
    "AppRequests": "request",
    "AppDependencies": "dependency",
    "AppTraces": "trace",
    "AppExceptions": "exception",
}

load_dotenv()


class ApplicationInsightsQueryError(RuntimeError):
    """Raised when Application Insights telemetry cannot be queried safely."""


def _parse_datetime(value: str | datetime, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{name} must be an ISO-8601 datetime") from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _kusto_datetime(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _kusto_string(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "''")


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _column_name(column: Any) -> str:
    return str(getattr(column, "name", column))


def _table_rows(response: Any) -> list[dict[str, Any]]:
    if LogsQueryStatus is not None and response.status != LogsQueryStatus.SUCCESS:
        return []

    records = []
    for table in getattr(response, "tables", []):
        columns = [_column_name(column) for column in table.columns]
        for row in table.rows:
            records.append(dict(zip(columns, row)))
    return records


def _property_value(properties: Any, *names: str) -> Any:
    if not isinstance(properties, dict):
        return None
    for name in names:
        value = properties.get(name)
        if value not in (None, ""):
            return value
    return None


def _normalize_record(row: dict[str, Any], telemetry_type: str) -> dict[str, Any]:
    properties = _json_value(row.get("Properties") or {})
    timestamp = row.get("TimeGenerated") or row.get("timestamp")
    record = {
        "telemetry_type": telemetry_type,
        "timestamp": _json_value(timestamp),
        "operation_id": row.get("OperationId"),
        "name": row.get("Name"),
        "message": row.get("Message"),
        "success": row.get("Success"),
        "result_code": row.get("ResultCode"),
        "duration_ms": row.get("DurationMs"),
        "target": row.get("Target"),
        "exception_type": row.get("ExceptionType") or row.get("OuterType"),
        "properties": properties,
    }
    if not isinstance(properties, dict):
        record["properties"] = {"value": properties}
    return {key: _json_value(value) for key, value in record.items()}


def _query_text(service_name: str, incident_id: str | None, max_records: int) -> str:
    service = _kusto_string(service_name)
    incident_filter = ""
    if incident_id is not None:
        incident = _kusto_string(incident_id)
        incident_filter = (
            "\n| where tostring(Properties['incident_id']) == '"
            f"{incident}'"
        )

    branches = []
    for table_name, telemetry_type in TABLES.items():
        branches.append(
            f"{table_name}"
            f"\n| where (AppRoleName == '{service}'"
            f" or tostring(Properties['service.name']) == '{service}'"
            f" or tostring(Properties['service_name']) == '{service}'"
            f" or tostring(Properties['serviceName']) == '{service}')"
            f"{incident_filter}"
            f"\n| extend telemetry_type = '{telemetry_type}'"
        )

    return (
        "union kind=outer\n"
        + ",\n".join(f"({branch})" for branch in branches)
        + f"\n| order by TimeGenerated asc\n| take {max_records}"
    )


class ApplicationInsightsClient:
    """Small Azure Monitor Logs client for workspace-based App Insights data."""

    def __init__(self, logs_client=None):
        if logs_client is not None:
            self.logs_client = logs_client
            return
        if LogsQueryClient is None or DefaultAzureCredential is None:
            raise ApplicationInsightsQueryError(
                "Azure Monitor Query dependencies are not installed."
            )
        self.logs_client = LogsQueryClient(DefaultAzureCredential())

    def get_telemetry(
        self,
        service_name: str,
        start_time: str | datetime,
        end_time: str | datetime,
        incident_id: str | None = None,
        max_records: int = DEFAULT_MAX_RECORDS,
    ) -> dict[str, Any]:
        if not service_name or not str(service_name).strip():
            raise ValueError("service_name must not be empty")
        if max_records < 1:
            raise ValueError("max_records must be greater than zero")

        workspace_id = os.getenv("APPLICATIONINSIGHTS_WORKSPACE_ID")
        if not workspace_id:
            raise ValueError(
                "APPLICATIONINSIGHTS_WORKSPACE_ID must be configured"
            )

        start = _parse_datetime(start_time, "start_time")
        end = _parse_datetime(end_time, "end_time")
        if end <= start:
            raise ValueError("end_time must be after start_time")

        query = _query_text(service_name, incident_id, max_records)
        try:
            response = self.logs_client.query_workspace(
                workspace_id,
                query,
                timespan=(start, end),
            )
            raw_records = _table_rows(response)
        except Exception as error:
            raise ApplicationInsightsQueryError(
                "Application Insights query failed."
            ) from error

        records = []
        for row in raw_records:
            telemetry_type = row.get("telemetry_type")
            if telemetry_type not in TABLES.values():
                continue
            records.append(_normalize_record(row, telemetry_type))

        evidence = {
            "source": "application_insights",
            "category": "telemetry",
            "service": str(service_name),
            "incident_id": incident_id,
            "start_time": _kusto_datetime(start),
            "end_time": _kusto_datetime(end),
            "records": records[:max_records],
        }
        json.dumps(evidence)
        return evidence


application_insights_client = ApplicationInsightsClient if LogsQueryClient else None


def get_application_insights_telemetry(
    service_name: str,
    start_time: str | datetime,
    end_time: str | datetime,
    incident_id: str | None = None,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> dict[str, Any]:
    """Return normalized telemetry evidence without exposing SDK response objects."""
    client = ApplicationInsightsClient()
    return client.get_telemetry(
        service_name,
        start_time,
        end_time,
        incident_id,
        max_records,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Query Application Insights telemetry")
    parser.add_argument("service_name")
    parser.add_argument("start_time")
    parser.add_argument("end_time")
    parser.add_argument("--incident-id")
    args = parser.parse_args()
    result = get_application_insights_telemetry(
        args.service_name,
        args.start_time,
        args.end_time,
        args.incident_id,
    )
    print(json.dumps(result, indent=2))
