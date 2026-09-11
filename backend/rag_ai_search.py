import os

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version="2024-12-01-preview"
)


def ask_question(question):
    search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    search_key = os.getenv("AZURE_SEARCH_KEY")
    search_index_name = os.getenv("AZURE_SEARCH_INDEX")

    response = client.embeddings.create(
        model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        input=question
    )

    vector_query = VectorizedQuery(
        vector=response.data[0].embedding,
        k_nearest_neighbors=5,
        fields="embedding"
    )

    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=search_index_name,
        credential=AzureKeyCredential(search_key)
    )

    results = search_client.search(
        search_text=None,
        vector_queries=[vector_query],
        select=["file", "chunk_id", "content"],
        top=5
    )

    context = ""
    sources = []

    for result in results:
        source = result.get("file")
        content = result.get("content", "")

        context += f"\n--- SOURCE: {source} ---\n"
        context += content
        context += "\n\n"

        sources.append(source)

    answer = client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"),
        messages=[
            {
                "role": "system",
                "content": """You are an incident investigation assistant.

Answer using the provided context.

If the context contains enough information,
provide a helpful answer.

If information is missing,
state clearly what is missing.

Reference relevant source information when possible.
"""
            },
            {
                "role": "user",
                "content": f"""
Context:

{context}

Question:

{question}
"""
            }
        ],
        max_completion_tokens=3000
    )

    answer_text = answer.choices[0].message.content

    return answer_text, sources


if __name__ == "__main__":
    question = input("Question: ")
    answer, sources = ask_question(question)

    print(answer)

    for source in sources:
        print(source)
