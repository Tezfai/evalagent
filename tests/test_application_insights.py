import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from azure.monitor.query import LogsQueryStatus

from backend.application_insights_client import (
    ApplicationInsightsClient,
    ApplicationInsightsQueryError,
)
from backend import tool_implementations


class FakeLogsClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query_workspace(self, workspace_id, query, *, timespan):
        self.calls.append((workspace_id, query, timespan))
        columns = list(dict.fromkeys(
            key
            for row in self.rows
            for key in row
        ))
        return SimpleNamespace(
            status=LogsQueryStatus.SUCCESS,
            tables=[
                SimpleNamespace(
                    columns=columns,
                    rows=[
                        [row.get(column) for column in columns]
                        for row in self.rows
                    ],
                )
            ] if self.rows else []
        )


class ApplicationInsightsTests(unittest.TestCase):
    def test_normalizes_all_telemetry_types(self):
        rows = [
            {
                "telemetry_type": "request",
                "TimeGenerated": "2026-09-14T10:00:00Z",
                "OperationId": "op-request",
                "Name": "POST /checkout",
                "Success": True,
                "ResultCode": "200",
                "DurationMs": 45,
                "Properties": {"checkout.phase": "normal"},
            },
            {
                "telemetry_type": "dependency",
                "TimeGenerated": "2026-09-14T10:00:01Z",
                "OperationId": "op-request",
                "Name": "GET checkout:cart",
                "Success": False,
                "DurationMs": 850,
                "Target": "checkout-redis",
                "Properties": {},
            },
            {
                "telemetry_type": "trace",
                "TimeGenerated": "2026-09-14T10:00:02Z",
                "OperationId": "op-request",
                "Message": "Synthetic checkout request failed",
                "Properties": {"incident_id": "1042"},
            },
            {
                "telemetry_type": "exception",
                "TimeGenerated": "2026-09-14T10:00:03Z",
                "OperationId": "op-request",
                "ExceptionType": "TimeoutError",
                "Properties": {},
            },
        ]
        fake_client = FakeLogsClient(rows)

        with patch.dict(
            "os.environ",
            {"APPLICATIONINSIGHTS_WORKSPACE_ID": "workspace-id"},
            clear=False,
        ):
            evidence = ApplicationInsightsClient(fake_client).get_telemetry(
                "checkout-service",
                "2026-09-14T09:59:00Z",
                "2026-09-14T10:01:00Z",
                incident_id="1042",
            )

        self.assertEqual(
            [record["telemetry_type"] for record in evidence["records"]],
            ["request", "dependency", "trace", "exception"],
        )
        self.assertEqual(evidence["records"][0]["result_code"], "200")
        self.assertEqual(evidence["records"][1]["target"], "checkout-redis")
        self.assertEqual(evidence["records"][2]["message"], "Synthetic checkout request failed")
        self.assertEqual(evidence["records"][3]["exception_type"], "TimeoutError")

    def test_empty_query_results_return_empty_evidence(self):
        fake_client = FakeLogsClient([])
        with patch.dict(
            "os.environ",
            {"APPLICATIONINSIGHTS_WORKSPACE_ID": "workspace-id"},
            clear=False,
        ):
            evidence = ApplicationInsightsClient(fake_client).get_telemetry(
                "checkout-service",
                "2026-09-14T09:59:00Z",
                "2026-09-14T10:01:00Z",
            )

        self.assertEqual(evidence["records"], [])

    def test_incident_filter_is_present_in_query(self):
        fake_client = FakeLogsClient([])
        with patch.dict(
            "os.environ",
            {"APPLICATIONINSIGHTS_WORKSPACE_ID": "workspace-id"},
            clear=False,
        ):
            ApplicationInsightsClient(fake_client).get_telemetry(
                "checkout-service",
                "2026-09-14T09:59:00Z",
                "2026-09-14T10:01:00Z",
                incident_id="1042",
            )

        query = fake_client.calls[0][1]
        self.assertIn("AppRequests", query)
        self.assertIn("AppDependencies", query)
        self.assertIn("AppTraces", query)
        self.assertIn("AppExceptions", query)
        self.assertIn("incident_id", query)
        self.assertIn("1042", query)

    def test_missing_configuration_is_rejected(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "APPLICATIONINSIGHTS_WORKSPACE_ID"):
                ApplicationInsightsClient(FakeLogsClient([])).get_telemetry(
                    "checkout-service",
                    "2026-09-14T09:59:00Z",
                    "2026-09-14T10:01:00Z",
                )

    def test_query_failure_is_sanitized(self):
        class FailingClient:
            def query_workspace(self, *args, **kwargs):
                raise RuntimeError("secret-token-and-raw-response")

        with (
            patch.dict(
                "os.environ",
                {"APPLICATIONINSIGHTS_WORKSPACE_ID": "workspace-id"},
                clear=False,
            ),
            self.assertRaises(ApplicationInsightsQueryError) as error,
        ):
            ApplicationInsightsClient(FailingClient()).get_telemetry(
                "checkout-service",
                "2026-09-14T09:59:00Z",
                "2026-09-14T10:01:00Z",
            )

        self.assertEqual(str(error.exception), "Application Insights query failed.")
        self.assertNotIn("secret-token", str(error.exception))

    def test_tool_implementation_preserves_evidence_contract(self):
        expected = {
            "source": "application_insights",
            "category": "telemetry",
            "service": "checkout-service",
            "incident_id": "1042",
            "records": [],
        }
        with patch.object(
            tool_implementations,
            "query_application_insights",
            return_value=expected,
        ) as query:
            result = tool_implementations.get_application_insights_telemetry(
                "checkout-service",
                "start",
                "end",
                "1042",
            )

        self.assertEqual(result, expected)
        query.assert_called_once_with(
            "checkout-service",
            "start",
            "end",
            "1042",
            200,
        )
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
