import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest

from azure.core.exceptions import ResourceNotFoundError

from tests.offline_bootstrap import configure_offline_tests

configure_offline_tests()

from backend import ingest_ai_search, restore_search_index


class RestoreSearchIndexTests(unittest.TestCase):
    def setUp(self):
        self.environment = mock.patch.dict(
            os.environ,
            {
                "AZURE_SEARCH_ENDPOINT": "https://example.search.windows.net",
                "AZURE_SEARCH_KEY": "test-admin-key",
                "AZURE_SEARCH_INDEX": "test-index",
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
                "AZURE_OPENAI_API_KEY": "test-openai-key",
                "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "test-embedding-deployment",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_existing_index_is_refused_without_calling_ingestion(self):
        index_client = mock.Mock()
        index_client.get_index.return_value = object()

        with (
            mock.patch.object(
                restore_search_index, "SearchIndexClient", return_value=index_client
            ),
            mock.patch.object(restore_search_index, "ingest_from_blob") as ingest,
            self.assertRaisesRegex(RuntimeError, "refusing to replace"),
        ):
            restore_search_index.restore_index()

        index_client.get_index.assert_called_once_with("test-index")
        ingest.assert_not_called()

    def test_missing_index_delegates_to_existing_blob_pipeline_in_safe_mode(self):
        index_client = mock.Mock()
        index_client.get_index.side_effect = ResourceNotFoundError("not found")

        with (
            mock.patch.object(
                restore_search_index, "SearchIndexClient", return_value=index_client
            ),
            mock.patch.object(
                restore_search_index,
                "ingest_from_blob",
                return_value="restored",
            ) as ingest,
        ):
            result = restore_search_index.restore_index()

        self.assertEqual(result, "restored")
        ingest.assert_called_once_with(require_empty_index=True)

    def test_safe_ingestion_mode_uses_create_only_and_never_deletes(self):
        index_client = mock.Mock()
        search_client = mock.Mock()
        search_client.upload_documents.return_value = [
            SimpleNamespace(succeeded=True)
        ]
        openai_client = mock.Mock()
        openai_client.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2])]
        )
        blob_client = mock.Mock()
        blob_client.download_markdown_documents.return_value = [
            {"file": "incidents/example.md", "content": "incident evidence"}
        ]

        with (
            mock.patch.object(ingest_ai_search, "AzureOpenAI", return_value=openai_client),
            mock.patch.object(ingest_ai_search, "BlobStorageClient", return_value=blob_client),
            mock.patch.object(ingest_ai_search, "SearchIndexClient", return_value=index_client),
            mock.patch.object(ingest_ai_search, "SearchClient", return_value=search_client),
        ):
            ingest_ai_search.main(require_empty_index=True)

        index_client.create_index.assert_called_once()
        index_client.create_or_update_index.assert_not_called()
        index_client.delete_index.assert_not_called()
        search_client.upload_documents.assert_called_once()
        openai_client.embeddings.create.assert_called_once_with(
            model="test-embedding-deployment",
            input="incident evidence",
        )

    def test_tracked_markdown_backup_is_nonempty_utf8_and_basename_unique(self):
        backup_root = Path(__file__).resolve().parents[1] / "data_backup"
        files = sorted(backup_root.rglob("*.md"))

        self.assertTrue(files)
        for path in files:
            self.assertGreater(path.stat().st_size, 0, path.as_posix())
            path.read_text(encoding="utf-8")
        basenames = [path.name.casefold() for path in files]
        self.assertEqual(len(basenames), len(set(basenames)))


if __name__ == "__main__":
    unittest.main()
