import json
import io
import asyncio
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from backend import investigation_runner
from backend import deployment_agent
from backend import evalagent_mcp_server
from backend import evalagent_mcp_client
from backend.tool_registry import ToolRegistry


class InvestigationRunnerTests(unittest.TestCase):
    @staticmethod
    def _response(content, finish_reason="stop"):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(content=content),
                )
            ]
        )

    def test_azure_devops_is_skipped_when_disabled(self):
        plan = {
            "incident_id": "1042",
            "deployment_id": "882",
            "runbook_reference": None,
            "search_deployment": False,
            "search_runbooks": False,
        }
        incident_evidence = [
            {
                "file": "data/incidents/incident-1042.md",
                "chunk_id": 0,
                "content": "Related deployment: deployment-882",
                "category": "incident",
                "primary": False,
            }
        ]
        deployment_evidence = [
            {
                "file": "data/deployments/deployment-882.md",
                "chunk_id": 0,
                "content": (
                    "Azure DevOps Work Item: 1234\n"
                    "Azure DevOps Pull Request: 5678\n"
                    "Azure DevOps Repository: checkout-service"
                ),
                "category": "deployment",
                "primary": False,
            }
        ]
        report_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({})
                    )
                )
            ]
        )

        with (
            patch.dict("os.environ", {"EVALAGENT_TOOL_PROVIDER": "mcp"}),
            patch.object(
                investigation_runner,
                "create_investigation_plan",
                return_value=plan,
            ),
            patch.object(
                investigation_runner.tool_registry,
                "get_incident",
                return_value=incident_evidence,
            ),
            patch.object(
                investigation_runner.tool_registry,
                "get_deployment",
                return_value=deployment_evidence,
            ),
            patch.object(
                evalagent_mcp_client,
                "call_tool",
            ) as call_tool,
            patch.object(
                investigation_runner,
                "analyze_deployment",
                return_value=None,
            ),
            patch.object(
                investigation_runner.client.chat.completions,
                "create",
                return_value=report_response,
            ),
            patch.object(
                investigation_runner,
                "review_report",
                return_value=None,
            ),
        ):
            report_text, evidence = investigation_runner.run_investigation(
                "Investigate incident 1042"
            )

        call_tool.assert_not_called()
        self.assertIn("No Azure DevOps evidence available.", report_text)
        self.assertTrue(evidence)

    def test_report_generation_succeeds_on_first_response(self):
        response = self._response('{"Incident": "supported"}')
        with patch.object(
            investigation_runner.client.chat.completions,
            "create",
            return_value=response,
        ) as create:
            report_text = investigation_runner._generate_report(
                [{"role": "user", "content": "secret evidence"}]
            )

        self.assertEqual(report_text, '{"Incident": "supported"}')
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["max_completion_tokens"], 5000)

    def test_report_generation_retries_empty_length_response_once(self):
        responses = [
            self._response(None, "length"),
            self._response('{"Incident": "supported"}'),
        ]
        output = io.StringIO()
        with (
            patch.object(
                investigation_runner.client.chat.completions,
                "create",
                side_effect=responses,
            ) as create,
            redirect_stdout(output),
        ):
            report_text = investigation_runner._generate_report(
                [{"role": "user", "content": "secret evidence"}]
            )

        self.assertEqual(report_text, '{"Incident": "supported"}')
        self.assertEqual(create.call_count, 2)
        self.assertEqual(
            create.call_args_list[0].kwargs["max_completion_tokens"],
            5000,
        )
        self.assertEqual(
            create.call_args_list[1].kwargs["max_completion_tokens"],
            7000,
        )
        self.assertIn("finish_reason=length, has_content=False", output.getvalue())
        self.assertNotIn("secret evidence", output.getvalue())

    def test_two_empty_report_responses_raise_without_third_request(self):
        responses = [
            self._response(None, "length"),
            self._response(None, "stop"),
        ]
        with patch.object(
            investigation_runner.client.chat.completions,
            "create",
            side_effect=responses,
        ) as create:
            with self.assertRaisesRegex(
                ValueError,
                r"finish_reason=stop",
            ):
                investigation_runner._generate_report(
                    [{"role": "user", "content": "secret evidence"}]
                )

        self.assertEqual(create.call_count, 2)

    def test_deployment_886_links_are_extracted_in_order(self):
        content = (
            "Related incidents: [incident-1046](../incidents/incident-1046.md), "
            "[incident-1050](../incidents/incident-1050.md)\n"
            "See [checkout-runbook](../runbooks/checkout-runbook.md)."
        )

        deployment_files, incident_files, runbook_files = (
            investigation_runner._extract_references(
                [{"file": "deployment-886.md", "content": content}]
            )
        )

        self.assertEqual(deployment_files, [])
        self.assertEqual(
            incident_files,
            ["incident-1046.md", "incident-1050.md"],
        )
        self.assertEqual(runbook_files, ["checkout-runbook.md"])

    def test_direct_deployment_retrieves_links_without_semantic_incident_search(self):
        plan = {
            "investigation_type": "deployment",
            "incident_id": None,
            "deployment_id": "886",
            "runbook_reference": None,
            "search_deployment": False,
            "search_runbooks": False,
        }
        deployment = {
            "file": r"data\deployments\deployment-886.md",
            "chunk_id": 0,
            "content": (
                "Related incidents: [incident-1046](../incidents/incident-1046.md), "
                "[incident-1050](../incidents/incident-1050.md). "
                "See [checkout-runbook](../runbooks/checkout-runbook.md)."
            ),
            "category": "deployment",
            "primary": False,
        }
        linked_incident = {
            "file": "data/incidents/incident-1046.md",
            "chunk_id": 0,
            "content": "Incident 1046 facts.",
            "category": "incident",
            "primary": False,
        }
        linked_runbook = {
            "file": "data/runbooks/checkout-runbook.md",
            "chunk_id": 0,
            "content": "Runbook facts.",
            "category": "runbook",
            "primary": False,
        }
        report_response = self._response(json.dumps({}))

        def get_incident(value):
            self.assertIn(value, {"incident-1046.md", "incident-1050.md"})
            return [linked_incident]

        with (
            patch.object(
                investigation_runner,
                "create_investigation_plan",
                return_value=plan,
            ),
            patch.object(
                investigation_runner.tool_registry,
                "get_incident",
                side_effect=get_incident,
            ) as get_incident_mock,
            patch.object(
                investigation_runner.tool_registry,
                "get_deployment",
                return_value=[deployment],
            ) as get_deployment_mock,
            patch.object(
                investigation_runner.tool_registry,
                "get_runbook",
                return_value=[linked_runbook],
            ) as get_runbook_mock,
            patch.object(
                investigation_runner,
                "analyze_deployment",
                return_value=None,
            ),
            patch.object(
                investigation_runner,
                "analyze_runbook",
                return_value=None,
            ),
            patch.object(
                investigation_runner.client.chat.completions,
                "create",
                return_value=report_response,
            ),
            patch.object(
                investigation_runner,
                "review_report",
                return_value=None,
            ),
        ):
            report_text, evidence = investigation_runner.run_investigation(
                "Investigate deployment 886"
            )

        get_deployment_mock.assert_called_once_with("deployment-886.md")
        self.assertEqual(
            [call.args[0] for call in get_incident_mock.call_args_list],
            ["incident-1046.md", "incident-1050.md"],
        )
        get_runbook_mock.assert_called_once_with("checkout-runbook.md")
        self.assertNotIn("Investigate deployment 886", [
            call.args[0] for call in get_incident_mock.call_args_list
        ])
        self.assertIn("Automated deployment analysis was unavailable", report_text)
        self.assertLessEqual(
            len({item["file"] for item in evidence}),
            4,
        )

    def test_deduplication_preserves_first_order_and_primary_status(self):
        evidence = [
            {"file": "deployment-886.md", "chunk_id": 0, "content": "A", "primary": False},
            {"file": "deployment-886.md", "chunk_id": 1, "content": "B", "primary": False},
            {"file": "deployment-886.md", "chunk_id": 0, "content": "A", "primary": True},
            {"file": "deployment-886.md", "chunk_id": 1, "content": "B", "primary": True},
        ]

        result = investigation_runner._deduplicate_evidence(evidence)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["chunk_id"], "0, 1")
        self.assertEqual(result[0]["content"], "A\n\nB")
        self.assertTrue(result[0]["primary"])

    def test_retrieved_evidence_category_cannot_override_registry_category(self):
        result = ToolRegistry._with_category(
            [{"file": "incident-1046.md", "category": "deployment"}],
            "incident",
        )

        self.assertEqual(result[0]["category"], "incident")
        self.assertFalse(result[0]["primary"])

    def test_recommendations_are_limited_to_five_items(self):
        recommendations = "\n".join(
            f"- Recommendation {index}" for index in range(1, 8)
        )

        result = investigation_runner._limit_recommendations(recommendations)

        self.assertEqual(result.count("Recommendation"), 5)

    def test_report_and_critic_receive_same_selected_azure_devops_evidence(self):
        plan = {
            "incident_id": "1042",
            "deployment_id": "882",
            "runbook_reference": None,
            "search_deployment": False,
            "search_runbooks": False,
        }
        incident = [{
            "file": "incident-1042.md",
            "chunk_id": 0,
            "content": "Incident facts.",
            "category": "incident",
            "primary": False,
        }]
        deployment = [{
            "file": "deployment-882.md",
            "chunk_id": 0,
            "content": (
                "Azure DevOps Work Item: 1234\n"
                "Azure DevOps Pull Request: 5678\n"
                "Azure DevOps Repository: checkout-platform"
            ),
            "category": "deployment",
            "primary": False,
        }]
        report_response = InvestigationRunnerTests._response(json.dumps({}))
        captured_report_prompt = {}
        captured_critic_evidence = {}

        def create_report(**kwargs):
            captured_report_prompt["value"] = kwargs["messages"][1]["content"]
            return report_response

        def review(report_text, evidence):
            captured_critic_evidence["value"] = evidence
            return None

        with (
            patch.object(
                investigation_runner,
                "create_investigation_plan",
                return_value=plan,
            ),
            patch.object(
                investigation_runner.tool_registry,
                "get_incident",
                return_value=incident,
            ),
            patch.object(
                investigation_runner.tool_registry,
                "get_deployment",
                return_value=deployment,
            ),
            patch.object(
                investigation_runner.tool_registry,
                "get_work_item",
                return_value={"id": 1234, "title": "Work item"},
            ),
            patch.object(
                investigation_runner.tool_registry,
                "get_pull_request",
                return_value={"id": 5678, "title": "Pull request"},
            ),
            patch.object(
                investigation_runner,
                "analyze_deployment",
                return_value=None,
            ),
            patch.object(
                investigation_runner.client.chat.completions,
                "create",
                side_effect=create_report,
            ),
            patch.object(
                investigation_runner,
                "review_report",
                side_effect=review,
            ),
        ):
            investigation_runner.run_investigation(
                "Investigate incident 1042",
                include_azure_devops=True,
            )

        self.assertIn("Work Item ID: 1234", captured_report_prompt["value"])
        self.assertIn("Work Item ID: 1234", captured_critic_evidence["value"])
        self.assertIn("Incident facts.", captured_critic_evidence["value"])


