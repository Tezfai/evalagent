import os
import pickle
import faiss
import numpy as np

from openai import AzureOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version="2024-12-01-preview"
)

documents = []

for root, _, files in os.walk("data"):
    for file in files:
        if file.endswith(".md"):
            path = os.path.join(root, file)

            with open(path, "r", encoding="utf-8") as f:
                text = f.read()

            documents.append({
                "file": path,
                "text": text
            })

vectors = []

for doc in documents:
    response = client.embeddings.create(
        model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        input=doc["text"]
    )

    embedding = response.data[0].embedding

    vectors.append(embedding)

dimension = len(vectors[0])

index = faiss.IndexFlatL2(dimension)

index.add(np.array(vectors).astype("float32"))

faiss.write_index(index, "vector_index.faiss")

with open("documents.pkl", "wb") as f:
    pickle.dump(documents, f)

print(f"Indexed {len(documents)} documents")