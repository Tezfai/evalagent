import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

from tests.offline_bootstrap import configure_offline_tests

configure_offline_tests()

import streamlit as st
from streamlit.testing.v1 import AppTest

from frontend import INTEGRATION_CHOICES, extract_fields, load_source_document, number_recommendations, split_report


STRUCTURED_REPORT = (
    "Primary Evidence: incident-1042.md\n\n"
    "## Incident\nIncident ID: 1042; Severity: SEV-2; Status: Resolved; Service: checkout-service; Date: 2025-01-14; Duration: 47 minutes; Related deployment: deployment-882\n\n"
    "## Root Cause\nRedis connection pool saturation following deployment 882.\n\n"
    "## Impact\nAffected Service Behavior: Checkout requests queued.\nReported Metrics: p95 latency rose from 420 ms to 3.8 seconds.\nUser Impact: Approximately 18% of requests in US-East were affected.\n\n"
    "## Resolution\nThe on-call rolled back deployment 882 and drained affected pods.\n\n"
    "## Recommendations\n- Validate bounded connection reuse under load.\n- Review per-request lookup limits.\n\n"
    "## Deployment Analysis\nChange Summary: Increased cart-session fan-out.\nAssessed Risk Rating: Not established by retrieved evidence.\nRelated Incidents: incident-1042\nRollback Status: Rolled back\n\n"
    "## Runbook Analysis\nPurpose: Restore checkout availability.\n\nImmediate Actions:\n- Inspect connection pool saturation.\n- Review the deployment.\n\nEscalation Conditions:\n- Not established by retrieved evidence.\n\nRecovery Steps:\n- None available.\n\nRisk Level: Not established by retrieved evidence.\n\n"
    "## Related Documents\nRetrieved:\n- incident-1042.md\n\nReferenced but Not Retrieved:\n- unverified-document.md\n\n"
    "## Report Review\nConfidence: medium\nReport Quality: acceptable\nEvidence Coverage: partial\n\nMissing Evidence:\n- Rollback validation evidence.\n\nUnsupported Claims:\n- None identified.\n\nRecommended Next Steps:\n- Verify recovery metrics.\n\nReview Summary: Further evidence would improve grounding.\n\n"
    "## Unfamiliar Section\nKeep every word of this section.\n"
)


class PresentationTests(unittest.TestCase):
    def test_labeled_fields_keep_unknown_values_and_multiline_content(self):
        text = "Change Summary: Pool size changed\nAssessed Risk Rating: Not established by retrieved evidence.\nRelated Incidents: incident-1042\nRollback Status: None available."
        fields = extract_fields(text, ("Change Summary", "Assessed Risk Rating", "Related Incidents", "Rollback Status"))
        self.assertEqual(fields[1], ("Assessed Risk Rating", "Not established by retrieved evidence."))
        self.assertEqual(fields[-1], ("Rollback Status", "None available."))
        self.assertEqual(extract_fields("Purpose: Restore service\nImmediate Actions:\n- Restart\n- Check logs", ("Purpose", "Immediate Actions"))[-1][1], "- Restart\n- Check logs")

    def test_incident_metadata_requires_labels_and_handles_inline_or_bold_fields(self):
        self.assertEqual(extract_fields("Incident ID: 1042; Severity: SEV-2; Service: checkout", ("Incident ID", "Severity", "Service")), [("Incident ID", "1042"), ("Severity", "SEV-2"), ("Service", "checkout")])
        self.assertEqual(extract_fields("- **Severity:** SEV-2", ("Severity",)), [("Severity", "SEV-2")])
        self.assertIsNone(extract_fields("Incident 1042 affected checkout", ("Incident ID", "Severity")))
        self.assertIsNone(extract_fields("Incident: Checkout latency affected users.", ("Incident ID",)))
        self.assertIsNone(extract_fields("Severity: SEV-2\nSeverity: Unknown", ("Severity",)))

    def test_recommendations_preserve_order_content_and_continuations(self):
        self.assertEqual(number_recommendations("- First action\n  With more detail\n- Second action\n"), "1. First action\n  With more detail\n2. Second action\n")
        self.assertEqual(number_recommendations("Unfamiliar prose"), "Unfamiliar prose")
        self.assertEqual(number_recommendations("1. First action. 2. Second action."), "1. First action.\n2. Second action.")

    def test_unknown_field_labels_or_unfamiliar_delimiters_fall_back(self):
        self.assertIsNone(extract_fields("Severity: SEV-2\nUnfamiliar Field: preserve me", ("Severity",)))
        self.assertIsNone(extract_fields("Severity: SEV-2, Status: Resolved", ("Severity", "Status")))

    def test_report_split_is_lossless_with_unknown_duplicate_and_fenced_headings(self):
        report = (
            "Primary Evidence: incident-1042.md\r\n\r\n"
            "## Incident\r\nObserved impact\r\n"
            "## Unknown Heading\r\nPreserve this\r\n"
            "```markdown\r\n## Root Cause\r\nNot a section\r\n```\r\n"
            "## Incident\r\nAdditional incident detail"
        )
        sections = split_report(report)
        self.assertEqual("".join(section.markdown for section in sections), report)
        self.assertEqual([section.title for section in sections], [None, "Incident", "Unknown Heading", "Incident"])

    def test_empty_and_unstructured_reports(self):
        self.assertEqual(split_report(""), [])
        self.assertEqual(split_report("Unstructured answer")[0].markdown, "Unstructured answer")

    def test_application_insights_choices_preserve_semantics(self):
        self.assertEqual(INTEGRATION_CHOICES, {"Auto": None, "Include": True, "Exclude": False})

    def test_source_lookup_uses_backup_and_windows_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "incident-1042.md"
            document.write_text("Full document", encoding="utf-8")
            self.assertEqual(
                load_source_document(r"data\incidents\incident-1042.md", [root / "missing", root]),
                "Full document",
            )
            self.assertIsNone(load_source_document("application-insights://checkout", [root]))
            self.assertIsNone(load_source_document("missing.md", [root]))


class FrontendWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.rag = ModuleType("backend.rag_ai_search")
        self.rag.ask_question = Mock(return_value=("A grounded answer", [{"file": "missing.md", "chunk_id": 0, "content": "Retrieved text"}]))
        self.runner = ModuleType("backend.investigation_runner")
        self.report = (
            "Primary Evidence: incident-1042.md\n\n"
            "## Incident\nIncident detail\n\n## Root Cause\nRoot detail\n"
            "## Impact\nImpact detail\n## Resolution\nResolution detail\n"
            "## Recommendations\nNext steps\n"
            "## Deployment Analysis\nDeployment detail\n"
            "## Runbook Analysis\nRunbook detail\n"
            "## Related Documents\nDocument detail\n"
            "## Azure DevOps Evidence\nWork item detail\n"
            "## Report Review\nConfidence: medium\n"
            "## Unexpected Heading\nDo not lose this text\n"
        )
        self.evidence = [{"file": "missing.md", "chunk_id": "0, 1", "content": "Primary source", "primary": True, "category": "incident"}]
        self.runner.run_investigation = Mock(return_value=(self.report, self.evidence))
        self.modules = patch.dict("sys.modules", {
            "backend.rag_ai_search": self.rag,
            "backend.investigation_runner": self.runner,
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.download_patch = patch("frontend.st.download_button", wraps=st.download_button)
        self.download = self.download_patch.start()
        self.addCleanup(self.download_patch.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
        self.assertFalse(self.app.exception)

    def investigate(self, question="Investigate incident 1042"):
        self.app.text_area[0].input(question)
        next(button for button in self.app.button if button.label == "Run investigation").click().run()
        self.assertFalse(self.app.exception)

    def conversation(self):
        self.app.radio(key="mode").set_value("Conversation").run()
        self.assertFalse(self.app.exception)

    def test_investigation_default_parameters_sections_and_download(self):
        self.investigate()
        self.runner.run_investigation.assert_called_once_with(
            "Investigate incident 1042", include_azure_devops=False, include_application_insights=None,
        )
        self.assertEqual([tab.label for tab in self.app.tabs], ["Overview", "Deployment", "Runbook", "Evidence", "Review"])
        rendered = "\n".join(element.value for element in self.app.markdown)
        for text in ("Incident detail", "Deployment detail", "Runbook detail", "Confidence: medium", "Do not lose this text", "Primary source", "Chunk: 0, 1"):
            self.assertIn(text, rendered + "\n" + "\n".join(element.value for element in self.app.caption))
        self.assertEqual(self.app.code[0].value, self.report.strip())
        self.assertEqual(len(self.app.get("download_button")), 1)
        self.assertEqual(self.download.call_args.kwargs["data"], self.report)
        self.assertEqual(self.download.call_args.kwargs["mime"], "text/markdown")
        self.assertEqual(self.app.session_state.investigations[0]["report"], self.report)
        self.assertEqual(self.app.session_state.investigations[0]["sources"], self.evidence)
        self.assertTrue(any("not an independent verification" in element.value for element in self.app.info))

    def test_integration_choices(self):
        self.assertEqual(self.app.selectbox(key="include_azure_devops").options, ["Exclude", "Include"])
        for azure_devops in (False, True):
            for choice, expected in INTEGRATION_CHOICES.items():
                with self.subTest(azure_devops=azure_devops, choice=choice):
                    self.app.selectbox(key="include_azure_devops").select(azure_devops)
                    self.app.selectbox(key="application_insights").select(choice).run()
                    self.investigate()
                    self.assertEqual(self.runner.run_investigation.call_args.kwargs, {
                        "include_azure_devops": azure_devops, "include_application_insights": expected,
                    })

    def test_qa_suggestions_separate_histories_and_clear(self):
        self.investigate()
        self.conversation()
        self.app.button(key="suggestion_0").click().run()
        self.rag.ask_question.assert_called_once_with("What caused the checkout latency incident?")
        self.assertEqual(len(self.app.chat_message), 2)
        self.assertEqual(self.app.session_state.messages[1]["content"], "A grounded answer")
        self.app.radio(key="mode").set_value("Investigate").run()
        self.assertEqual(len(self.app.session_state.investigations), 1)
        self.assertEqual(len(self.app.session_state.messages), 2)
        self.conversation()
        self.app.chat_input[0].set_value("Another question").run()
        self.assertEqual(len(self.app.session_state.messages), 4)
        next(button for button in self.app.button if button.label == "Clear conversation").click().run()
        self.assertEqual(self.app.session_state.messages, [])
        self.assertEqual(len(self.app.session_state.investigations), 1)

    def test_errors_do_not_expose_sensitive_exception_text(self):
        secret = "SECRET_TOKEN internal traceback configuration"
        self.runner.run_investigation.side_effect = RuntimeError(secret)
        self.investigate()
        self.assertTrue(self.app.error)
        self.assertNotIn(secret, str(self.app))
        self.conversation()
        self.rag.ask_question.side_effect = RuntimeError(secret)
        self.app.chat_input[0].set_value("Question").run()
        self.assertTrue(self.app.error)
        self.assertNotIn(secret, str(self.app))

    def test_empty_responses_keep_evidence_and_missing_sections(self):
        self.runner.run_investigation.return_value = (None, self.evidence)
        self.investigate()
        self.assertTrue(self.app.warning)
        self.assertIn("Primary source", "\n".join(element.value for element in self.app.markdown))
        self.assertTrue(any("No deployment section" in element.value for element in self.app.caption))
        self.conversation()
        self.rag.ask_question.return_value = (None, self.evidence)
        self.app.chat_input[0].set_value("Question").run()
        self.assertIn("No answer text", self.app.session_state.messages[1]["content"])
        self.assertEqual(self.app.session_state.messages[1]["sources"], self.evidence)

    def test_blank_request_does_not_call_backend(self):
        self.investigate("   ")
        self.runner.run_investigation.assert_not_called()
        self.assertTrue(self.app.warning)

    def test_settings_draft_and_history_selection_survive_mode_switch(self):
        self.app.selectbox(key="include_azure_devops").select(True)
        self.app.selectbox(key="application_insights").select("Exclude").run()
        self.investigate("First investigation")
        self.investigate("Second investigation")
        self.app.selectbox(key="history_2").select_index(1).run()
        self.assertEqual(self.app.session_state.selected_investigation, 0)
        self.conversation()
        self.app.radio(key="mode").set_value("Investigate").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state.selected_investigation, 0)
        self.assertTrue(self.app.selectbox(key="include_azure_devops").value)
        self.assertEqual(self.app.selectbox(key="application_insights").value, "Exclude")
        self.assertEqual(self.app.text_area[0].value, "Second investigation")
        next(button for button in self.app.button if button.label == "Clear investigations").click().run()
        self.assertEqual(self.app.session_state.investigations, [])

    def test_full_document_and_retrieved_evidence_both_display(self):
        self.conversation()
        with patch("frontend.load_source_document", return_value="Complete local document"):
            self.app.chat_input[0].set_value("Question").run()
        rendered = "\n".join(element.value for element in self.app.markdown)
        self.assertIn("Complete local document", rendered)
        self.assertIn("Retrieved text", rendered)
        self.assertIn("missing.md", "\n".join(element.value for element in self.app.caption))

    def test_examples_prefill_without_execution_and_failures_can_retry(self):
        self.app.button(key="investigation_example_0").click().run()
        self.assertEqual(self.app.text_area[0].value, "What caused the checkout latency incident?")
        self.runner.run_investigation.assert_not_called()
        self.runner.run_investigation.side_effect = RuntimeError("private details")
        self.investigate()
        self.assertFalse(self.app.session_state.investigation_running)
        self.runner.run_investigation.side_effect = None
        next(button for button in self.app.button if button.label == "Retry investigation").click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.runner.run_investigation.call_count, 2)
        self.assertEqual(self.app.session_state.investigations[-1]["question"], "Investigate incident 1042")
        self.assertFalse(self.app.session_state.investigations[-1]["failed"])

    def test_execution_is_marked_running_only_during_backend_call(self):
        def backend_response(*args, **kwargs):
            self.assertTrue(st.session_state.investigation_running)
            return self.report, self.evidence
        self.runner.run_investigation.side_effect = backend_response
        self.investigate()
        self.assertFalse(self.app.session_state.investigation_running)

    def test_structured_report_fields_lists_provenance_and_actions(self):
        self.runner.run_investigation.return_value = (STRUCTURED_REPORT, self.evidence)
        self.investigate()
        captions = [element.value for element in self.app.caption]
        for label in ("Incident ID", "Severity", "Status", "Service", "Incident Date", "Duration", "Related Deployment", "Confidence", "Report Quality", "Evidence Coverage"):
            self.assertIn(label, captions)
        values = [element.value for element in self.app.markdown]
        for value in ("**1042**", "**checkout-service**", "**2025-01-14**", "**47 minutes**", "**deployment-882**", "**medium**", "**acceptable**", "**partial**", "Not established by retrieved evidence.", "- None available."):
            self.assertIn(value, values)
        self.assertTrue(any("orange-badge[SEV-2]" in value for value in values))
        self.assertTrue(any("gray-badge[Resolved]" in value for value in values))
        self.assertIn("1. Validate bounded connection reuse under load.\n2. Review per-request lookup limits.", values)
        self.assertIn("**Change Summary**", values)
        self.assertIn("**Immediate Actions**", values)
        self.assertIn("**Unsupported Claims**", values)
        self.assertIn("**User Impact**", values)
        self.assertTrue(any("not retrieved or analyzed" in caption for caption in captions))
        self.assertIn("incident | missing.md | Chunk 0, 1", [element.label for element in self.app.expander])
        self.assertEqual(self.download.call_args.kwargs["data"], STRUCTURED_REPORT)
        self.assertEqual(self.app.session_state.investigations[0]["report"], STRUCTURED_REPORT)
        self.assertEqual(len(self.app.get("download_button")), 1)
        for tab in self.app.tabs:
            self.assertFalse(tab.get("download_button"))
            self.assertFalse(any(element.label == "Complete original Markdown report" for element in tab.get("expander")))

    def test_unfamiliar_field_formats_are_displayed_without_loss(self):
        report = "## Deployment Analysis\nChange Summary: Something changed\nUnknown Field: Keep this detail\n\n## Incident\nAn incident described without metadata labels.\n"
        self.runner.run_investigation.return_value = (report, [])
        self.investigate()
        rendered = "\n".join(element.value for element in self.app.markdown)
        self.assertIn("Unknown Field: Keep this detail", rendered)
        self.assertIn("An incident described without metadata labels.", rendered)
        self.assertEqual(self.download.call_args.kwargs["data"], report)

    def test_primary_and_supporting_evidence_keep_categories_and_chunk_zero(self):
        sources = self.evidence + [{"file": "supporting.md", "chunk_id": 0, "content": "Supporting deployment evidence", "category": "deployment", "primary": False}]
        self.runner.run_investigation.return_value = (STRUCTURED_REPORT, sources)
        self.investigate()
        self.assertIn("Primary evidence", [element.value for element in self.app.subheader])
        self.assertIn("Supporting evidence", [element.value for element in self.app.subheader])
        self.assertIn("deployment | supporting.md | Chunk 0", [element.label for element in self.app.expander])
        self.assertEqual(self.app.session_state.investigations[-1]["sources"], sources)


if __name__ == "__main__":
    unittest.main()