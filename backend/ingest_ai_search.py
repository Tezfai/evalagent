import os
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from dotenv import load_dotenv
from openai import AzureOpenAI

load_dotenv()


def chunk_text(text, chunk_size=500, overlap=100):
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap

    return chunks


def main():
    search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    search_key = os.getenv("AZURE_SEARCH_KEY")
    search_index_name = os.getenv("AZURE_SEARCH_INDEX", "incident-index")

    if not search_endpoint or not search_key:
        raise ValueError(
            "AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY must be set in .env"
        )

    openai_client = AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version="2024-12-01-preview",
    )

    chunks = []
    for file_path in Path("data").rglob("*.md"):
        file_content = file_path.read_text(encoding="utf-8")
        file_content = file_content.replace("\\n", "\n")
        chunks_for_file = chunk_text(file_content)

        for chunk_id, chunk in enumerate(chunks_for_file):
            chunks.append(
                {
                    "file": str(file_path),
                    "chunk_id": chunk_id,
                    "content": chunk,
                }
            )

    if not chunks:
        raise ValueError("No Markdown documents were found in the data folder")

    for chunk in chunks:
        response = openai_client.embeddings.create(
            model=os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT"),
            input=chunk["content"],
        )
        chunk["embedding"] = response.data[0].embedding

    embedding_dimensions = len(chunks[0]["embedding"])
    credential = AzureKeyCredential(search_key)
    index_client = SearchIndexClient(
        endpoint=search_endpoint,
        credential=credential,
    )

    fields = [
        SimpleField(
            name="id",
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
        ),
        SearchableField(
            name="file",
            type=SearchFieldDataType.String,
            filterable=True,
        ),
        SimpleField(
            name="chunk_id",
            type=SearchFieldDataType.Int32,
            filterable=True,
        ),
        SearchableField(
            name="content",
            type=SearchFieldDataType.String,
        ),
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=embedding_dimensions,
            vector_search_profile_name="incident-vector-profile",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(name="incident-hnsw")
        ],
        profiles=[
            VectorSearchProfile(
                name="incident-vector-profile",
                algorithm_configuration_name="incident-hnsw",
            )
        ],
    )

    index = SearchIndex(
        name=search_index_name,
        fields=fields,
        vector_search=vector_search,
    )
    try:
        index_client.delete_index(search_index_name)
    except ResourceNotFoundError:
        pass
    index_client.create_or_update_index(index)

    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=search_index_name,
        credential=credential,
    )

    documents = []
    for chunk in chunks:
        document_id = f"{Path(chunk['file']).stem}-{chunk['chunk_id']}"
        documents.append(
            {
                "id": document_id,
                "file": chunk["file"],
                "chunk_id": chunk["chunk_id"],
                "content": chunk["content"],
                "embedding": chunk["embedding"],
            }
        )

    uploaded_count = 0
    for start in range(0, len(documents), 1000):
        batch = documents[start:start + 1000]
        results = search_client.upload_documents(documents=batch)
        failed = [result for result in results if not result.succeeded]
        if failed:
            raise RuntimeError(
                f"Failed to upload {len(failed)} chunks: {failed}"
            )
        uploaded_count += len(batch)

    print(f"Uploaded {uploaded_count} chunks")


if __name__ == "__main__":
    main()
