import io
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock
import unittest

from tests.offline_bootstrap import configure_offline_tests

configure_offline_tests()

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

    def test_missing_document_diagnostics_are_structured_without_document_names(self):
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
            mock.patch.object(search_ai_search, "emit_event") as emit_event,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            results = search_ai_search.search_document("missing-runbook.md")

        self.assertEqual(results, [])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        emit_event.assert_called_once_with(
            "retrieval.document_not_found",
            component="evalagent.retrieval",
            candidate_count=1,
        )

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
            mock.patch.object(search_ai_search, "emit_event") as emit_event,
            redirect_stdout(stdout),
        ):
            results = search_ai_search.search_document("incident-1042.md")

        self.assertEqual(len(results), 1)
        self.assertEqual(stdout.getvalue(), "")
        emit_event.assert_not_called()


class SearchDocumentFilteringTests(unittest.TestCase):
    def _patched_env(self):
        return mock.patch.dict(
            "os.environ",
            {
                "AZURE_SEARCH_ENDPOINT": "https://example.search.windows.net",
                "AZURE_SEARCH_KEY": "fake-key",
                "AZURE_SEARCH_INDEX": "fake-index",
            },
        )

    def _search_document(self, file_name, fake_results):
        fake_client = mock.Mock()
        fake_client.search.return_value = fake_results
        with (
            self._patched_env(),
            mock.patch.object(
                search_ai_search, "SearchClient", return_value=fake_client
            ),
            mock.patch.object(search_ai_search, "emit_event"),
            mock.patch.object(search_ai_search, "tracked_embeddings_create") as embed,
        ):
            results = search_ai_search.search_document(file_name)
        embed.assert_not_called()
        return results, fake_client

    def test_incident_deployment_and_runbook_names_are_filtered_server_side(self):
        documents = (
            "incidents/incident-1042.md",
            "deployments/deployment-1042.json",
            "runbooks/incident-response.md",
        )
        for file_name in documents:
            with self.subTest(file_name=file_name):
                results, fake_client = self._search_document(
                    file_name,
                    [{"file": file_name, "chunk_id": 0, "content": "evidence"}],
                )

                self.assertEqual(len(results), 1)
                fake_client.search.assert_called_once_with(
                    search_text="*",
                    filter=search_ai_search._document_filter(file_name),
                    select=["file", "chunk_id", "content"],
                )
                self.assertIn("search.ismatch(", fake_client.search.call_args.kwargs["filter"])

    def test_windows_paths_case_variants_duplicate_basenames_and_near_matches(self):
        fake_results = [
            {
                "file": "incidents/Incident-1042.MD",
                "chunk_id": 10,
                "content": "later chunk",
            },
            {
                "file": "deployments/incident-1042.md",
                "chunk_id": 3,
                "content": "duplicate basename",
            },
            {
                "file": "incidents/incident-10420.md",
                "chunk_id": 0,
                "content": "near match",
            },
            {
                "file": "incidents/other-incident-1042.md",
                "chunk_id": 1,
                "content": "another near match",
            },
        ]

        results, _ = self._search_document(
            r"C:\workspace\incidents\INCIDENT-1042.MD", fake_results
        )

        self.assertEqual(
            results,
            [
                {
                    "file": "deployments/incident-1042.md",
                    "chunk_id": 3,
                    "content": "duplicate basename",
                },
                {
                    "file": "incidents/Incident-1042.MD",
                    "chunk_id": 10,
                    "content": "later chunk",
                },
            ],
        )

    def test_lucene_and_odata_escaping_preserves_unicode_and_apostrophes(self):
        file_name = r"docs\O'Brien (α)+draft?:v2.md"

        self.assertEqual(
            search_ai_search._document_filter(file_name),
            "search.ismatch("
            "'\"O''Brien \\(α\\)\\+draft\\?\\:v2.md\"', "
            "'file', 'full', 'all')",
        )

    def test_all_result_pages_are_read_and_chunks_are_numerically_sorted(self):
        class PagedResults:
            def __init__(self):
                self.pages_read = 0
                self.pages = [
                    [{"file": "runbooks/incident-response.md", "chunk_id": 12}],
                    [{"file": "runbooks/incident-response.md", "chunk_id": 2}],
                    [{"file": "runbooks/incident-response.md", "chunk_id": 1}],
                ]

            def __iter__(self):
                for page in self.pages:
                    self.pages_read += 1
                    yield from page

        paged_results = PagedResults()
        results, fake_client = self._search_document(
            "incident-response.md", paged_results
        )

        self.assertEqual(paged_results.pages_read, 3)
        self.assertEqual([result["chunk_id"] for result in results], [1, 2, 12])
        self.assertTrue(fake_client.search.called)

    def test_azure_search_errors_propagate(self):
        fake_client = mock.Mock()
        fake_client.search.side_effect = RuntimeError("Azure Search unavailable")
        with (
            self._patched_env(),
            mock.patch.object(
                search_ai_search, "SearchClient", return_value=fake_client
            ),
            self.assertRaisesRegex(RuntimeError, "Azure Search unavailable"),
        ):
            search_ai_search.search_document("incident-1042.md")


if __name__ == "__main__":
    unittest.main()