class DeploymentAgentTests(unittest.TestCase):
    @staticmethod
    def _response(content, finish_reason="stop"):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(content=content),
                )
            ]
        )

    def test_successful_deployment_analysis_does_not_retry(self):
        result = self._response(
            json.dumps({
                "deployment": "deployment-886.md",
                "change_summary": "Changed concurrency.",
                "risks": [],
                "related_incidents": [],
                "rollback_status": "Rolled back",
                "risk_rating": "High",
            })
        )
        with patch.object(
            deployment_agent.client.chat.completions,
            "create",
            return_value=result,
        ) as create:
            analysis = deployment_agent.analyze_deployment(
                "deployment-886.md",
                "Deployment evidence",
            )

        create.assert_called_once()
        self.assertEqual(analysis["risk_rating"], "High")
        self.assertEqual(create.call_args.kwargs["max_completion_tokens"], 3000)

    def test_empty_length_response_retries_once_with_5000_tokens(self):
        responses = [
            self._response(None, "length"),
            self._response(
                json.dumps({
                    "deployment": "deployment-886.md",
                    "change_summary": "Changed concurrency.",
                    "risks": [],
                    "related_incidents": [],
                    "rollback_status": "",
                    "risk_rating": "Medium",
                })
            ),
        ]
        with patch.object(
            deployment_agent.client.chat.completions,
            "create",
            side_effect=responses,
        ) as create:
            deployment_agent.analyze_deployment(
                "deployment-886.md",
                "Deployment evidence",
            )

        self.assertEqual(create.call_count, 2)
        self.assertEqual(
            create.call_args_list[1].kwargs["max_completion_tokens"],
            5000,
        )

    def test_two_failed_attempts_do_not_trigger_a_third_request(self):
        responses = [
            self._response(None, "length"),
            self._response(None, "length"),
        ]
        output = io.StringIO()
        with (
            patch.object(
                deployment_agent.client.chat.completions,
                "create",
                side_effect=responses,
            ) as create,
            redirect_stdout(output),
        ):
            analysis = deployment_agent.analyze_deployment(
                "deployment-886.md",
                "SECRET deployment evidence",
            )

        self.assertIsNone(analysis)
        self.assertEqual(create.call_count, 2)
        self.assertNotIn("SECRET deployment evidence", output.getvalue())
        self.assertIn("finish_reason=length", output.getvalue())


