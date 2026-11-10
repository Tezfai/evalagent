"""Guarded entry point for restoring Azure AI Search from Blob Markdown."""

import os

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv

from .ingest_ai_search import main as ingest_from_blob


def restore_index():
    load_dotenv()
    required = (
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_KEY",
        "AZURE_SEARCH_INDEX",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    index_name = os.environ["AZURE_SEARCH_INDEX"]
    index_client = SearchIndexClient(
        endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
        credential=AzureKeyCredential(os.environ["AZURE_SEARCH_KEY"]),
    )
    try:
        index_client.get_index(index_name)
    except ResourceNotFoundError:
        pass
    else:
        raise RuntimeError(
            f"Index '{index_name}' already exists; refusing to replace it."
        )

    return ingest_from_blob(require_empty_index=True)


def main():
    restore_index()


if __name__ == "__main__":
    main()
