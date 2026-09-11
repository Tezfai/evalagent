import os
import pickle
import faiss
import numpy as np

from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version="2024-12-01-preview"
)

def ask_question(question):
    index = faiss.read_index("vector_index.faiss")

    with open("documents.pkl", "rb") as f:
        documents = pickle.load(f)

    response = client.embeddings.create(
        model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        input=question
    )

    query_vector = np.array(
        [response.data[0].embedding],
        dtype="float32"
    )

    distances, indices = index.search(query_vector, 3)

    context = ""

    sources = []

    for idx in indices[0]:
        context += f"\n--- SOURCE: {documents[idx]['file']} ---\n"
        context += documents[idx]["text"]
        context += "\n\n"

        sources.append(
            documents[idx]["file"]
        )

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

    print("\nAnswer:\n")
    print(answer)

    print("\nSources:\n")

    for source in sources:
        print(source)
