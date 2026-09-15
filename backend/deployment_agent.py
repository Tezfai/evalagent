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


SYSTEM_PROMPT = """You are a deployment analysis agent.
Analyze only the deployment evidence provided by the user and return a valid
JSON object with exactly these keys:
- deployment: the deployment filename provided by the user
- change_summary: a concise summary of the change, or an empty string if the evidence does not establish one
- risks: a list of risks explicitly supported by the evidence
- related_incidents: a list of incident identifiers explicitly supported by the evidence
- rollback_status: the rollback status explicitly supported by the evidence, or an empty string
- risk_rating: exactly one of Low, Medium, or High, based only on the evidence

Do not infer facts from outside the evidence. If a field is not established by
the evidence, use an empty string or an empty list as appropriate. Do not
include markdown or explanation outside the JSON object.
"""


EXPECTED_KEYS = (
    "deployment",
    "change_summary",
    "risks",
    "related_incidents",
    "rollback_status",
    "risk_rating",
)
VALID_RISK_RATINGS = {"Low", "Medium", "High"}


def analyze_deployment(deployment_file, deployment_content):
    """Analyze deployment evidence and return the result as a Python dictionary."""
    if not deployment_file or not str(deployment_file).strip():
        raise ValueError("deployment_file must not be empty")
    if not deployment_content or not str(deployment_content).strip():
        raise ValueError("deployment_content must not be empty")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Deployment file: {str(deployment_file).strip()}\n\n"
                f"Deployment evidence:\n{str(deployment_content).strip()}"
            ),
        },
    ]

    response = client.chat.completions.create(
        model=GPT5_MINI_DEPLOYMENT,
        messages=messages,
        response_format={"type": "json_object"},
        max_completion_tokens=3000,
    )

    response_text = response.choices[0].message.content
    if (
        getattr(response.choices[0], "finish_reason", None) == "length"
        and not response_text
    ):
        response = client.chat.completions.create(
            model=GPT5_MINI_DEPLOYMENT,
            messages=messages,
            response_format={"type": "json_object"},
            max_completion_tokens=5000,
        )
        response_text = response.choices[0].message.content

    if not response_text:
        print(
            "Deployment analyzer: "
            f"finish_reason={getattr(response.choices[0], 'finish_reason', None)}, "
            f"has_content=False"
        )
        return None

    result = json.loads(response_text)
    if not isinstance(result, dict):
        raise ValueError("The deployment analyzer did not return a JSON object")

    normalized = {key: result.get(key, "" if key not in {"risks", "related_incidents"} else [])
                  for key in EXPECTED_KEYS}
    if normalized["risk_rating"] not in VALID_RISK_RATINGS:
        raise ValueError("risk_rating must be Low, Medium, or High")

    return normalized


if __name__ == "__main__":
    deployment_path = sys.argv[1] if len(sys.argv) > 1 else input("Deployment file: ").strip()
    with open(deployment_path, encoding="utf-8") as deployment_handle:
        analysis = analyze_deployment(deployment_path, deployment_handle.read())
    print(json.dumps(analysis, indent=4))
