import asyncio
import io
import json
import logging
import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.offline_bootstrap import configure_offline_tests

configure_offline_tests()

from backend import evalagent_mcp_client, investigation_runner, observability
from backend.tool_registry import ToolRegistry


_MCP_CHILD_SCRIPT = """
import logging
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock
from tests.offline_bootstrap import configure_offline_tests

correlation = os.environ.get("EVALAGENT_INVESTIGATION_ID")
configure_offline_tests()
if correlation:
    os.environ["EVALAGENT_INVESTIGATION_ID"] = correlation
os.environ["EVALAGENT_PROCESS_ROLE"] = "mcp_server"

from backend import evalagent_mcp_server as server, observability

mode = sys.argv[1]
logger = observability.configure_logging("mcp_server")
if mode in {"handler_failure", "handler_sdk_failure"}:
    class RaisingHandler(logging.Handler):
        def emit(self, record):
            raise OSError("SYNTHETIC_SECRET_LOG_FAILURE")
    logger.handlers = [RaisingHandler()]
elif mode in {"checkpoint_loss", "request_loss"}:
    original_emit = observability.emit_event
    def emit(event, **kwargs):
        dropped = "mcp.telemetry.finished" if mode == "checkpoint_loss" else "llm.request.finished"
        if event != dropped:
            original_emit(event, **kwargs)
    observability.emit_event = emit
elif mode == "collector_failure":
    observability.Lock = Mock(side_effect=RuntimeError("collector failed"))

sdk_error = ValueError("SYNTHETIC_SECRET_SDK_FAILURE")
create = Mock(
    side_effect=sdk_error if mode in {"sdk_failure", "handler_sdk_failure"} else None,
    return_value=SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=9, total_tokens=9),
    ),
)
client = SimpleNamespace(embeddings=SimpleNamespace(create=create))

def get_incident(incident_id):
    if mode != "zero_requests":
        observability.tracked_embeddings_create(
            "evidence_retrieval", client,
            model="offline-embedding", input="SYNTHETIC_SECRET_QUERY",
        )
        assert create.call_count == 1
    return [{"ok": True, "content": "SYNTHETIC_SECRET_TOOL_RESULT"}]

server.tool_implementations.get_incident = get_incident
server.mcp.run("stdio")
"""


def _response(prompt_tokens=5, completion_tokens=7, total_tokens=12, usage=True):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop")],
        usage=(
            SimpleNamespace(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
            if usage
            else None
        ),
    )


