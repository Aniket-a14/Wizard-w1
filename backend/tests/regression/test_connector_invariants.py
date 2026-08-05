"""Invariants of the connector layer that would erode quietly if unpinned.

Each of these is a property the design depends on and which nothing else would
notice losing. They are not tests of whether connectors work -- that is the
integration suite -- but of the boundaries around them.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.api import app
from src.config import settings
from src.core.connectors import ConnectionSpec
from src.core.connectors.store import ConnectionStore
from src.core.data_mode import DataPolicy
from src.core.session import session_manager


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    session_manager.shutdown()


def test_generated_code_is_never_given_a_connection_string(client, tmp_path) -> None:
    """The sandbox network seal survives this milestone.

    Connections are read in the *parent* and materialised to Feather; the child
    that runs generated code has no driver, no DSN and no outbound network. If a
    connection string ever reached the prompt or the workspace, the deny-by-
    default network policy would still hold but would no longer mean anything,
    because the code would have been handed the credentials directly.
    """
    pytest.importorskip("sqlalchemy")
    database = tmp_path / "seal.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE t (x INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()

    headers = {"X-Session-Id": client.post("/api/session").json()["session_id"]}
    created = client.post(
        "/api/connections",
        json={
            "name": "Sealed",
            "kind": "relational",
            "options": {"driver": "sqlite", "database": str(database)},
            "secret": "a-real-password",
        },
        headers=headers,
    ).json()
    imported = client.post(f"/api/connections/{created['id']}/import", json={"target": "t"}, headers=headers)
    assert imported.status_code == 200, imported.text

    session = session_manager.get_or_create(headers["X-Session-Id"])
    workspace_text = "".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in session.workspace.rglob("*")
        if path.is_file() and path.suffix in {".py", ".csv", ".json"}
    )

    assert "a-real-password" not in workspace_text
    assert str(database) not in workspace_text
    assert session.inspect() and "a-real-password" not in session.inspect()


def test_a_connection_policy_covers_tables_imported_later() -> None:
    """The reason `origin` exists.

    A per-source decision has to apply to the whole source. Keyed only by table
    name, a policy set on a connection would silently fail to cover the next
    table imported from it -- the case where getting it wrong is invisible.
    """
    policy = DataPolicy(schema_only=False)
    policy.set_for("Warehouse", True)

    assert policy.schema_only_for("warehouse_orders", origin="Warehouse") is True
    assert policy.schema_only_for("warehouse_customers", origin="Warehouse") is True


def test_a_tables_own_policy_outranks_its_connections() -> None:
    policy = DataPolicy(schema_only=False)
    policy.set_for("Warehouse", True)
    policy.set_for("warehouse_public", False)

    assert policy.schema_only_for("warehouse_public", origin="Warehouse") is False


def test_an_upload_cannot_inherit_a_connection_policy_by_name() -> None:
    """Why `origin` is a separate argument rather than a prefix test on the name.

    A prefix match looks equivalent and would give an uploaded `sales.csv` the
    policy set for a connection called `sales`.
    """
    policy = DataPolicy(schema_only=False)
    policy.set_for("sales", True)

    assert policy.schema_only_for("sales.csv", origin="") is False


def test_the_connections_file_is_not_inside_the_checkout(tmp_path) -> None:
    """Configuration belongs to the person, not the clone.

    A user who deletes `backend/data/` to clear a stale cache must not lose
    their saved connections with it -- the same rule the credential store
    follows, and the reason neither lives in `wizard.db`.
    """
    assert "connections.json" in str(ConnectionStore().path)
    assert str(settings.DATA_DIR) not in str(ConnectionStore().path)


def test_a_saved_connection_survives_a_reload_but_stays_read_only(tmp_path) -> None:
    """Connections persist; consent does not. The two halves of the split."""
    path = tmp_path / "connections.json"
    ConnectionStore(path=path).save(ConnectionSpec(name="W", kind="relational"), secret="")

    reopened = ConnectionStore(path=path).list()

    assert [spec.name for spec in reopened] == ["W"]
    assert reopened[0].read_only is True


def test_the_stored_file_shape_is_stable(tmp_path) -> None:
    """Pinned because Milestone 8's CLI and Milestone 9's export both read it."""
    path = tmp_path / "connections.json"
    ConnectionStore(path=path).save(ConnectionSpec(name="W", kind="relational", options={"host": "h"}), secret="")

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert set(payload) == {"connections"}
    assert set(payload["connections"][0]) == {"id", "name", "kind", "options", "read_only", "created_at"}


def test_a_pasted_dsn_password_reaches_neither_the_file_nor_any_response(client) -> None:
    """The most common configuration path is the one that leaked.

    A canonical Postgres DSN carries the password inline. Left whole it lands in
    `spec.options`, which is persisted and returned verbatim -- making
    `ConnectionSpec.to_dict`'s "there is no secret in it" false exactly where it
    matters most. Asserted through the API rather than the helper, because the
    helper being right is not the same as it being called.
    """
    headers = {"X-Session-Id": client.post("/api/session").json()["session_id"]}
    client.post(
        "/api/connections",
        json={
            "name": "Leaky",
            "kind": "relational",
            "options": {"dsn": "postgresql://admin:SUPERSECRET@db.internal:5432/prod"},
        },
        headers=headers,
    )

    listing = client.get("/api/connections", headers=headers).text
    on_disk = ConnectionStore().path.read_text(encoding="utf-8")

    assert "SUPERSECRET" not in listing
    assert "SUPERSECRET" not in on_disk
    # The rest of the DSN is still there -- the password was lifted out, not the
    # whole connection string discarded.
    assert "db.internal" in listing


def test_local_only_refuses_a_connection_that_leaves_the_machine(client, tmp_path) -> None:
    """The mode outranks the profile, and its promise has to be literally true.

    `local-only` describes itself as "Nothing is sent anywhere". Before this,
    a session in that mode could still pull rows from a hosted warehouse.
    """
    pytest.importorskip("sqlalchemy")
    headers = {"X-Session-Id": client.post("/api/session").json()["session_id"]}
    remote = client.post(
        "/api/connections",
        json={"name": "Remote", "kind": "relational", "options": {"driver": "postgresql", "host": "db.example.com"}},
        headers=headers,
    ).json()["id"]
    client.post("/api/data-mode", json={"mode": "local-only"}, headers=headers)

    response = client.post(f"/api/connections/{remote}/import", json={"target": "t"}, headers=headers)

    assert response.status_code == 403
    assert "local-only" in response.json()["detail"]


def test_local_only_still_allows_a_connection_that_does_not(client, tmp_path) -> None:
    """The refusal has to discriminate, or it is just a switch that breaks the feature."""
    pytest.importorskip("sqlalchemy")
    database = tmp_path / "local.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE t (x INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()

    headers = {"X-Session-Id": client.post("/api/session").json()["session_id"]}
    local = client.post(
        "/api/connections",
        json={"name": "Local", "kind": "relational", "options": {"driver": "sqlite", "database": str(database)}},
        headers=headers,
    ).json()["id"]
    client.post("/api/data-mode", json={"mode": "local-only"}, headers=headers)

    response = client.post(f"/api/connections/{local}/import", json={"target": "t"}, headers=headers)

    assert response.status_code == 200


def test_a_truncated_import_does_not_invent_a_total(client, tmp_path, monkeypatch) -> None:
    """ "Report, don't invent" applied to the row count.

    The source's real size is never queried, and `assumptions_from_profile`
    renders `original_rows` as an exact total ("down-sampled to N of M"). A
    plausible figure here becomes an invented one on screen, which is the
    precise thing the trust layer exists to prevent.
    """
    pytest.importorskip("sqlalchemy")
    monkeypatch.setattr(settings, "CONNECTOR_MAX_ROWS", 5)
    database = tmp_path / "big.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE wide (x INTEGER)")
    connection.executemany("INSERT INTO wide VALUES (?)", [(index,) for index in range(50)])
    connection.commit()
    connection.close()

    headers = {"X-Session-Id": client.post("/api/session").json()["session_id"]}
    created = client.post(
        "/api/connections",
        json={"name": "Big", "kind": "relational", "options": {"driver": "sqlite", "database": str(database)}},
        headers=headers,
    ).json()["id"]
    body = client.post(f"/api/connections/{created}/import", json={"target": "wide"}, headers=headers).json()

    assert body["truncated"] is True
    assert body["dataset"]["rows"] == 5
    assert body["dataset"]["profile"]["original_rows"] is None, "the source was never counted"
    assert "1,000,001" not in body["message"]
    assert "CONNECTOR_MAX_ROWS" in body["message"]


def test_an_import_is_bounded(client) -> None:
    """An upload is capped by MAX_UPLOAD_BYTES before anything reads it; a table is not.

    Without a ceiling the first honest question asked of a real warehouse is an
    OOM in the API process, which is the one process that is not sandboxed.
    """
    assert settings.CONNECTOR_MAX_ROWS > 0
    assert settings.CONNECTOR_MAX_OBJECT_BYTES > 0
