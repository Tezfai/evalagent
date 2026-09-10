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

index = faiss.read_index("vector_index.faiss")

with open("documents.pkl", "rb") as f:
    documents = pickle.load(f)

query = input("Question: ")

response = client.embeddings.create(
    model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
    input=query
)

query_vector = np.array(
    [response.data[0].embedding],
    dtype="float32"
)

distances, indices = index.search(query_vector, 3)

print("\nTop Documents:\n")

for idx in indices[0]:
    print(documents[idx]["file"])