def _client(create):
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        ),
    )


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("evalagent")
        self.original_handlers = self.logger.handlers[:]
        self.original_level = self.logger.level
        self.original_propagate = self.logger.propagate
        self.log_stream = io.StringIO()
        handler = logging.StreamHandler(self.log_stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.handlers = [handler]
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

    def tearDown(self):
        for handler in self.logger.handlers:
            if handler not in self.original_handlers:
                handler.close()
        self.logger.handlers = self.original_handlers
        self.logger.setLevel(self.original_level)
        self.logger.propagate = self.original_propagate
        observability.consume_completed_metrics()

    def _logged_events(self):
        return [
            json.loads(line)
            for line in self.log_stream.getvalue().splitlines()
            if line.startswith("{")
        ]

    def test_successful_request_records_usage_and_operation_totals(self):
        response = _response()
        client = _client(Mock(return_value=response))

        @observability.observed_investigation
        def run():
            return observability.tracked_chat_completion(
                "planner",
                client,
                model="planner-deployment",
                messages=[{"role": "user", "content": "SECRET_PROMPT"}],
            )

        self.assertIs(run(), response)
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["calls_attempted"], 1)
        self.assertEqual(metrics["calls_successful"], 1)
        self.assertEqual(metrics["calls_failed"], 0)
        self.assertEqual(metrics["total_tokens"], 12)
        self.assertTrue(metrics["token_totals_complete"])
        self.assertEqual(metrics["stages"]["planner"]["prompt_tokens"], 5)
        request = next(
            event for event in self._logged_events()
            if event["event"] == "llm.request.finished"
        )
        self.assertEqual(request["deployment"], "planner-deployment")
        self.assertEqual(request["finish_reason"], "stop")
        self.assertEqual(request["status"], "success")
        self.assertIn("investigation_id", request)
        self.assertNotIn("SECRET_PROMPT", self.log_stream.getvalue())

    def test_embedding_request_uses_returned_prompt_and_total_usage(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=9, total_tokens=9),
        )
        client = SimpleNamespace(
            embeddings=SimpleNamespace(create=Mock(return_value=response)),
        )

        @observability.observed_investigation
        def run():
            return observability.tracked_embeddings_create(
                "evidence_retrieval",
                client,
                model="embedding-deployment",
                input="SECRET_QUERY",
            )

        self.assertIs(run(), response)
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["total_tokens"], 9)
        self.assertEqual(metrics["prompt_tokens"], 9)
        request = next(
            event for event in self._logged_events()
            if event["event"] == "llm.request.finished"
        )
        self.assertEqual(request["request_type"], "embeddings")
        self.assertIsNone(request["completion_tokens"])
        self.assertNotIn("SECRET_QUERY", self.log_stream.getvalue())

    def test_missing_usage_makes_token_total_unavailable(self):
        client = _client(Mock(return_value=_response(usage=False)))

        @observability.observed_investigation
        def run():
            observability.tracked_chat_completion("planner", client, model="mini")

        run()
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["calls_attempted"], 1)
        self.assertIsNone(metrics["total_tokens"])
        self.assertFalse(metrics["token_totals_complete"])
        self.assertFalse(metrics["stages"]["planner"]["token_totals_complete"])

    def test_failed_attempt_and_retry_are_counted_once_each_and_not_token_complete(self):
        secret = "SECRET_SENTINEL"
        client = _client(Mock(
            side_effect=[RuntimeError(f"request failed {secret}"), _response()],
        ))

        @observability.observed_investigation
        def run():
            try:
                observability.tracked_chat_completion(
                    "report_generation",
                    client,
                    model="mini",
                )
            except RuntimeError:
                pass
            observability.tracked_chat_completion(
                "report_generation",
                client,
                model="mini",
            )

        run()
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["calls_attempted"], 2)
        self.assertEqual(metrics["calls_successful"], 1)
        self.assertEqual(metrics["calls_failed"], 1)
        self.assertIsNone(metrics["total_tokens"])
        self.assertFalse(metrics["token_totals_complete"])
        self.assertEqual([request["status"] for request in metrics["requests"]],
                         ["failed", "success"])
        self.assertNotIn(secret, self.log_stream.getvalue())

    def test_failed_agent_preserves_exception_and_emits_sanitized_failure(self):
        secret = "SECRET_SENTINEL"

        @observability.agent_span("test_agent")
        def failing_agent():
            raise RuntimeError(f"failure contains {secret}")

        @observability.observed_investigation
        def run():
            return failing_agent()

        with self.assertRaisesRegex(RuntimeError, secret):
            run()
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["status"], "failed")
        self.assertEqual(metrics["calls_attempted"], 0)
        events = self._logged_events()
        self.assertTrue(any(event["event"] == "agent.finished" for event in events))
        self.assertTrue(any(event["event"] == "investigation.failed" for event in events))
        self.assertNotIn(secret, self.log_stream.getvalue())

    def test_concurrent_investigations_keep_correlation_and_usage_isolated(self):
        barrier = threading.Barrier(2)

        def create(**kwargs):
            barrier.wait(timeout=5)
            token_count = kwargs["token_count"]
            return _response(
                prompt_tokens=token_count,
                completion_tokens=0,
                total_tokens=token_count,
            )

        client = _client(create)

        @observability.observed_investigation
        @observability.agent_span("parallel_stage")
        def run(token_count):
            observability.tracked_chat_completion(
                "parallel_stage",
                client,
                model=f"deployment-{token_count}",
                token_count=token_count,
            )
            observability.emit_event(
                "tool.finished", component="evalagent.tool", tool="get_incident",
                status="success", duration_ms=token_count,
            )

        def worker(token_count):
            run(token_count)
            return observability.consume_completed_metrics()

        with ThreadPoolExecutor(max_workers=2) as executor:
            metrics = list(executor.map(worker, (11, 23)))

        self.assertEqual(
            {item["total_tokens"] for item in metrics},
            {11, 23},
        )
        self.assertEqual(
            len({item["investigation_id"] for item in metrics}),
            2,
        )
        self.assertEqual({item["tool_duration_ms"] for item in metrics}, {11, 23})
        self.assertTrue(all(item["agent_stages"]["parallel_stage"]["calls_attempted"] == 1
                            for item in metrics))

    def test_mcp_stderr_metrics_are_relayed_without_changing_tool_result(self):
        child_request = {
            "component": "evalagent.llm",
            "event": "llm.request.finished",
            "investigation_id": None,
            "request_id": "00000000-0000-4000-8000-000000000001",
            "stage": "evidence_retrieval",
            "request_type": "embeddings",
            "deployment": "embedding-deployment",
            "duration_ms": 31.5,
            "status": "success",
            "prompt_tokens": 9,
            "completion_tokens": None,
            "total_tokens": 9,
            "usage_available": True,
            "finish_reason": None,
        }

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def initialize(self):
                return None

            async def call_tool(self, name, arguments):
                return SimpleNamespace(
                    is_error=False,
                    structured_content={"result": {"tool": name, "ok": True}},
                    content=[],
                )

        @observability.observed_investigation
        def run():
            child_request["investigation_id"] = (
                observability.current_investigation_id()
            )

            @asynccontextmanager
            async def fake_stdio(server, errlog):
                self.assertEqual(
                    server.env["EVALAGENT_INVESTIGATION_ID"],
                    child_request["investigation_id"],
                )
                errlog.write((json.dumps(child_request) + "\n").encode("utf-8"))
                errlog.write((json.dumps({
                    "event": "mcp.telemetry.finished",
                    "component": "evalagent.mcp",
                    "investigation_id": child_request["investigation_id"],
                    "calls_attempted": 1,
                    "request_metrics_complete": True,
                }) + "\n").encode("utf-8"))
                errlog.write(b"sensitive raw child diagnostic\n")
                yield object(), object()

            with (
                patch.object(evalagent_mcp_client, "stdio_client", fake_stdio),
                patch.object(
                    evalagent_mcp_client,
                    "ClientSession",
                    return_value=FakeSession(),
                ),
            ):
                return asyncio.run(
                    evalagent_mcp_client._call_tool_async(
                        "get_incident",
                        {"incident_id": "incident-1042.md"},
                    )
                )

        result = run()
        metrics = observability.consume_completed_metrics()
        self.assertEqual(result, {"tool": "get_incident", "ok": True})
        self.assertEqual(metrics["calls_attempted"], 1)
        self.assertEqual(metrics["total_tokens"], 9)
        self.assertTrue(metrics["request_metrics_complete"])
        self.assertEqual(metrics["llm_duration_ms"], 31.5)
        self.assertEqual(metrics["requests"][0]["stage"], "evidence_retrieval")
        self.assertEqual(metrics["requests"][0]["request_type"], "embeddings")
        self.assertNotIn("request_id", metrics["requests"][0])
        self.assertNotIn("sensitive raw child diagnostic", self.log_stream.getvalue())

    def test_agent_runtime_and_request_latency_are_distinct_with_retries(self):
        client = _client(Mock(side_effect=[_response(), _response(2, 1, 3)]))
        times = iter([0, 1, 2, 4, 5, 8, 10, 12])

        @observability.agent_span("planner")
        def planner():
            observability.tracked_chat_completion("planner", client, model="mini")
            observability.tracked_chat_completion("planner", client, model="mini")

        @observability.observed_investigation
        def run():
            planner()

        with patch.object(observability.time, "perf_counter", side_effect=lambda: next(times)):
            run()
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["duration_ms"], 12000)
        self.assertEqual(metrics["agent_stages"]["planner"]["duration_ms"], 9000)
        self.assertEqual(metrics["stages"]["planner"]["duration_ms"], 5000)
        self.assertEqual(metrics["llm_duration_ms"], 5000)
        self.assertEqual(metrics["calls_attempted"], 2)
        self.assertEqual(metrics["prompt_tokens"], 7)
        self.assertEqual(metrics["completion_tokens"], 8)
        self.assertEqual(metrics["total_tokens"], 15)
        self.assertEqual(len(metrics["requests"]), 2)
        self.assertEqual(metrics["agent_stages"]["planner"]["status"], "success")
        self.assertNotIn("critic", metrics["agent_stages"])
        self.assertIsNone(metrics["unattributed_duration_ms"])

    def test_failed_agent_retains_runtime_and_failed_request_details(self):
        original = RuntimeError("SECRET_FAILURE_BODY")
        client = _client(Mock(side_effect=original))

        @observability.agent_span("critic")
        def critic():
            observability.tracked_chat_completion("critic", client, model="mini")

        @observability.observed_investigation
        def run():
            critic()

        with self.assertRaises(RuntimeError) as raised:
            run()
        self.assertIs(raised.exception, original)
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["agent_stages"]["critic"]["status"], "failed")
        self.assertEqual(metrics["agent_stages"]["critic"]["calls_failed"], 1)
        self.assertEqual(metrics["requests"][0]["status"], "failed")
        self.assertIsNone(metrics["requests"][0]["total_tokens"])
        self.assertIsNone(metrics["total_tokens"])
        self.assertNotIn("SECRET_FAILURE_BODY", json.dumps(metrics))

    def test_repeated_agent_executions_aggregate_runtime_and_mixed_outcomes(self):
        times = iter([0, 1, 2, 3, 6, 7])

        @observability.agent_span("runbook_analysis")
        def analyze(fail):
            if fail:
                raise ValueError("synthetic failure")

        @observability.observed_investigation
        def run():
            try:
                analyze(True)
            except ValueError:
                pass
            analyze(False)

        with patch.object(observability.time, "perf_counter", side_effect=lambda: next(times)):
            run()
        metrics = observability.consume_completed_metrics()
        stage = metrics["agent_stages"]["runbook_analysis"]
        self.assertEqual(stage["duration_ms"], 4000)
        self.assertEqual(stage["calls_attempted"], 2)
        self.assertEqual(stage["calls_successful"], 1)
        self.assertEqual(stage["calls_failed"], 1)
        self.assertEqual(stage["status"], "mixed")
        self.assertEqual(metrics["calls_attempted"], 0)
        self.assertEqual(metrics["llm_duration_ms"], 0)

    def test_remote_requests_cannot_enter_another_investigation_snapshot(self):
        @observability.observed_investigation
        def run():
            operation_id = observability.current_investigation_id()
            payload = {
                "component": "evalagent.llm", "event": "llm.request.finished",
                "investigation_id": "00000000-0000-4000-8000-000000000099",
                "request_id": "00000000-0000-4000-8000-000000000001",
                "stage": "evidence_retrieval", "request_type": "embeddings",
                "status": "success", "duration_ms": 100, "total_tokens": 999,
            }
            self.assertFalse(observability.record_remote_request(payload, operation_id))
        run()
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["requests"], [])
        self.assertEqual(metrics["calls_attempted"], 0)
        self.assertEqual(metrics["llm_duration_ms"], 0)

    def test_tool_events_aggregate_counts_durations_and_failures(self):
        @observability.observed_investigation
        def run():
            for duration, status in ((10, "success"), (30, "failed")):
                observability.emit_event(
                    "tool.finished", component="evalagent.tool",
                    tool="get_incident", status=status, duration_ms=duration,
                    arguments={"api_key": "SECRET_TOOL_ARGS"},
                    result="SECRET_TOOL_RESULT",
                )

        run()
        metrics = observability.consume_completed_metrics()
        tool = metrics["tools"]["get_incident"]
        self.assertEqual(tool["calls_attempted"], 2)
        self.assertEqual(tool["calls_successful"], 1)
        self.assertEqual(tool["calls_failed"], 1)
        self.assertEqual(tool["duration_ms"], 40)
        self.assertEqual(tool["average_duration_ms"], 20)
        self.assertEqual(metrics["tool_duration_ms"], 40)
        self.assertNotIn("SECRET_TOOL", json.dumps(metrics))

    def test_direct_and_mcp_tools_collect_runtime_without_changing_results(self):
        for provider in ("direct", "mcp"):
            with self.subTest(provider=provider):
                expected = [{"file": "synthetic.md", "content": "SECRET_EVIDENCE"}]
                if provider == "direct":
                    target = patch(
                        "backend.tool_registry.tool_implementations.get_incident",
                        return_value=expected,
                    )
                else:
                    target = patch.object(evalagent_mcp_client, "call_tool", return_value=expected)

                @observability.observed_investigation
                def run():
                    return ToolRegistry().get_incident("synthetic")

                with patch.dict(os.environ, {"EVALAGENT_TOOL_PROVIDER": provider}), target:
                    self.assertIs(run(), expected)
                metrics = observability.consume_completed_metrics()
                self.assertEqual(metrics["tools"]["get_incident"]["calls_attempted"], 1)
                self.assertTrue(metrics["tool_metrics_complete"])
                self.assertGreaterEqual(metrics["tool_duration_ms"], 0)
                self.assertNotIn("SECRET_EVIDENCE", json.dumps(metrics))

    def test_execution_collection_failure_isolated_from_agents_and_tools(self):
        @observability.agent_span("planner")
        def planner():
            return "result"

        @observability.observed_investigation
        def run():
            observability.emit_event(
                "tool.finished", component="evalagent.tool", tool="get_incident",
                status="success", duration_ms=10,
            )
            return planner()

        with patch.object(
            observability.OperationMetrics, "record_execution",
            side_effect=RuntimeError("collector failed"),
        ):
            self.assertEqual(run(), "result")
        metrics = observability.consume_completed_metrics()
        self.assertFalse(metrics["agent_metrics_complete"])
        self.assertFalse(metrics["tool_metrics_complete"])
        self.assertIsNone(metrics["tool_duration_ms"])
        self.assertIsNone(observability.current_investigation_id())

    def test_execution_collection_survives_logging_failure_and_stays_isolated(self):
        class RaisingHandler(logging.Handler):
            def emit(self, record):
                raise OSError("log failed")

        self.logger.handlers = [RaisingHandler()]

        @observability.agent_span("planner")
        def planner():
            observability.emit_event(
                "tool.finished", component="evalagent.tool", tool="get_incident",
                status="success", duration_ms=10,
            )

        @observability.observed_investigation
        def run():
            planner()

        run()
        first = observability.consume_completed_metrics()
        run()
        second = observability.consume_completed_metrics()
        self.assertNotEqual(first["investigation_id"], second["investigation_id"])
        for metrics in (first, second):
            self.assertEqual(metrics["tools"]["get_incident"]["calls_attempted"], 1)
            self.assertEqual(metrics["agent_stages"]["planner"]["calls_attempted"], 1)
        self.assertIsNone(observability.current_investigation_id())

    def test_missing_tool_duration_is_unavailable_not_zero(self):
        @observability.observed_investigation
        def run():
            observability.emit_event(
                "tool.finished", component="evalagent.tool", tool="get_incident",
                status="success", duration_ms=None,
            )
        run()
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["tools"]["get_incident"]["calls_attempted"], 1)
        self.assertIsNone(metrics["tools"]["get_incident"]["duration_ms"])
        self.assertIsNone(metrics["tools"]["get_incident"]["average_duration_ms"])
        self.assertIsNone(metrics["tool_duration_ms"])

    def test_request_snapshot_exposes_only_safe_metadata(self):
        response = _response()
        response.content = "SECRET_RESPONSE"
        client = _client(Mock(return_value=response))

        @observability.observed_investigation
        def run():
            return observability.tracked_chat_completion(
                "planner", client, model="mini", messages=["SECRET_PROMPT"],
            )

        self.assertIs(run(), response)
        metrics = observability.consume_completed_metrics()
        request = metrics["requests"][0]
        self.assertEqual(request["total_tokens"], 12)
        self.assertNotIn("request_id", request)
        self.assertNotIn("SECRET", json.dumps(metrics))

    def test_event_allowlist_omits_unapproved_sensitive_fields(self):
        secret = "SYNTHETIC_SECRET_SENTINEL"
        observability.emit_event(
            "llm.request.finished",
            component="evalagent.llm",
            request_id="00000000-0000-4000-8000-000000000001",
            stage="planner",
            request_type="chat",
            deployment="planner-deployment",
            duration_ms=12.5,
            status="success",
            prompt_tokens=4,
            completion_tokens=3,
            total_tokens=7,
            usage_available=True,
            finish_reason="stop",
            api_key=secret,
            authorization=f"Bearer {secret}",
            access_token=secret,
            connection_string=secret,
            prompt=secret,
            completion=secret,
            documents=secret,
            body={"content": secret},
        )

        output = self.log_stream.getvalue()
        self.assertNotIn(secret, output)
        event = self._logged_events()[0]
        self.assertEqual(event["stage"], "planner")
        self.assertEqual(event["prompt_tokens"], 4)
        self.assertEqual(event["total_tokens"], 7)
        for field in (
            "api_key",
            "authorization",
            "access_token",
            "connection_string",
            "prompt",
            "completion",
            "documents",
            "body",
        ):
            self.assertNotIn(field, event)

    def test_event_emission_failure_preserves_success_and_resets_context(self):
        response = _response()
        client = _client(Mock(return_value=response))

        @observability.observed_investigation
        def run():
            return observability.tracked_chat_completion(
                "planner",
                client,
                model="planner-deployment",
            )

        with patch.object(
            observability,
            "emit_event",
            side_effect=RuntimeError("telemetry handler failed"),
        ):
            self.assertIs(run(), response)
            first_metrics = observability.consume_completed_metrics()

        self.assertEqual(first_metrics["calls_attempted"], 1)
        self.assertTrue(first_metrics["request_metrics_complete"])
        self.assertIsNone(observability.current_investigation_id())

        self.assertIs(run(), response)
        second_metrics = observability.consume_completed_metrics()
        self.assertNotEqual(
            first_metrics["investigation_id"],
            second_metrics["investigation_id"],
        )
        self.assertEqual(second_metrics["calls_attempted"], 1)
        self.assertIsNone(observability.current_investigation_id())

    def test_run_investigation_succeeds_when_event_emission_fails(self):
        class RaisingHandler(logging.Handler):
            def emit(self, record):
                raise OSError("synthetic event sink failure")

        plan = {
            "incident_id": None,
            "deployment_id": None,
            "investigation_type": "deployment",
            "search_deployment": False,
            "search_runbooks": False,
        }
        self.logger.handlers = [RaisingHandler()]
        with (
            patch.object(
                observability,
                "emit_event",
                side_effect=RuntimeError("telemetry emission failed"),
            ),
            patch.object(
                investigation_runner,
                "create_investigation_plan",
                return_value=plan,
            ),
            patch.object(
                investigation_runner,
                "_generate_report",
                return_value="{}",
            ),
            patch.object(
                investigation_runner,
                "review_report",
                return_value=None,
            ),
        ):
            result = investigation_runner.run_investigation(
                "Investigate the synthetic deployment"
            )

        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], str)
        self.assertEqual(result[1], [])
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["status"], "success")
        self.assertEqual(metrics["calls_attempted"], 0)
        self.assertIsNone(observability.current_investigation_id())

    def test_event_emission_failure_does_not_mask_sdk_exception(self):
        original_error = RuntimeError("original SDK failure")
        client = _client(Mock(side_effect=original_error))

        @observability.observed_investigation
        def run():
            observability.tracked_chat_completion(
                "planner",
                client,
                model="planner-deployment",
            )

        with (
            patch.object(
                observability,
                "emit_event",
                side_effect=RuntimeError("telemetry failure"),
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            run()

        self.assertIs(raised.exception, original_error)
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["status"], "failed")
        self.assertEqual(metrics["calls_failed"], 1)
        self.assertIsNone(observability.current_investigation_id())

    def test_metric_recording_failure_preserves_sdk_response_and_invalidates_totals(self):
        response = _response()
        client = _client(Mock(return_value=response))

        @observability.observed_investigation
        def run():
            return observability.tracked_chat_completion(
                "planner",
                client,
                model="planner-deployment",
            )

        with patch.object(
            observability.OperationMetrics,
            "record_request",
            side_effect=RuntimeError("metrics storage failed"),
        ):
            self.assertIs(run(), response)
            metrics = observability.consume_completed_metrics()

        self.assertFalse(metrics["request_metrics_complete"])
        self.assertIsNone(metrics["calls_attempted"])
        self.assertIsNone(metrics["total_tokens"])
        self.assertFalse(metrics["token_totals_complete"])
        self.assertEqual(metrics["stages"], {})
        self.assertIsNone(observability.current_investigation_id())

    def test_summary_failure_returns_unavailable_metrics_and_next_scope_is_clean(self):
        response = _response()
        client = _client(Mock(return_value=response))

        @observability.observed_investigation
        def run():
            return observability.tracked_chat_completion(
                "planner",
                client,
                model="planner-deployment",
            )

        with patch.object(
            observability.OperationMetrics,
            "summary",
            side_effect=RuntimeError("summary aggregation failed"),
        ):
            self.assertIs(run(), response)
            unavailable = observability.consume_completed_metrics()

        self.assertIsNone(unavailable["calls_attempted"])
        self.assertIsNone(unavailable["duration_ms"])
        self.assertIsNone(unavailable["total_tokens"])
        self.assertFalse(unavailable["request_metrics_complete"])
        self.assertIsNone(observability.current_investigation_id())

        self.assertIs(run(), response)
        recovered = observability.consume_completed_metrics()
        self.assertEqual(recovered["calls_attempted"], 1)
        self.assertEqual(recovered["total_tokens"], 12)
        self.assertIsNone(observability.current_investigation_id())

    def test_logging_handler_failure_does_not_interrupt_investigation(self):
        class RaisingHandler(logging.Handler):
            def emit(self, record):
                raise OSError("synthetic log sink failure")

        self.logger.handlers = [RaisingHandler()]
        response = _response()
        client = _client(Mock(return_value=response))

        @observability.observed_investigation
        def run():
            return observability.tracked_chat_completion(
                "planner",
                client,
                model="planner-deployment",
            )

        self.assertIs(run(), response)
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["calls_attempted"], 1)
        self.assertEqual(metrics["total_tokens"], 12)
        self.assertIsNone(observability.current_investigation_id())

    def test_mcp_stderr_relay_failure_does_not_fail_tool_and_marks_metrics_unknown(self):
        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def initialize(self):
                return None

            async def call_tool(self, name, arguments):
                return SimpleNamespace(
                    is_error=False,
                    structured_content={"result": {"ok": True}},
                    content=[],
                )

        @observability.observed_investigation
        def run():
            @asynccontextmanager
            async def fake_stdio(server, errlog):
                yield object(), object()

            with (
                patch.object(evalagent_mcp_client, "stdio_client", fake_stdio),
                patch.object(
                    evalagent_mcp_client,
                    "ClientSession",
                    return_value=FakeSession(),
                ),
                patch.object(
                    evalagent_mcp_client,
                    "_relay_child_stderr",
                    side_effect=OSError("relay unavailable"),
                ),
            ):
                return asyncio.run(
                    evalagent_mcp_client._call_tool_async(
                        "get_incident",
                        {"incident_id": "incident-1042.md"},
                    )
                )

        self.assertEqual(run(), {"ok": True})
        metrics = observability.consume_completed_metrics()
        self.assertFalse(metrics["request_metrics_complete"])
        self.assertIsNone(metrics["total_tokens"])

    def test_mcp_capture_failure_uses_discard_sink_and_preserves_tool_result(self):
        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def initialize(self):
                return None

            async def call_tool(self, name, arguments):
                return SimpleNamespace(
                    is_error=False,
                    structured_content={"result": {"ok": True}},
                    content=[],
                )

        stderr_sinks = []

        @observability.observed_investigation
        def run():
            @asynccontextmanager
            async def fake_stdio(server, errlog):
                stderr_sinks.append(errlog)
                self.assertIsNot(errlog, sys.stderr)
                self.assertEqual(errlog.name, os.devnull)
                yield object(), object()

            with (
                patch.object(
                    evalagent_mcp_client.tempfile,
                    "TemporaryFile",
                    side_effect=OSError("capture unavailable"),
                ),
                patch.object(evalagent_mcp_client, "stdio_client", fake_stdio),
                patch.object(
                    evalagent_mcp_client,
                    "ClientSession",
                    return_value=FakeSession(),
                ),
            ):
                return asyncio.run(
                    evalagent_mcp_client._call_tool_async(
                        "get_incident",
                        {"incident_id": "incident-1042.md"},
                    )
                )

        self.assertEqual(run(), {"ok": True})
        metrics = observability.consume_completed_metrics()
        self.assertFalse(metrics["request_metrics_complete"])
        self.assertTrue(stderr_sinks[0].closed)

    def test_collector_initialization_failure_preserves_nested_result_and_isolation(self):
        response = _response()
        sdk = Mock(return_value=response)
        client = _client(sdk)

        @observability.observed_investigation
        def nested():
            return observability.tracked_chat_completion("planner", client, model="mini")

        @observability.observed_investigation
        def run():
            return nested()

        for target in ("Lock", "uuid4"):
            with self.subTest(target=target):
                with patch.object(observability, target, side_effect=RuntimeError("init failed")):
                    self.assertIs(run(), response)
                metrics = observability.consume_completed_metrics()
                self.assertIsNone(metrics["calls_attempted"])
                self.assertIsNone(metrics["total_tokens"])
                self.assertIsNone(metrics["tool_duration_ms"])
                self.assertFalse(metrics["request_metrics_complete"])
                self.assertFalse(metrics["token_totals_complete"])
                self.assertFalse(metrics["tool_metrics_complete"])
                self.assertIsNone(observability.current_investigation_id())
                self.assertIsNone(observability._CURRENT_OPERATION.get())

        self.assertEqual(sdk.call_count, 2)
        self.assertIs(run(), response)
        recovered = observability.consume_completed_metrics()
        self.assertEqual(recovered["calls_attempted"], 1)
        self.assertEqual(recovered["total_tokens"], 12)
        self.assertTrue(recovered["request_metrics_complete"])
        self.assertIsNone(observability._CURRENT_OPERATION.get())

    def test_collector_initialization_failure_preserves_original_sdk_exception(self):
        original = ValueError("SYNTHETIC_SECRET_ORIGINAL")
        client = _client(Mock(side_effect=original))

        @observability.observed_investigation
        def run():
            observability.tracked_chat_completion("planner", client, model="mini")

        with (
            patch.object(observability, "Lock", side_effect=RuntimeError("init failed")),
            patch.object(observability, "emit_event", side_effect=OSError("sink failed")),
            self.assertRaises(ValueError) as raised,
        ):
            run()
        self.assertIs(raised.exception, original)
        metrics = observability.consume_completed_metrics()
        self.assertEqual(metrics["status"], "failed")
        self.assertIsNone(metrics["total_tokens"])
        self.assertFalse(metrics["request_metrics_complete"])
        self.assertIsNone(observability._CURRENT_OPERATION.get())

    def _check_tool_clock_failure(self, fail_tool):
        original = ValueError("SYNTHETIC_SECRET_TOOL_ERROR")
        expected = [{"ok": True}]
        for provider in ("direct", "mcp"):
            for failure in ("start", "elapsed"):
                with self.subTest(provider=provider, failure=failure):
                    target = (
                        "backend.tool_registry.tool_implementations.get_incident"
                        if provider == "direct" else
                        "backend.evalagent_mcp_client.call_tool"
                    )
                    clock_failure = RuntimeError("clock failed")
                    times = (
                        [0, clock_failure, 2] if failure == "start"
                        else [0, 1, clock_failure, 2]
                    )

                    @observability.observed_investigation
                    def run():
                        return ToolRegistry().get_incident("synthetic")

                    with (
                        patch.dict(os.environ, {"EVALAGENT_TOOL_PROVIDER": provider}),
                        patch(target, side_effect=original if fail_tool else None,
                              return_value=expected),
                        patch.object(observability.time, "perf_counter", side_effect=times),
                    ):
                        if fail_tool:
                            with self.assertRaises(ValueError) as raised:
                                run()
                            self.assertIs(raised.exception, original)
                        else:
                            self.assertIs(run(), expected)
                    metrics = observability.consume_completed_metrics()
                    tool = metrics["tools"]["get_incident"]
                    self.assertEqual(tool["calls_attempted"], 1)
                    self.assertEqual(tool["calls_failed"], int(fail_tool))
                    self.assertEqual(tool["calls_successful"], int(not fail_tool))
                    self.assertIsNone(tool["duration_ms"])
                    self.assertIsNone(tool["average_duration_ms"])
                    self.assertIsNone(metrics["tool_duration_ms"])
                    self.assertIsNone(observability._CURRENT_OPERATION.get())

    def test_tool_timer_failures_preserve_success_in_both_providers(self):
        self._check_tool_clock_failure(False)

    def test_tool_timer_failures_preserve_original_exception_in_both_providers(self):
        self._check_tool_clock_failure(True)

    def test_timestamp_failure_preserves_tool_outcomes_and_invalidates_collection(self):
        expected = [{"ok": True}]
        original = ValueError("SYNTHETIC_SECRET_ORIGINAL")
        for fail_tool in (False, True):
            with self.subTest(fail_tool=fail_tool):
                @observability.observed_investigation
                def run():
                    return ToolRegistry().get_incident("synthetic")

                with (
                    patch.dict(os.environ, {"EVALAGENT_TOOL_PROVIDER": "direct"}),
                    patch("backend.tool_registry.tool_implementations.get_incident",
                          side_effect=original if fail_tool else None, return_value=expected),
                    patch.object(observability.time, "strftime",
                                 side_effect=RuntimeError("SYNTHETIC_SECRET_TIMESTAMP")),
                ):
                    if fail_tool:
                        with self.assertRaises(ValueError) as raised:
                            run()
                        self.assertIs(raised.exception, original)
                    else:
                        self.assertIs(run(), expected)
                metrics = observability.consume_completed_metrics()
                self.assertFalse(metrics["tool_metrics_complete"])
                self.assertIsNone(metrics["tool_duration_ms"])
                self.assertEqual(metrics["tools"], {})
                self.assertIsNone(observability._CURRENT_OPERATION.get())
                self.assertNotIn("SYNTHETIC_SECRET", self.log_stream.getvalue())

        with patch("backend.tool_registry.tool_implementations.get_incident",
                   return_value=expected):
            self.assertIs(run(), expected)
        recovered = observability.consume_completed_metrics()
        self.assertTrue(recovered["tool_metrics_complete"])
        self.assertEqual(recovered["tools"]["get_incident"]["calls_successful"], 1)
        self.assertIsNotNone(recovered["tool_duration_ms"])

    def _run_real_mcp(self, mode):
        parameters = evalagent_mcp_client._server_parameters()
        parameters.args = ["-B", "-c", _MCP_CHILD_SCRIPT, mode]

        @observability.observed_investigation
        def run():
            return ToolRegistry().get_incident("synthetic")

        with (
            patch.dict(os.environ, {"EVALAGENT_TOOL_PROVIDER": "mcp"}),
            patch.object(evalagent_mcp_client, "_server_parameters", side_effect=lambda: (
                parameters.model_copy(update={"env": {
                    **parameters.env,
                    "EVALAGENT_INVESTIGATION_ID": observability.current_investigation_id(),
                }})
            )),
        ):
            result = run()
        self.assertEqual(result, [{"ok": True, "content": "SYNTHETIC_SECRET_TOOL_RESULT"}])
        self.assertIsNone(observability._CURRENT_OPERATION.get())
        self.assertNotIn("SYNTHETIC_SECRET", self.log_stream.getvalue())
        return observability.consume_completed_metrics()

    def test_real_mcp_child_emission_failure_preserves_result_and_marks_usage_unknown(self):
        metrics = self._run_real_mcp("handler_failure")
        self.assertFalse(metrics["request_metrics_complete"])
        self.assertFalse(metrics["token_totals_complete"])
        self.assertIsNone(metrics["calls_attempted"])
        self.assertIsNone(metrics["total_tokens"])
        self.assertEqual(metrics["tools"]["get_incident"]["calls_successful"], 1)

    def test_real_mcp_checkpoint_loss_invalidates_even_received_usage(self):
        metrics = self._run_real_mcp("checkpoint_loss")
        self.assertEqual(len(metrics["requests"]), 1)
        self.assertFalse(metrics["request_metrics_complete"])
        self.assertIsNone(metrics["total_tokens"])

    def test_real_mcp_missing_request_record_does_not_match_checkpoint(self):
        metrics = self._run_real_mcp("request_loss")
        self.assertEqual(metrics["requests"], [])
        self.assertFalse(metrics["request_metrics_complete"])
        self.assertIsNone(metrics["calls_attempted"])
        self.assertIsNone(metrics["total_tokens"])

    def test_real_mcp_child_collector_failure_preserves_result_and_invalidates_totals(self):
        metrics = self._run_real_mcp("collector_failure")
        self.assertFalse(metrics["request_metrics_complete"])
        self.assertIsNone(metrics["total_tokens"])
        self.assertEqual(metrics["tools"]["get_incident"]["calls_successful"], 1)

    def test_real_mcp_valid_and_verified_zero_requests_remain_accurate_and_isolated(self):
        valid = self._run_real_mcp("valid")
        zero = self._run_real_mcp("zero_requests")
        self.assertNotEqual(valid["investigation_id"], zero["investigation_id"])
        self.assertTrue(valid["request_metrics_complete"])
        self.assertEqual(valid["calls_attempted"], 1)
        self.assertEqual(valid["calls_successful"], 1)
        self.assertEqual(valid["prompt_tokens"], 9)
        self.assertEqual(valid["total_tokens"], 9)
        self.assertTrue(zero["request_metrics_complete"])
        self.assertEqual(zero["calls_attempted"], 0)
        self.assertEqual(zero["total_tokens"], 0)
        self.assertEqual(zero["requests"], [])

    def test_real_mcp_original_failure_contract_is_preserved(self):
        for mode in ("sdk_failure", "handler_sdk_failure"):
            with self.subTest(mode=mode):
                parameters = evalagent_mcp_client._server_parameters()
                parameters.args = ["-B", "-c", _MCP_CHILD_SCRIPT, mode]

                @observability.observed_investigation
                def run():
                    return evalagent_mcp_client.call_tool("get_incident", incident_id="synthetic")

                with patch.object(evalagent_mcp_client, "_server_parameters", side_effect=lambda: (
                    parameters.model_copy(update={"env": {
                        **parameters.env,
                        "EVALAGENT_INVESTIGATION_ID": observability.current_investigation_id(),
                    }})
                )):
                    with self.assertRaisesRegex(RuntimeError, "MCP tool 'get_incident' is unavailable"):
                        run()
                metrics = observability.consume_completed_metrics()
                self.assertEqual(metrics["status"], "failed")
                if mode == "sdk_failure":
                    self.assertEqual(metrics["calls_failed"], 1)
                else:
                    self.assertIsNone(metrics["calls_failed"])
                    self.assertFalse(metrics["request_metrics_complete"])
                self.assertIsNone(metrics["total_tokens"])
                self.assertFalse(metrics["token_totals_complete"])
                self.assertIsNone(observability._CURRENT_OPERATION.get())
                self.assertNotIn("SYNTHETIC_SECRET", self.log_stream.getvalue())

    def test_mcp_checkpoint_validation_detects_lost_records_and_wrong_correlation(self):
        for count, correlation in ((1, None), (0, "00000000-0000-4000-8000-000000000099")):
            with self.subTest(count=count, correlation=correlation):
                @observability.observed_investigation
                def run():
                    operation_id = observability.current_investigation_id()
                    capture = io.StringIO(json.dumps({
                        "event": "mcp.telemetry.finished",
                        "component": "evalagent.mcp",
                        "investigation_id": correlation or operation_id,
                        "calls_attempted": count,
                        "request_metrics_complete": True,
                    }) + "\n")
                    evalagent_mcp_client._relay_child_stderr(capture, operation_id)
                run()
                metrics = observability.consume_completed_metrics()
                self.assertFalse(metrics["request_metrics_complete"])
                self.assertIsNone(metrics["calls_attempted"])
                self.assertIsNone(metrics["total_tokens"])

    def test_stale_mcp_relay_cannot_invalidate_an_independent_investigation(self):
        @observability.observed_investigation
        def run():
            evalagent_mcp_client._relay_child_stderr(
                io.StringIO(""), "00000000-0000-4000-8000-000000000099",
            )
        run()
        metrics = observability.consume_completed_metrics()
        self.assertTrue(metrics["request_metrics_complete"])
        self.assertEqual(metrics["calls_attempted"], 0)
        self.assertEqual(metrics["total_tokens"], 0)

    def test_mcp_checkpoint_allowlist_never_exposes_payload_fields(self):
        observability.emit_event(
            "mcp.telemetry.finished", component="evalagent.mcp",
            calls_attempted=1, request_metrics_complete=True,
            api_key="SYNTHETIC_SECRET", authorization="SYNTHETIC_SECRET",
            body={"prompt": "SYNTHETIC_SECRET"}, result="SYNTHETIC_SECRET",
        )
        event = self._logged_events()[0]
        self.assertEqual(event["calls_attempted"], 1)
        self.assertTrue(event["request_metrics_complete"])
        self.assertNotIn("SYNTHETIC_SECRET", self.log_stream.getvalue())
        for name in ("api_key", "authorization", "body", "result"):
            self.assertNotIn(name, event)


if __name__ == "__main__":
    unittest.main()
