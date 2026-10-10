import os
import socket


_configured = False
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex


def _allow_connection(address):
    return isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1", "localhost"}


def _offline_connect(connection, address):
    if not _allow_connection(address):
        raise AssertionError("External network access is forbidden in offline tests")
    return _original_connect(connection, address)


def _offline_connect_ex(connection, address):
    if not _allow_connection(address):
        raise AssertionError("External network access is forbidden in offline tests")
    return _original_connect_ex(connection, address)


def configure_offline_tests():
    global _configured
    if _configured:
        return
    for name in list(os.environ):
        if name.startswith(("AZURE_", "AZDO_", "APPLICATIONINSIGHTS_", "OPENAI_", "EVALAGENT_")) or name in {
            "IDENTITY_ENDPOINT", "IDENTITY_HEADER", "IDENTITY_SERVER_THUMBPRINT", "MSI_ENDPOINT", "MSI_SECRET", "IMDS_ENDPOINT",
        }:
            del os.environ[name]
    os.environ.update({
        "PYTHON_DOTENV_DISABLED": "1",
        "AZURE_OPENAI_API_KEY": "offline-fake-key",
        "AZURE_OPENAI_ENDPOINT": "https://offline.invalid",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "offline-chat",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "offline-embedding",
        "AZURE_OPENAI_GPT5_MINI_DEPLOYMENT": "offline-planner",
        "EVALAGENT_TOOL_PROVIDER": "direct",
    })
    socket.socket.connect = _offline_connect
    socket.socket.connect_ex = _offline_connect_ex
    _configured = True