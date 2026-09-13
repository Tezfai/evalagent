import json
import os
import sys

from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

GPT5_MINI_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_GPT5_MINI_DEPLOYMENT",
    "gpt-5-mini",
)

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version="2024-12-01-preview",
)


SYSTEM_PROMPT = """You are an investigation report critic.
Review the investigation report against only the evidence supplied by the user.
Return a valid JSON object with exactly these keys:
- confidence: exactly one of Low, Medium, or High, based on how strongly the evidence supports the report
- report_quality: exactly one of Weak, Fair, or Strong, based on accuracy, completeness, and evidence support
- evidence_coverage: exactly one of Weak, Partial, or Strong, based on how much of the report is supported by the supplied evidence
- missing_evidence: a list of evidence gaps explicitly identified by comparing the report with the supplied evidence
- unsupported_claims: a list of report claims not supported by the supplied evidence
- recommended_next_steps: a list of actionable steps to close identified evidence gaps
- review_summary: a concise review summary supported only by the supplied report and evidence

Confidence scoring rules:
- High:
    - Primary evidence exists.
    - Supporting evidence exists.
    - Claims are directly supported.
- Medium:
    - Evidence provides partial support.
    - Some evidence gaps remain.
- Low:
    - Evidence is missing.
    - Conclusions rely heavily on inference.

When evidence gaps exist, provide concrete recommended_next_steps such as
retrieving deployment logs, reviewing database metrics, or collecting a
rollback timeline. Return an empty list when no next steps are supported by
the supplied report and evidence.

Do not use outside knowledge or infer facts beyond the supplied evidence. If no
missing evidence or unsupported claims can be identified, return an empty list.
Do not include markdown or explanation outside the JSON object.
"""

EXPECTED_KEYS = (
    "confidence",
    "report_quality",
    "evidence_coverage",
    "missing_evidence",
    "unsupported_claims",
    "recommended_next_steps",
    "review_summary",
)
LIST_FIELDS = {
    "missing_evidence",
    "unsupported_claims",
    "recommended_next_steps",
}
VALID_CONFIDENCE = {"Low", "Medium", "High"}
VALID_REPORT_QUALITY = {"Weak", "Fair", "Strong"}
VALID_EVIDENCE_COVERAGE = {"Weak", "Partial", "Strong"}


def review_report(report_text, evidence):
    """Review a report against supplied evidence and return a Python dictionary."""
    if not report_text or not str(report_text).strip():
        raise ValueError("report_text must not be empty")
    if not evidence:
        raise ValueError("evidence must not be empty")

    evidence_text = evidence if isinstance(evidence, str) else json.dumps(evidence)
    if not evidence_text.strip():
        raise ValueError("evidence must not be empty")

    response = client.chat.completions.create(
        model=GPT5_MINI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Investigation report:\n{str(report_text).strip()}\n\n"
                    f"Supplied evidence:\n{evidence_text.strip()}"
                ),
            },
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=10000,
    )

    if response.choices[0].finish_reason == "length":
        raise ValueError(
            "Critic agent hit the token limit before producing a response."
        )

    response_text = response.choices[0].message.content
    if not response_text:
        raise ValueError("The report critic returned an empty response")

    result = json.loads(response_text)
    if not isinstance(result, dict):
        raise ValueError("The report critic did not return a JSON object")

    normalized = {
        key: result.get(key, [] if key in LIST_FIELDS else "")
        for key in EXPECTED_KEYS
    }
    if normalized["confidence"] not in VALID_CONFIDENCE:
        raise ValueError("confidence must be Low, Medium, or High")
    if normalized["report_quality"] not in VALID_REPORT_QUALITY:
        raise ValueError("report_quality must be Weak, Fair, or Strong")
    if normalized["evidence_coverage"] not in VALID_EVIDENCE_COVERAGE:
        raise ValueError("evidence_coverage must be Weak, Partial, or Strong")
    if not isinstance(normalized["recommended_next_steps"], list):
        raise ValueError("recommended_next_steps must be a list")

    return normalized


if __name__ == "__main__":
    report_path = sys.argv[1] if len(sys.argv) > 1 else input("Report file: ").strip()
    evidence_path = sys.argv[2] if len(sys.argv) > 2 else input("Evidence file: ").strip()

    with open(report_path, encoding="utf-8") as report_handle:
        report_content = report_handle.read()
    with open(evidence_path, encoding="utf-8") as evidence_handle:
        evidence_content = evidence_handle.read()

    review = review_report(report_content, evidence_content)
    print(json.dumps(review, indent=4))
