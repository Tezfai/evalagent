#!/usr/bin/env python
"""Upload existing local data/ Markdown documents to Azure Blob Storage."""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from backend.blob_storage_client import BlobStorageClient

load_dotenv()


def sync_local_data_to_blob(data_dir="data"):
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"Error: Local directory '{data_dir}' not found.")
        return

    client = BlobStorageClient()
    print(f"Uploading files from '{data_dir}' to storage account '{client.account_name}', container '{client.container_name}'...")

    files = list(data_path.rglob("*.md"))
    if not files:
        print("No Markdown files found to upload.")
        return

    count = 0
    for file_path in sorted(files):
        rel_path = file_path.relative_to(data_path)
        blob_name = str(rel_path).replace("\\", "/")
        client.upload_file(file_path, blob_name, overwrite=True)
        print(f"  • Uploaded: {blob_name}")
        count += 1

    print(f"\nSuccessfully uploaded {count} documents to Azure Blob Storage.")


if __name__ == "__main__":
    sync_local_data_to_blob()
