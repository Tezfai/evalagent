import os

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()


def search_chunks(query):
    search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    search_key = os.getenv("AZURE_SEARCH_KEY")
    search_index_name = os.getenv("AZURE_SEARCH_INDEX")

    required_settings = {
        "AZURE_SEARCH_ENDPOINT": search_endpoint,
        "AZURE_SEARCH_KEY": search_key,
        "AZURE_SEARCH_INDEX": search_index_name,
    }
    missing_settings = [
        name for name, value in required_settings.items() if not value
    ]
    if missing_settings:
        raise ValueError(
            "Missing required environment variables: "
            + ", ".join(missing_settings)
        )

    openai_client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version="2024-12-01-preview",
    )

    embedding_response = openai_client.embeddings.create(
        model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
        input=query,
    )
    query_embedding = embedding_response.data[0].embedding

    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=search_index_name,
        credential=AzureKeyCredential(search_key),
    )

    vector_query = VectorizedQuery(
        vector=query_embedding,
        k_nearest_neighbors=5,
        fields="embedding",
    )

    results = search_client.search(
        search_text=None,
        vector_queries=[vector_query],
        select=["file", "chunk_id", "content"],
        top=5,
    )

    return [
        {
            "file": result.get("file"),
            "chunk_id": result.get("chunk_id"),
            "content": result.get("content", ""),
        }
        for result in results
    ]


def search_document(file_name):
    """Retrieve all chunks for one document by searching its file field."""
    search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    search_key = os.getenv("AZURE_SEARCH_KEY")
    search_index_name = os.getenv("AZURE_SEARCH_INDEX")

    required_settings = {
        "AZURE_SEARCH_ENDPOINT": search_endpoint,
        "AZURE_SEARCH_KEY": search_key,
        "AZURE_SEARCH_INDEX": search_index_name,
    }
    missing_settings = [
        name for name, value in required_settings.items() if not value
    ]
    if missing_settings:
        raise ValueError(
            "Missing required environment variables: "
            + ", ".join(missing_settings)
        )

    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=search_index_name,
        credential=AzureKeyCredential(search_key),
    )
    requested_file = os.path.basename(file_name).lower()
    results = search_client.search(
        search_text="*",
        select=["file", "chunk_id", "content"],
    )
    results = list(results)
    matching_results = [
        result
        for result in results
        if os.path.basename(str(result.get("file", ""))).lower()
        == requested_file
    ]
    if not matching_results:
        print("Candidate files:")
        for result in results:
            print(result.get("file"))
    results = sorted(
        matching_results,
        key=lambda result: int(result.get("chunk_id", 0)),
    )

    return [
        {
            "file": result.get("file"),
            "chunk_id": result.get("chunk_id"),
            "content": result.get("content", ""),
        }
        for result in results
    ]


if __name__ == "__main__":
    query = input("Question: ")
    results = search_chunks(query)

    print("\nResults:\n")
    for result in results:
        preview = " ".join(result["content"].split())[:200]
        print(f"File: {result['file']}")
        print(f"Chunk ID: {result['chunk_id']}")
        print(f"Content preview: {preview}")
        print()