class EvalagentMcpServerTests(unittest.TestCase):
    def test_mcp_tools_are_exposed(self):
        names = asyncio.run(evalagent_mcp_server.mcp.list_tools())
        self.assertEqual(
            [tool.name for tool in names],
            [
                "get_incident",
                "get_deployment",
                "get_runbook",
                "get_work_item",
                "get_pull_request",
                "get_release",
            ],
        )

    def test_mcp_tools_delegate_to_lower_level_implementations(self):
        with (
            patch.object(
                evalagent_mcp_server.tool_implementations,
                "get_incident",
                return_value=[{"file": "incident-1042.md"}],
            ) as get_incident,
            patch.object(
                evalagent_mcp_server.tool_implementations,
                "get_deployment",
                return_value=[{"file": "deployment-886.md"}],
            ) as get_deployment,
            patch.object(
                evalagent_mcp_server.tool_implementations,
                "get_runbook",
                return_value=[{"file": "checkout-runbook.md"}],
            ) as get_runbook,
            patch.object(
                evalagent_mcp_server.tool_implementations,
                "get_work_item",
                return_value={"id": 2},
            ) as get_work_item,
            patch.object(
                evalagent_mcp_server.tool_implementations,
                "get_pull_request",
                return_value={"id": 1},
            ) as get_pull_request,
        ):
            self.assertEqual(
                evalagent_mcp_server.get_incident("1042"),
                [{"file": "incident-1042.md"}],
            )
            self.assertEqual(
                evalagent_mcp_server.get_deployment("886"),
                [{"file": "deployment-886.md"}],
            )
            self.assertEqual(
                evalagent_mcp_server.get_runbook("checkout-runbook"),
                [{"file": "checkout-runbook.md"}],
            )
            self.assertEqual(
                evalagent_mcp_server.get_work_item("2"),
                {"id": 2},
            )
            self.assertEqual(
                evalagent_mcp_server.get_pull_request("checkout-platform", "1"),
                {"id": 1},
            )

        get_incident.assert_called_once_with("1042")
        get_deployment.assert_called_once_with("886")
        get_runbook.assert_called_once_with("checkout-runbook")
        get_work_item.assert_called_once_with("2")
        get_pull_request.assert_called_once_with("checkout-platform", "1")

    def test_server_has_no_registry_dependency(self):
        self.assertFalse(hasattr(evalagent_mcp_server, "tool_registry"))


