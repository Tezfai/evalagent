"""Azure Blob Storage client for managing and reading markdown documents."""

import os
from dotenv import load_dotenv

try:
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient
except ImportError:
    DefaultAzureCredential = None
    BlobServiceClient = None

load_dotenv()


class BlobStorageClient:
    """Client to list, download, and upload documents in Azure Blob Storage."""

    def __init__(
        self,
        account_name=None,
        container_name=None,
        credential=None,
        service_client=None,
    ):
        self.account_name = account_name or os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        self.container_name = (
            container_name
            or os.getenv("AZURE_STORAGE_CONTAINER_NAME", "evalagent-documents")
        )
        self._credential = credential
        self._service_client = service_client

    def get_container_client(self):
        if self._service_client is not None:
            return self._service_client.get_container_client(self.container_name)

        if not self.account_name:
            raise ValueError(
                "AZURE_STORAGE_ACCOUNT_NAME must be set in .env or passed to constructor"
            )

        if BlobServiceClient is None:
            raise RuntimeError("azure-storage-blob is not installed.")

        account_url = f"https://{self.account_name}.blob.core.windows.net"
        credential = self._credential
        if credential is None:
            if DefaultAzureCredential is None:
                raise RuntimeError("azure-identity is not installed.")
            credential = DefaultAzureCredential()

        service_client = BlobServiceClient(account_url=account_url, credential=credential)
        return service_client.get_container_client(self.container_name)

    def download_markdown_documents(self):
        """List and download all Markdown documents from the container."""
        container_client = self.get_container_client()
        documents = []
        for blob in container_client.list_blobs():
            if blob.name.endswith(".md"):
                blob_client = container_client.get_blob_client(blob.name)
                content = blob_client.download_blob().readall().decode("utf-8")
                content = content.replace("\\n", "\n")
                documents.append({"file": blob.name, "content": content})
        return documents

    def upload_file(self, local_file_path, blob_name, overwrite=True):
        """Upload a local file to the container."""
        container_client = self.get_container_client()
        with open(local_file_path, "rb") as data:
            blob_client = container_client.get_blob_client(blob_name)
            blob_client.upload_blob(data, overwrite=overwrite)
