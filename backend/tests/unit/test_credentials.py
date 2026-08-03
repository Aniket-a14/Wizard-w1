"""Local credential storage.

Two things must hold: a key round-trips, and a key never leaves the process in
any form but a mask. The permission guarantee is asserted where it can be —
POSIX mode bits — and the Windows path is exercised for "did not lock the owner
out", which is how it failed the first time it was written.
"""

from __future__ import annotations

import json
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.api import app
from src.config import settings
from src.core.credentials import CredentialStore
from src.core.session import session_manager


@pytest.fixture
def store(tmp_path: Path) -> CredentialStore:
    return CredentialStore(path=tmp_path / "credentials.json")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    session_manager.shutdown()


def test_a_key_round_trips(store: CredentialStore) -> None:
    assert store.set("anthropic", "sk-ant-secret-value")
    assert store.get("anthropic") == "sk-ant-secret-value"
    assert store.has("anthropic")


def test_the_provider_name_is_case_insensitive(store: CredentialStore) -> None:
    store.set("Anthropic", "sk-ant-x")
    assert store.get("anthropic") == "sk-ant-x"


def test_the_hint_masks_everything_but_the_tail(store: CredentialStore) -> None:
    store.set("openai", "sk-proj-abcdefghij9876")
    hint = store.hint("openai")
    assert hint == "…9876"
    assert "abcdefghij" not in hint


def test_no_key_means_no_hint(store: CredentialStore) -> None:
    assert store.hint("openai") == ""


def test_a_key_can_be_removed(store: CredentialStore) -> None:
    store.set("openai", "sk-1234")
    assert store.delete("openai")
    assert not store.has("openai")
    assert not store.delete("openai")


def test_an_empty_key_is_not_stored(store: CredentialStore) -> None:
    assert not store.set("openai", "   ")
    assert not store.has("openai")


def test_the_file_survives_a_new_store_over_the_same_path(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    CredentialStore(path=path).set("anthropic", "sk-ant-persisted")
    assert CredentialStore(path=path).get("anthropic") == "sk-ant-persisted"


def test_a_corrupt_file_reads_as_no_keys_rather_than_raising(tmp_path: Path) -> None:
    """A question must never fail because the credentials file is malformed."""
    path = tmp_path / "credentials.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert CredentialStore(path=path).get("anthropic") == ""


def test_an_unexpected_shape_reads_as_no_keys(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"api_keys": ["not", "a", "mapping"]}), encoding="utf-8")
    assert CredentialStore(path=path).providers_with_keys() == []


def test_the_file_stays_writable_after_being_restricted(store: CredentialStore) -> None:
    """The Windows ACL path granted access to `%USERNAME%`, which is an ordinary
    environment variable and on one machine named a different account entirely —
    locking the owner out of their own file on the second write."""
    assert store.set("anthropic", "sk-ant-first")
    assert store.set("anthropic", "sk-ant-second")
    assert store.get("anthropic") == "sk-ant-second"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits do not describe Windows ACLs")
def test_the_file_is_readable_only_by_its_owner(store: CredentialStore) -> None:
    store.set("anthropic", "sk-ant-x")
    mode = stat.S_IMODE(store.path.stat().st_mode)
    assert mode == 0o600


# --------------------------------------------------------------------------- #
# Resolution order
# --------------------------------------------------------------------------- #
def test_a_configured_key_beats_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment wins, so a container or CI run behaves as it was configured."""
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "from-the-environment")
    assert settings.provider_api_key("anthropic") == "from-the-environment"


def test_the_store_is_consulted_when_nothing_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core import credentials as credentials_module

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(credentials_module.credential_store, "_cache", {"anthropic": "from-the-store"})
    assert settings.provider_api_key("anthropic") == "from-the-store"


def test_a_provider_needing_a_key_is_unconfigured_without_one(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core import credentials as credentials_module

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(credentials_module.credential_store, "_cache", {})
    assert settings.provider_is_configured("anthropic") is False
    # A local daemon needs no key and is configured as soon as it has a URL.
    assert settings.provider_is_configured("ollama") is True


# --------------------------------------------------------------------------- #
# Nothing leaks
# --------------------------------------------------------------------------- #
def test_no_route_returns_a_stored_key(client) -> None:
    secret = "sk-ant-do-not-leak-this-0000"
    response = client.put("/api/providers/anthropic/credentials", json={"api_key": secret})
    assert response.status_code == 200
    assert secret not in response.text

    for path in ("/api/providers", "/api/models?provider=anthropic", "/api/config", "/api/session"):
        assert secret not in client.get(path).text, path

    client.delete("/api/providers/anthropic/credentials")


def test_an_unknown_provider_cannot_be_given_a_key(client) -> None:
    assert client.put("/api/providers/not-a-backend/credentials", json={"api_key": "x"}).status_code == 404
