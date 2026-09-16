import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from backend.blob_storage_client import BlobStorageClient


class FakeDownloadStream:
    def __init__(self, content: bytes):
        self._content = content

    def readall(self) -> bytes:
        return self._content


class FakeBlobClient:
    def __init__(self, storage, name):
        self.storage = storage
        self.name = name

    def upload_blob(self, data, overwrite=False):
        if hasattr(data, "read"):
            data = data.read()
        self.storage[self.name] = data

    def download_blob(self):
        return FakeDownloadStream(self.storage[self.name])


class FakeContainerClient:
    def __init__(self, name="evalagent-documents"):
        self.name = name
        self.storage = {}

    def get_blob_client(self, blob_name):
        return FakeBlobClient(self.storage, blob_name)

    def list_blobs(self):
        return [SimpleNamespace(name=name) for name in self.storage.keys()]


class FakeBlobServiceClient:
    def __init__(self):
        self.containers = {}

    def get_container_client(self, name):
        if name not in self.containers:
            self.containers[name] = FakeContainerClient(name)
        return self.containers[name]


class BlobStorageTests(unittest.TestCase):
    def setUp(self):
        self.fake_service = FakeBlobServiceClient()
        self.client = BlobStorageClient(
            account_name="incidentxagentstorage",
            container_name="evalagent-documents",
            service_client=self.fake_service,
        )

    def test_upload_and_download_markdown_documents(self):
        fake_container = self.fake_service.get_container_client("evalagent-documents")
        fake_container.storage["incidents/incident-1042.md"] = b"# Incident 1042\nCheckout latency"
        fake_container.storage["deployments/deployment-882.md"] = b"# Deployment 882\nRelease notes"
        fake_container.storage["ignore.txt"] = b"not a markdown file"

        docs = self.client.download_markdown_documents()
        self.assertEqual(len(docs), 2)
        doc_files = [d["file"] for d in docs]
        self.assertIn("incidents/incident-1042.md", doc_files)
        self.assertIn("deployments/deployment-882.md", doc_files)
        self.assertNotIn("ignore.txt", doc_files)

    def test_credential_initialization_with_default_azure_credential(self):
        with patch("backend.blob_storage_client.DefaultAzureCredential") as mock_cred, \
             patch("backend.blob_storage_client.BlobServiceClient") as mock_service_cls:
            client = BlobStorageClient(account_name="incidentxagentstorage")
            client.get_container_client()
            mock_cred.assert_called_once()
            mock_service_cls.assert_called_once_with(
                account_url="https://incidentxagentstorage.blob.core.windows.net",
                credential=mock_cred.return_value,
            )


if __name__ == "__main__":
    unittest.main()
