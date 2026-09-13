import json
import os
import re

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


SYSTEM_PROMPT = """You are a runbook analysis agent.
Analyze only the runbook content provided by the user and return a valid JSON
object with exactly these keys:
- runbook: the runbook filename provided by the user
- purpose: a concise purpose statement. Use an explicit Purpose section when
    present. Otherwise infer it only from the Title, Scope, Symptoms, and
    Immediate Actions sections.
- immediate_actions: a list of immediate actions explicitly supported by the runbook
- escalation_conditions: a list of escalation conditions explicitly supported by the runbook
- recovery_steps: a list of recovery steps explicitly supported by the runbook
- risk_level: exactly one of Low, Medium, or High, based only on the runbook

Do not infer facts from outside the supplied runbook. If a field is not
established by the runbook, use an empty string or an empty list as appropriate.
Do not include markdown or explanation outside the JSON object.
"""

EXPECTED_KEYS = (
    "runbook",
    "purpose",
    "immediate_actions",
    "escalation_conditions",
    "recovery_steps",
    "risk_level",
)
LIST_FIELDS = {
    "immediate_actions",
    "escalation_conditions",
    "recovery_steps",
}
VALID_RISK_LEVELS = {"Low", "Medium", "High"}


def _purpose_from_runbook(runbook_content):
    """Return a concise purpose using only runbook headings and content."""
    sections = {}
    current_heading = None
    for line in runbook_content.splitlines():
        heading_match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading_match:
            current_heading = heading_match.group(1).strip().lower()
            sections[current_heading] = []
        elif current_heading:
            sections[current_heading].append(line.strip())

    purpose_lines = sections.get("purpose", [])
    purpose = " ".join(line for line in purpose_lines if line).strip()
    if purpose:
        return purpose.split(". ", 1)[0].strip().rstrip(".")

    title = next(
        (
            line.strip().lstrip("#").strip()
            for line in runbook_content.splitlines()
            if re.match(r"^#\s+", line)
        ),
        "",
    )
    title = re.sub(r"\s+runbook$", "", title, flags=re.IGNORECASE).strip()
    if title:
        return f"{title} incident response and recovery"

    for heading in ("scope", "symptoms", "immediate actions"):
        content = " ".join(line for line in sections.get(heading, []) if line)
        if content:
            return content.split(". ", 1)[0].strip().rstrip(".")

    return ""


def analyze_runbook(runbook_file, runbook_content):
    """Analyze supplied runbook content and return a Python dictionary."""
    if not runbook_file or not str(runbook_file).strip():
        raise ValueError("runbook_file must not be empty")
    if not runbook_content or not str(runbook_content).strip():
        raise ValueError("runbook_content must not be empty")

    response = client.chat.completions.create(
        model=GPT5_MINI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Runbook file: {str(runbook_file).strip()}\n\n"
                    f"Supplied runbook:\n{str(runbook_content).strip()}"
                ),
            },
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=5000,
    )

    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise ValueError(
            "Runbook agent hit the token limit before producing a response."
        )

    message = choice.message
    response_content = getattr(message, "content", None)
    if response_content is None:
        response_content = getattr(message, "parsed", None)

    if isinstance(response_content, str):
        response_text = response_content.strip()
    elif isinstance(response_content, list):
        content_parts = []
        for part in response_content:
            if isinstance(part, str):
                content_parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if text:
                    content_parts.append(str(text))
            else:
                text = getattr(part, "text", None) or getattr(part, "content", None)
                if text:
                    content_parts.append(str(text))
        response_text = "".join(content_parts).strip()
    elif isinstance(response_content, dict):
        response_text = json.dumps(response_content)
    else:
        response_text = "" if response_content is None else str(response_content).strip()

    if not response_text:
        raise ValueError("The runbook analyzer returned an empty response")

    result = json.loads(response_text)
    if not isinstance(result, dict):
        raise ValueError("The runbook analyzer did not return a JSON object")

    normalized = {
        key: result.get(key, [] if key in LIST_FIELDS else "")
        for key in EXPECTED_KEYS
    }
    if not str(normalized["purpose"]).strip():
        normalized["purpose"] = _purpose_from_runbook(runbook_content)
    if normalized["risk_level"] not in VALID_RISK_LEVELS:
        raise ValueError("risk_level must be Low, Medium, or High")

    return normalized


if __name__ == "__main__":
    default_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "runbooks",
        "checkout-runbook.md",
    )
    runbook_path = input("Runbook file [Enter for default]: ").strip()
    if not runbook_path:
        runbook_path = default_path

    with open(runbook_path, encoding="utf-8") as runbook_handle:
        analysis = analyze_runbook(runbook_path, runbook_handle.read())
    print(json.dumps(analysis, indent=4))
