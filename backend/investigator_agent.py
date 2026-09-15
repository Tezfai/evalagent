import json
import os

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


SYSTEM_PROMPT = """You are an investigation planning agent.
Analyze the user's question and return only a valid JSON object with these keys:
- investigation_type: one of incident, deployment, architecture, runbook, or general
- incident_id: the incident number as a string, or null if none is mentioned
- deployment_id: the deployment number as a string, or null if none is mentioned
- runbook_reference: the runbook filename or slug as a string, or null if none is mentioned
- search_application_insights: boolean
- application_insights_service_name: the exact service name for telemetry, or null if unknown
- application_insights_start_time: an ISO-8601 UTC start time, or null if not provided
- application_insights_end_time: an ISO-8601 UTC end time, or null if not provided
- search_incident: boolean
- search_deployment: boolean
- search_runbooks: boolean

If the user does not explicitly mention an incident, infer the most appropriate
investigation_type from the question. Set search flags to true when the relevant
source category could help answer the question. Set search_application_insights
to true only when telemetry is relevant and the question or retrieved context
provides a service name. Preserve explicit time bounds when provided, but they
may be null when the caller will supply a default lookback. Do not invent a
service name. Do not include markdown or any explanation outside the JSON
object.
"""


def create_investigation_plan(question):
    """Analyze a question and return an investigation plan as a Python dictionary."""
    if not question or not question.strip():
        raise ValueError("question must not be empty")

    response = client.chat.completions.create(
        model=GPT5_MINI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question.strip()},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=500,
    )

    plan_text = response.choices[0].message.content
    if not plan_text:
        raise ValueError("The investigation planner returned an empty response")

    try:
        return json.loads(plan_text)
    except json.JSONDecodeError:
        cleaned_text = plan_text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]

        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]

        return json.loads(cleaned_text.strip())


if __name__ == "__main__":
    user_question = input("Question: ")
    investigation_plan = create_investigation_plan(user_question)
    print(json.dumps(investigation_plan, indent=4))
