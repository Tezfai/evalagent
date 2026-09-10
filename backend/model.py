from openai import AzureOpenAI
from dotenv import load_dotenv
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
subscription_key = os.getenv("AZURE_OPENAI_API_KEY")
api_version = "2024-12-01-preview"

client = AzureOpenAI(
    api_version=api_version,
    azure_endpoint=endpoint,
    api_key=subscription_key,
)

response = client.chat.completions.create(
    messages=[
        {
            "role": "system",
            "content": "You are a helpful assistant.",
        },
        {
            "role": "user",
            "content": "what is 1+1?",
        }
    ],
    max_completion_tokens=1000,
    model=deployment
)

print(response.choices[0].message.content)