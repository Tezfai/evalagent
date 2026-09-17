import io
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock
import unittest

from backend import search_ai_search


class SearchDocumentStdoutTests(unittest.TestCase):
    """MCP stdio transport requires stdout to carry only protocol traffic."""

    def _patched_env(self):
        return mock.patch.dict(
            "os.environ",
            {
                "AZURE_SEARCH_ENDPOINT": "https://example.search.windows.net",
                "AZURE_SEARCH_KEY": "fake-key",
                "AZURE_SEARCH_INDEX": "fake-index",
            },
        )

    def test_missing_document_diagnostics_do_not_write_to_stdout(self):
        fake_results = [{"file": "incident-1042.md", "chunk_id": 0, "content": "x"}]
        fake_client = mock.Mock()
        fake_client.search.return_value = fake_results

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            self._patched_env(),
            mock.patch.object(
                search_ai_search, "SearchClient", return_value=fake_client
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            results = search_ai_search.search_document("missing-runbook.md")

        self.assertEqual(results, [])
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Candidate files:", stderr.getvalue())
        self.assertIn("incident-1042.md", stderr.getvalue())

    def test_matching_document_writes_no_diagnostics(self):
        fake_results = [{"file": "incident-1042.md", "chunk_id": 0, "content": "x"}]
        fake_client = mock.Mock()
        fake_client.search.return_value = fake_results

        stdout = io.StringIO()
        with (
            self._patched_env(),
            mock.patch.object(
                search_ai_search, "SearchClient", return_value=fake_client
            ),
            redirect_stdout(stdout),
        ):
            results = search_ai_search.search_document("incident-1042.md")

        self.assertEqual(len(results), 1)
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
