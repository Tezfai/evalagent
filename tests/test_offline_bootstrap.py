import os
import socket
import unittest

from tests.offline_bootstrap import configure_offline_tests

configure_offline_tests()


class OfflineBootstrapTests(unittest.TestCase):
    def test_only_test_configuration_is_available(self):
        self.assertEqual(os.environ["PYTHON_DOTENV_DISABLED"], "1")
        self.assertEqual(os.environ["AZURE_OPENAI_API_KEY"], "offline-fake-key")
        self.assertEqual(os.environ["AZURE_OPENAI_ENDPOINT"], "https://offline.invalid")
        self.assertNotIn("AZDO_PAT", os.environ)
        self.assertNotIn("AZURE_CLIENT_SECRET", os.environ)

    def test_external_network_attempts_are_rejected(self):
        with socket.socket() as connection:
            with self.assertRaisesRegex(AssertionError, "External network access"):
                connection.connect(("offline.invalid", 443))
            with self.assertRaisesRegex(AssertionError, "External network access"):
                connection.connect_ex(("offline.invalid", 443))