class EvalagentMcpClientTests(unittest.TestCase):
    def test_client_sends_tool_name_and_arguments(self):
        calls = []

        async def fake_call(name, arguments):
            calls.append((name, arguments))
            return {"id": arguments["work_item_id"]}

        with patch.object(evalagent_mcp_client, "_call_tool_async", fake_call):
            result = evalagent_mcp_client.get_work_item("42")

        self.assertEqual(result, {"id": "42"})
        self.assertEqual(calls, [("get_work_item", {"work_item_id": "42"})])

    def test_mcp_provider_uses_client(self):
        with (
            patch.dict("os.environ", {"EVALAGENT_TOOL_PROVIDER": "mcp"}),
            patch.object(
                evalagent_mcp_client,
                "call_tool",
                return_value=[{"file": "incident-1042.md"}],
            ) as call_tool,
        ):
            result = ToolRegistry().get_incident("1042")

        self.assertEqual(result, [{"file": "incident-1042.md"}])
        call_tool.assert_called_once_with(
            "get_incident",
            incident_id="1042",
        )

    def test_investigation_runner_uses_mcp_provider_and_preserves_contract(self):
        plan = {
            "incident_id": "1042",
            "deployment_id": None,
            "runbook_reference": None,
            "search_deployment": False,
            "search_runbooks": False,
        }
        incident = [{
            "source": "azure_ai_search",
            "category": "incident",
            "primary": False,
            "file": "incident-1042.md",
            "chunk_id": 0,
            "content": "Incident facts.",
        }]
        calls = []

        def call_tool(name, **arguments):
            calls.append((name, arguments))
            if name == "get_incident":
                return incident
            raise AssertionError(f"Unexpected MCP tool: {name}")

        report_response = InvestigationRunnerTests._response(json.dumps({}))

        with (
            patch.dict("os.environ", {"EVALAGENT_TOOL_PROVIDER": "mcp"}),
            patch.object(
                evalagent_mcp_client,
                "call_tool",
                side_effect=call_tool,
            ),
            patch.object(
                investigation_runner,
                "create_investigation_plan",
                return_value=plan,
            ),
            patch.object(
                investigation_runner.client.chat.completions,
                "create",
                return_value=report_response,
            ),
            patch.object(
                investigation_runner,
                "review_report",
                return_value=None,
            ),
        ):
            report_text, evidence = investigation_runner.run_investigation(
                "Investigate incident 1042"
            )

        self.assertEqual(calls, [("get_incident", {"incident_id": "incident-1042.md"})])
        self.assertIsInstance(report_text, str)
        self.assertIsInstance(evidence, list)
        self.assertEqual(evidence[0]["category"], "incident")
        self.assertEqual(evidence[0]["file"], "incident-1042.md")

    def test_direct_provider_preserves_existing_implementation(self):
        with (
            patch.dict("os.environ", {"EVALAGENT_TOOL_PROVIDER": "direct"}),
            patch.object(
                evalagent_mcp_client,
                "call_tool",
            ) as call_tool,
            patch.object(
                ToolRegistry,
                "_call",
                wraps=ToolRegistry._call,
            ),
            patch.object(
                __import__("backend.tool_implementations", fromlist=["get_incident"]),
                "get_incident",
                return_value=[{"file": "incident-1042.md"}],
            ) as direct_get_incident,
        ):
            result = ToolRegistry().get_incident("1042")

        self.assertEqual(result, [{"file": "incident-1042.md"}])
        direct_get_incident.assert_called_once_with("1042")
        call_tool.assert_not_called()

    def test_mcp_error_does_not_expose_secret(self):
        secret = "super-secret-pat"

        async def failing_call(name, arguments):
            raise RuntimeError(f"transport failed with {secret}")

        with patch.object(
            evalagent_mcp_client,
            "_call_tool_async",
            failing_call,
        ):
            with self.assertRaisesRegex(RuntimeError, "MCP tool 'get_work_item'") as error:
                evalagent_mcp_client.get_work_item("42")

        self.assertNotIn(secret, str(error.exception))


if __name__ == "__main__":
    unittest.main()
