"""Hostile, malformed and degenerate input to the connector surface.

Every case here must produce a clear refusal -- a status code and a sentence the
user can act on -- rather than a crash, a hang, or a driver traceback.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.api import app
from src.core.agent.consent import consent_broker
from src.core.session import session_manager


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    session_manager.shutdown()


@pytest.fixture
def session_headers(client):
    return {"X-Session-Id": client.post("/api/session").json()["session_id"]}


@pytest.fixture
def sqlite_connection(client, session_headers, tmp_path):
    pytest.importorskip("sqlalchemy")
    path = tmp_path / "n.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (x INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()
    return client.post(
        "/api/connections",
        json={"name": "N", "kind": "relational", "options": {"driver": "sqlite", "database": str(path)}},
        headers=session_headers,
    ).json()["id"]


def test_an_unknown_kind_is_refused(client, session_headers) -> None:
    response = client.post(
        "/api/connections", json={"name": "X", "kind": "teleport", "options": {}}, headers=session_headers
    )

    assert response.status_code == 400
    assert "teleport" in response.json()["detail"]


def test_a_nameless_connection_is_refused(client, session_headers) -> None:
    response = client.post(
        "/api/connections", json={"name": "   ", "kind": "relational", "options": {}}, headers=session_headers
    )

    assert response.status_code == 422


def test_a_duplicate_name_is_refused(client, session_headers, sqlite_connection) -> None:
    """Names are how an exported script will look a connection up, so they are unique."""
    response = client.post(
        "/api/connections", json={"name": "N", "kind": "relational", "options": {}}, headers=session_headers
    )

    assert response.status_code == 409


def test_an_unknown_connection_id_is_a_404(client, session_headers) -> None:
    response = client.post("/api/connections/nope/test", headers=session_headers)

    assert response.status_code == 404


def test_importing_a_table_that_does_not_exist_reports_it(client, session_headers, sqlite_connection) -> None:
    response = client.post(
        f"/api/connections/{sqlite_connection}/import", json={"target": "no_such_table"}, headers=session_headers
    )

    assert response.status_code == 400
    assert "no_such_table" in response.json()["detail"]


def test_an_empty_import_target_is_refused(client, session_headers, sqlite_connection) -> None:
    response = client.post(
        f"/api/connections/{sqlite_connection}/import", json={"target": "  "}, headers=session_headers
    )

    assert response.status_code == 422


def test_a_write_to_a_read_only_connection_asks_nobody(client, session_headers, sqlite_connection) -> None:
    """Refused *before* any consent prompt.

    A question whose only permitted answer is no is worse than no question --
    the same rule that keeps the install gate silent when runtime pip is off.
    The assertion on the broker is the part that matters: nothing was asked.
    """
    client.post(f"/api/connections/{sqlite_connection}/import", json={"target": "t"}, headers=session_headers)

    response = client.post(
        f"/api/connections/{sqlite_connection}/write",
        json={"dataset": "n_t", "target": "copy"},
        headers=session_headers,
    )

    assert response.status_code == 403
    assert "read-only" in response.json()["detail"]
    assert not consent_broker._pending, "a refused write must not have asked anything"


def test_write_back_cannot_be_granted_by_a_permission_profile(client, session_headers) -> None:
    """`always_ask` is rejected at the edge, not silently clamped."""
    response = client.post(
        "/api/permissions", json={"profile": "custom", "categories": {"db_write": "allow"}}, headers=session_headers
    )

    assert response.status_code == 400
    assert "per connection" in response.json()["detail"]


def test_a_denied_db_connect_blocks_the_import_even_from_a_click(client, session_headers, sqlite_connection) -> None:
    """`deny` is a real third state, not a stronger flavour of `ask`.

    An explicit click answers an `ask`. It does not answer a `deny` -- otherwise
    setting a category to deny would do nothing at all over HTTP.
    """
    client.post(
        "/api/permissions",
        json={"profile": "custom", "categories": {"db_connect": "deny"}},
        headers=session_headers,
    )

    response = client.post(
        f"/api/connections/{sqlite_connection}/import", json={"target": "t"}, headers=session_headers
    )

    assert response.status_code == 403


def test_writing_a_dataset_the_session_does_not_have_is_a_404(client, session_headers, sqlite_connection) -> None:
    client.post(
        f"/api/connections/{sqlite_connection}/write-back",
        json={"enable": True, "confirm": "N"},
        headers=session_headers,
    )

    response = client.post(
        f"/api/connections/{sqlite_connection}/write",
        json={"dataset": "not_loaded", "target": "copy"},
        headers=session_headers,
    )

    assert response.status_code == 404
