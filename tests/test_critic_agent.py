import re
import unittest

from backend import critic_agent


def _normalize(text):
    return re.sub(r"\s+", " ", text).strip()


class CriticPromptTests(unittest.TestCase):
    """Regression tests for the Recommendations-vs-claims prompt clarification."""

    def setUp(self):
        self.normalized_prompt = _normalize(critic_agent.SYSTEM_PROMPT).lower()

    def test_prompt_clarifies_recommendations_are_proposed_not_implemented(self):
        self.assertIn(
            "the report's recommendations section contains proposed future "
            "actions, not claims that those actions already exist",
            self.normalized_prompt,
        )
        self.assertIn(
            "do not classify a recommendation as an unsupported claim merely "
            "because the evidence does not show that the proposed mechanism "
            "is already implemented, planned, approved, or deployed",
            self.normalized_prompt,
        )

    def test_prompt_still_flags_factual_premises_within_recommendations(self):
        self.assertIn(
            "if a recommendation itself asserts or implies a factual premise",
            self.normalized_prompt,
        )
        self.assertIn(
            "that factual premise is a claim and must be flagged as "
            "unsupported if the evidence does not establish it",
            self.normalized_prompt,
        )

    def test_prompt_preserves_strict_grounding_for_factual_sections(self):
        self.assertIn("apply strict grounding", self.normalized_prompt)
        for section in (
            "incident",
            "root cause",
            "impact",
            "resolution",
            "deployment analysis",
            "runbook analysis",
            "related documents",
            "azure devops evidence",
        ):
            self.assertIn(section, self.normalized_prompt)

    def test_prompt_distinguishes_azure_devops_text_mentions_from_retrieved_evidence(self):
        self.assertIn(
            "plain-text mentions of azure devops work item or pull request "
            "ids inside an incident, deployment, or runbook document are not "
            "the same as azure devops evidence retrieved through the azure "
            "devops integration",
            self.normalized_prompt,
        )
        self.assertIn(
            'do not flag a report statement such as "no azure devops evidence '
            'available." as unsupported merely because an ordinary retrieved '
            "document mentions an azure devops id in passing",
            self.normalized_prompt,
        )

    def test_prompt_still_requires_grounding_for_specific_azure_devops_claims(self):
        self.assertIn(
            "claims about specific work items, pull requests, states, "
            "descriptions, or other azure devops data still require strict "
            "grounding in the supplied evidence",
            self.normalized_prompt,
        )


if __name__ == "__main__":
    unittest.main()

