import unittest
from unittest.mock import patch

from backend import eval_harness
from backend import investigation_runner as ir


class EvalHarnessTests(unittest.TestCase):
    CASE = {
        "id": "incident-1042",
        "question": "Investigate incident 1042",
        "expected_primary_evidence": "incident-1042.md",
        "expected_deployment": "deployment-882.md",
        "expected_runbook": "redis-cache-runbook.md",
        "expected_service": "checkout-service",
        "root_cause_keywords": ["redis", "connection pool", "deployment 882"],
    }

    EVIDENCE = [
        {
            "file": "incident-1042.md",
            "chunk_id": 0,
            "content": "- **Service:** checkout-service\nCheckout latency incident.",
            "category": "incident",
            "primary": True,
        },
        {
            "file": "deployment-882.md",
            "chunk_id": 0,
            "content": "Deployment 882 details.",
            "category": "deployment",
            "primary": False,
        },
        {
            "file": "redis-cache-runbook.md",
            "chunk_id": 0,
            "content": "Redis cache runbook.",
            "category": "runbook",
            "primary": False,
        },
    ]

    def _report(self, unsupported_claims="- None identified.", evidence_coverage="Strong"):
        return (
            "Primary Evidence: incident-1042.md\n\n"
            "## Root Cause\n"
            "Deployment 882 opened a Redis connection per lookup, exhausting "
            "the connection pool.\n\n"
            "## Report Review\n"
            "Confidence: High\n"
            "Report Quality: Strong\n"
            f"Evidence Coverage: {evidence_coverage}\n\n"
            "Missing Evidence:\n"
            "- None identified.\n\n"
            "Unsupported Claims:\n"
            f"{unsupported_claims}\n\n"
            "Recommended Next Steps:\n"
            "- None identified.\n\n"
            "Review Summary: Well supported."
        )

    def test_all_metrics_pass_for_fully_supported_report(self):
        result = eval_harness.evaluate_case(self.CASE, self._report(), self.EVIDENCE)

        self.assertTrue(result["primary_evidence_pass"])
        self.assertTrue(result["deployment_pass"])
        self.assertTrue(result["runbook_pass"])
        self.assertTrue(result["service_pass"])
        self.assertTrue(result["root_cause_pass"])
        self.assertEqual(result["root_cause_coverage"], 1.0)
        self.assertTrue(result["grounding_pass"])

    def test_missing_deployment_and_runbook_evidence_fail(self):
        evidence = [self.EVIDENCE[0]]

        result = eval_harness.evaluate_case(self.CASE, self._report(), evidence)

        self.assertTrue(result["primary_evidence_pass"])
        self.assertFalse(result["deployment_pass"])
        self.assertFalse(result["runbook_pass"])

    def test_unsupported_claims_fail_grounding(self):
        report = self._report(unsupported_claims="- Recovery time was under 5 minutes.")

        result = eval_harness.evaluate_case(self.CASE, report, self.EVIDENCE)

        self.assertFalse(result["grounding_pass"])

    def test_grounding_failure_reports_evidence_coverage_and_unsupported_claims(self):
        report = self._report(
            unsupported_claims=(
                "- Recovery time was under 5 minutes.\n"
                "- The rollback was performed by the on-call engineer."
            ),
            evidence_coverage="Partial",
        )

        result = eval_harness.evaluate_case(self.CASE, report, self.EVIDENCE)

        self.assertFalse(result["grounding_pass"])
        self.assertEqual(result["grounding_evidence_coverage"], "Partial")
        self.assertEqual(
            result["grounding_unsupported_claims"],
            [
                "Recovery time was under 5 minutes.",
                "The rollback was performed by the on-call engineer.",
            ],
        )

    def test_grounding_pass_reports_no_unsupported_claims(self):
        result = eval_harness.evaluate_case(self.CASE, self._report(), self.EVIDENCE)

        self.assertTrue(result["grounding_pass"])
        self.assertEqual(result["grounding_unsupported_claims"], [])

    def test_format_report_shows_details_only_on_grounding_failure(self):
        passing = eval_harness.evaluate_case(self.CASE, self._report(), self.EVIDENCE)
        failing_report = self._report(
            unsupported_claims="- Recovery time was under 5 minutes.",
            evidence_coverage="Partial",
        )
        failing = eval_harness.evaluate_case(self.CASE, failing_report, self.EVIDENCE)

        rendered = eval_harness.format_report(
            [passing, failing], eval_harness.aggregate_results([passing, failing])
        )

        self.assertIn("Grounding: PASS", rendered)
        self.assertIn("Grounding: FAIL", rendered)
        self.assertIn("Evidence Coverage: Partial", rendered)
        self.assertIn("Unsupported Claims:\n- Recovery time was under 5 minutes.", rendered)

    def test_weak_evidence_coverage_fails_grounding(self):
        report = self._report(evidence_coverage="Weak")

        result = eval_harness.evaluate_case(self.CASE, report, self.EVIDENCE)

        self.assertFalse(result["grounding_pass"])

    def test_root_cause_keyword_coverage_below_threshold_fails(self):
        report = (
            "Primary Evidence: incident-1042.md\n\n"
            "## Root Cause\n"
            "The checkout service experienced elevated latency.\n\n"
            "## Report Review\n"
            "Evidence Coverage: Strong\n\n"
            "Unsupported Claims:\n"
            "- None identified.\n\n"
            "Recommended Next Steps:\n"
            "- None identified."
        )

        result = eval_harness.evaluate_case(self.CASE, report, self.EVIDENCE)

        self.assertEqual(result["root_cause_coverage"], 0.0)
        self.assertFalse(result["root_cause_pass"])

    def test_root_cause_matching_normalizes_hyphen_vs_space(self):
        """"deployment 882" must match "Deployment-882" in generated text -
        equivalent phrasing must not be scored as a miss."""
        report = (
            "Primary Evidence: incident-1042.md\n\n"
            "## Root Cause\n"
            "Deployment-882 saturated the Redis connection pool.\n\n"
            "## Report Review\n"
            "Evidence Coverage: Strong\n\n"
            "Unsupported Claims:\n"
            "- None identified.\n\n"
            "Recommended Next Steps:\n"
            "- None identified."
        )

        result = eval_harness.evaluate_case(self.CASE, report, self.EVIDENCE)

        self.assertEqual(result["root_cause_coverage"], 1.0)
        self.assertTrue(result["root_cause_pass"])

    def test_root_cause_matching_normalizes_underscores_and_whitespace(self):
        case = {**self.CASE, "root_cause_keywords": ["connection_pool"]}
        report = (
            "Primary Evidence: incident-1042.md\n\n"
            "## Root Cause\n"
            "The change saturated the connection   pool under load.\n\n"
            "## Report Review\n"
            "Evidence Coverage: Strong\n\n"
            "Unsupported Claims:\n"
            "- None identified.\n\n"
            "Recommended Next Steps:\n"
            "- None identified."
        )

        result = eval_harness.evaluate_case(case, report, self.EVIDENCE)

        self.assertEqual(result["root_cause_coverage"], 1.0)

    def test_case_without_expected_runbook_is_not_applicable(self):
        case = {**self.CASE, "expected_runbook": None}

        result = eval_harness.evaluate_case(case, self._report(), self.EVIDENCE)

        self.assertIsNone(result["runbook_pass"])

    def test_aggregate_results_computes_pass_rates_and_skips_not_applicable(self):
        results = [
            {
                "primary_evidence_pass": True,
                "deployment_pass": True,
                "runbook_pass": None,
                "service_pass": True,
                "root_cause_pass": True,
                "grounding_pass": True,
            },
            {
                "primary_evidence_pass": True,
                "deployment_pass": False,
                "runbook_pass": True,
                "service_pass": False,
                "root_cause_pass": False,
                "grounding_pass": True,
            },
        ]

        aggregate = eval_harness.aggregate_results(results)

        self.assertEqual(aggregate["Primary Evidence Accuracy"], 1.0)
        self.assertEqual(aggregate["Deployment Retrieval"], 0.5)
        self.assertEqual(aggregate["Runbook Retrieval"], 1.0)
        self.assertEqual(aggregate["Service Accuracy"], 0.5)
        self.assertEqual(aggregate["Root Cause Accuracy"], 0.5)
        self.assertEqual(aggregate["Grounding Pass Rate"], 1.0)
        self.assertEqual(aggregate["Execution Error Rate"], 0.0)

    def test_service_pass_is_unaffected_and_surfaced_in_format_report(self):
        result = eval_harness.evaluate_case(self.CASE, self._report(), self.EVIDENCE)

        # service_pass calculation itself is unchanged.
        self.assertTrue(result["service_pass"])

        rendered = eval_harness.format_report(
            [result], eval_harness.aggregate_results([result])
        )

        self.assertIn("Service: PASS", rendered)
        self.assertIn("Service Accuracy: 100%", rendered)

    def test_load_cases_reads_all_ten_incidents(self):
        cases = eval_harness.load_cases()

        self.assertEqual(len(cases), 10)
        self.assertEqual(cases[0]["id"], "incident-1042")

    def test_execution_error_is_not_counted_as_a_metric_failure(self):
        """An MCP/transport failure must show up as ERROR, not as FAIL,
        so it does not distort accuracy metrics."""
        cases = [self.CASE, {**self.CASE, "id": "incident-1043"}]

        def fake_run_case(case):
            if case["id"] == "incident-1043":
                raise RuntimeError("MCP tool 'get_runbook' is unavailable")
            return {
                "id": case["id"],
                "status": "OK",
                "primary_evidence_pass": True,
                "deployment_pass": True,
                "runbook_pass": True,
                "root_cause_pass": True,
                "grounding_pass": True,
            }

        with patch.object(eval_harness, "run_case", side_effect=fake_run_case):
            results, aggregate = eval_harness.run_all(cases)

        error_result = next(r for r in results if r["id"] == "incident-1043")
        self.assertEqual(error_result["status"], "ERROR")
        self.assertIn("MCP tool", error_result["error"])
        self.assertIsNone(error_result["primary_evidence_pass"])
        self.assertIsNone(error_result["root_cause_pass"])

        # The errored case must be excluded from accuracy metrics, not scored as a FAIL.
        self.assertEqual(aggregate["Primary Evidence Accuracy"], 1.0)
        self.assertEqual(aggregate["Root Cause Accuracy"], 1.0)
        self.assertEqual(aggregate["Execution Error Rate"], 0.5)

    def test_format_report_shows_error_status_instead_of_fabricated_pass_fail(self):
        results = [{
            "id": "incident-1043",
            "status": "ERROR",
            "primary_evidence_pass": None,
            "deployment_pass": None,
            "runbook_pass": None,
            "root_cause_pass": None,
            "grounding_pass": None,
            "error": "MCP tool 'get_runbook' is unavailable",
        }]

        report = eval_harness.format_report(results, eval_harness.aggregate_results(results))

        self.assertIn("Status: ERROR (MCP tool 'get_runbook' is unavailable)", report)
        self.assertNotIn("Primary Evidence: FAIL", report)
        self.assertNotIn("Primary Evidence: PASS", report)

    def _real_format_review(self, review):
        return ir._format_report_review(review)

    def _real_report(self, review):
        sections = {
            name: "na"
            for name in (
                "Deployment Analysis", "Runbook Analysis", "Incident",
                "Root Cause", "Impact", "Resolution", "Related Documents",
                "Recommendations", "Azure DevOps Evidence",
            )
        }
        sections["Report Review"] = self._real_format_review(review)
        return ir._format_report(sections, ["incident-1042.md"])

    def test_grounding_parser_is_robust_to_embedded_blank_lines_in_critic_fields(self):
        """A critic missing_evidence item that happens to contain a blank
        line followed by markdown-like text must not truncate the section
        and hide a genuinely clean Unsupported Claims verdict."""
        review = {
            "confidence": "High",
            "report_quality": "Strong",
            "evidence_coverage": "Strong",
            "missing_evidence": [
                "Quoted runbook excerpt:\n\n## Escalation Conditions\nPage on-call if..."
            ],
            "unsupported_claims": [],
            "recommended_next_steps": [],
            "review_summary": "Well supported.",
        }

        report_text = self._real_report(review)

        self.assertTrue(eval_harness._grounding_pass(report_text))

    def test_grounding_parser_still_fails_genuine_unsupported_claims(self):
        review = {
            "confidence": "Medium",
            "report_quality": "Fair",
            "evidence_coverage": "Partial",
            "missing_evidence": [],
            "unsupported_claims": ["Recovery time was under 5 minutes."],
            "recommended_next_steps": [],
            "review_summary": "Some claims are unproven.",
        }

        report_text = self._real_report(review)

        self.assertFalse(eval_harness._grounding_pass(report_text))

    def test_grounding_parser_still_fails_weak_evidence_coverage(self):
        review = {
            "confidence": "Low",
            "report_quality": "Weak",
            "evidence_coverage": "Weak",
            "missing_evidence": ["Deployment logs."],
            "unsupported_claims": [],
            "recommended_next_steps": ["Retrieve deployment logs."],
            "review_summary": "Insufficient evidence.",
        }

        report_text = self._real_report(review)

        self.assertFalse(eval_harness._grounding_pass(report_text))


if __name__ == "__main__":
    unittest.main()
