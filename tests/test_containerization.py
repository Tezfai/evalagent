import ast
import fnmatch
import json
import shlex
import unittest
from importlib import metadata
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from tests.offline_bootstrap import configure_offline_tests

configure_offline_tests()

ROOT = Path(__file__).resolve().parents[1]


class ContainerizationTests(unittest.TestCase):
    def setUp(self):
        self.dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.instructions = self.dockerfile.replace("\\\n", " ").splitlines()
        self.allowlist = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    def included(self, path):
        included = False
        for pattern in self.allowlist:
            if pattern.startswith("!") and fnmatch.fnmatchcase(path, pattern[1:]):
                included = True
            elif fnmatch.fnmatchcase(path, pattern):
                included = False
        return included

    def test_runtime_copies_exist_and_are_allowed(self):
        copied = []
        for line in self.instructions:
            if line.startswith("COPY "):
                copied.extend(shlex.split(line)[1:-1])
        for path in copied:
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())
                self.assertTrue(self.included(path))
        for path in ("app.py", "frontend.py", "assets/dashboard.css", ".streamlit/config.toml", "backend/evalagent_mcp_server.py", "backend/evalagent_mcp_client.py"):
            self.assertIn(path, copied)
        for path in copied:
            if not path.endswith(".py"):
                continue
            tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend."):
                    self.assertIn(node.module.replace(".", "/") + ".py", copied)

    def test_context_excludes_secrets_caches_corpus_and_legacy_files(self):
        self.assertEqual(self.allowlist[0], "**")
        for path in (".env", ".env.docker", ".env.example", ".azure/accessTokens.json", ".azure/msal_token_cache.json", ".git/config", ".venv/bin/python", "venv/Scripts/python.exe", "backend/__pycache__/model.pyc", ".pytest_cache/cache", "tests/eval_cases.json", "data_backup/incidents/incident-1042.md", "documents.pkl", "vector_index.faiss", "scripts/upload_data_to_blob.py", "backend/ingest_ai_search.py", "backend/model.py", "backend/rag.py", "backend/search.py", "backend/private_config.json"):
            with self.subTest(path=path):
                self.assertFalse(self.included(path))

    def test_non_root_exec_startup_and_healthcheck(self):
        self.assertIn("@sha256:", self.instructions[0])
        self.assertIn("USER 10001:10001", self.instructions)
        self.assertIn("EXPOSE 8501", self.instructions)
        self.assertIn("STOPSIGNAL SIGTERM", self.instructions)
        command = json.loads(next(line[4:] for line in self.instructions if line.startswith("CMD [")))
        self.assertEqual(command[:5], ["python", "-m", "streamlit", "run", "app.py"])
        self.assertIn("--server.address=0.0.0.0", command)
        self.assertIn("--server.port=8501", command)
        self.assertIn("--server.fileWatcherType=none", command)
        self.assertIn("http://127.0.0.1:8501/_stcore/health", self.dockerfile)
        self.assertIn("PYTHON_DOTENV_DISABLED=1", self.dockerfile)
        self.assertIn("--only-binary=:all:", self.dockerfile)

    def test_lock_covers_linux_python_runtime_without_unrelated_packages(self):
        lock = {}
        for line in (ROOT / "requirements.lock").read_text().splitlines():
            if line.strip():
                requirement = Requirement(line)
                self.assertEqual(len(requirement.specifier), 1)
                self.assertEqual(next(iter(requirement.specifier)).operator, "==")
                lock[canonicalize_name(requirement.name)] = requirement
        environment = default_environment()
        environment.update({"sys_platform": "linux", "os_name": "posix", "platform_system": "Linux", "python_version": "3.13", "python_full_version": "3.13.16", "extra": ""})
        for name, requirement in lock.items():
            version = metadata.version(name)
            self.assertIn(version, requirement.specifier)
            python_specifier = metadata.metadata(name).get("Requires-Python")
            if python_specifier:
                self.assertIn("3.13.16", SpecifierSet(python_specifier))
            for value in metadata.requires(name) or []:
                dependency = Requirement(value)
                if dependency.marker is None or dependency.marker.evaluate(environment):
                    target = canonicalize_name(dependency.name)
                    self.assertIn(target, lock)
                    self.assertIn(metadata.version(target), dependency.specifier)
        for name in ("faiss-cpu", "opencv-python", "pywin32", "azure-monitor-opentelemetry"):
            self.assertNotIn(name, lock)
        for line in (ROOT / "requirements.txt").read_text().splitlines():
            if line.strip():
                requirement = Requirement(line)
                self.assertEqual(requirement.specifier, lock[canonicalize_name(requirement.name)].specifier)