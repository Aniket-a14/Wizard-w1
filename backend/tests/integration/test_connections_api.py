"""The connections surface through the real app.

Uses a real SQLite file and the real connector, so what is asserted is the whole
path a user takes -- save, test, discover, import -- rather than a mock of it.
Nothing here reaches the network: SQLite is a file, and no other kind is built.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.api import app
from src.core.session import session_manager


pytest.importorskip("sqlalchemy")


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    session_manager.shutdown()


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "shop.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE orders (id INTEGER, region TEXT, amount REAL)")
    connection.execute("CREATE TABLE customers (id INTEGER, name TEXT)")
    connection.executemany(
        "INSERT INTO orders VALUES (?, ?, ?)",
        [(index, "north" if index % 2 else "south", index * 1.5) for index in range(30)],
    )
    connection.executemany("INSERT INTO customers VALUES (?, ?)", [(index, f"c{index}") for index in range(5)])
    connection.commit()
    connection.close()
    return path


@pytest.fixture
def connected(client, database):
    """A session with one saved SQLite connection."""
    session_id = client.post("/api/session").json()["session_id"]
    headers = {"X-Session-Id": session_id}
    body = client.post(
        "/api/connections",
        json={
            "name": "Shop",
            "kind": "relational",
            "options": {"driver": "sqlite", "database": str(database)},
        },
        headers=headers,
    ).json()
    return headers, body["id"]


def test_a_connection_is_saved_read_only(connected, client) -> None:
    """Every connection starts read-only; nothing about connecting implies writing."""
    headers, connection_id = connected

    body = client.get("/api/connections", headers=headers).json()
    row = next(entry for entry in body["connections"] if entry["id"] == connection_id)

    assert row["read_only"] is True
    assert row["name"] == "Shop"


def test_the_list_route_never_returns_a_secret(client, database) -> None:
    """No response model has a field to put one in, and this pins that."""
    session_id = client.post("/api/session").json()["session_id"]
    headers = {"X-Session-Id": session_id}
    client.post(
        "/api/connections",
        json={
            "name": "Secretive",
            "kind": "relational",
            "options": {"driver": "sqlite", "database": str(database)},
            "secret": "hunter2-super-secret",
        },
        headers=headers,
    )

    body = client.get("/api/connections", headers=headers).text

    assert "hunter2-super-secret" not in body
    assert '"has_secret":true' in body.replace(" ", "")


def test_an_imported_table_is_a_dataset_like_any_other(connected, client) -> None:
    """The whole point of the ingest design: nothing downstream is special-cased."""
    headers, connection_id = connected

    imported = client.post(
        f"/api/connections/{connection_id}/import", json={"target": "orders"}, headers=headers
    ).json()
    session = client.get("/api/datasets", headers=headers).json()

    assert imported["dataset"]["table_key"] == "shop_orders"
    assert imported["dataset"]["origin"] == "Shop"
    assert imported["dataset"]["rows"] == 30
    assert "shop_orders" in {dataset["name"] for dataset in session["datasets"]}


def test_two_tables_from_one_connection_stay_distinct(connected, client) -> None:
    """The `Path(name).stem` collision, asserted through the API.

    Both tables come from the same connection, so a name built with a dot would
    give them the same table key and the second import would erase the first.
    """
    headers, connection_id = connected

    for target in ("orders", "customers"):
        client.post(f"/api/connections/{connection_id}/import", json={"target": target}, headers=headers)
    session = client.get("/api/datasets", headers=headers).json()

    keys = {dataset["table_key"] for dataset in session["datasets"]}
    assert {"shop_orders", "shop_customers"} <= keys


def test_discovery_lists_what_can_be_read(connected, client) -> None:
    headers, connection_id = connected

    body = client.get(f"/api/connections/{connection_id}/schema", headers=headers).json()

    assert {"orders", "customers"} <= {target["name"] for target in body["targets"]}


def test_a_connection_test_reports_instead_of_failing(connected, client) -> None:
    """A diagnostic that raises is useless at the moment it is needed."""
    headers, connection_id = connected

    body = client.post(f"/api/connections/{connection_id}/test", headers=headers).json()

    assert body["ok"] is True


def test_deleting_a_connection_drops_what_it_imported(connected, client) -> None:
    """Rows from a disconnected source must not stay queryable by generated code."""
    headers, connection_id = connected
    client.post(f"/api/connections/{connection_id}/import", json={"target": "orders"}, headers=headers)

    client.delete(f"/api/connections/{connection_id}", headers=headers)
    session = client.get("/api/datasets", headers=headers).json()

    assert session["datasets"] == []


def test_write_back_needs_the_name_typed_back(connected, client) -> None:
    """Enabled once, deliberately -- so it costs more than one click."""
    headers, connection_id = connected

    refused = client.post(
        f"/api/connections/{connection_id}/write-back", json={"enable": True, "confirm": "wrong"}, headers=headers
    )
    accepted = client.post(
        f"/api/connections/{connection_id}/write-back", json={"enable": True, "confirm": "Shop"}, headers=headers
    )

    assert refused.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()["read_only"] is False


def test_a_per_source_policy_can_be_set_on_an_imported_table(connected, client) -> None:
    """Connection-sourced tables reuse the per-source data policy unchanged."""
    headers, connection_id = connected
    client.post(f"/api/connections/{connection_id}/import", json={"target": "orders"}, headers=headers)

    response = client.put("/api/data-mode/dataset/shop_orders", json={"schema_only": True}, headers=headers)

    assert response.status_code == 200
    assert response.json()["per_dataset"]["shop_orders"] is True
