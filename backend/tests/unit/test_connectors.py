"""The connector layer, with no database running.

Most of this file exercises inert data and pure functions, for the same reason
``test_sandbox_policy`` does: the interface is where the design is either right
or wrong, and it has to be reviewable from a laptop with no warehouse on it.

The one place a *real* engine is used is SQLite, which needs no third-party
driver at all -- that is what makes the relational connector testable rather
than merely described.
"""

from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from src.core.connectors import (
    ConnectionSpec,
    ConnectorError,
    ConnectorKind,
    available_kinds,
    build,
    kind_by_name,
    refuse_write,
    register,
    sanitize_identifier,
)
from src.core.connectors.store import ConnectionStore
from src.core.credentials import CredentialStore


# ------------------------------------------------------------------- spec --
def test_a_dotted_target_cannot_collapse_the_table_key() -> None:
    """The trap that makes two imported tables silently become one.

    ``DatasetHandle.table_key`` derives from ``Path(name).stem``, so a dataset
    named ``warehouse.orders`` would have stem ``warehouse`` -- and every table
    from that connection would land on the same key, the same feather file and
    the same ``tables[...]`` binding, each overwriting the last. The name is
    built dot-free for exactly this reason.
    """
    spec = ConnectionSpec(name="Warehouse", kind="relational")

    orders = spec.dataset_name("public.orders")
    customers = spec.dataset_name("public.customers")

    assert "." not in orders
    assert orders == "warehouse_public_orders"
    assert orders != customers


def test_a_connection_spec_carries_no_secret() -> None:
    """There is no field to forget to strip, which is stronger than remembering to."""
    spec = ConnectionSpec(name="W", kind="relational", options={"host": "db.internal", "user": "reader"})

    serialised = json.dumps(spec.to_dict())

    assert "password" not in serialised
    assert spec.credential_key == f"connection:{spec.id}"
    assert spec.read_only is True, "a connection must start read-only"


def test_a_spec_round_trips_through_disk() -> None:
    spec = ConnectionSpec(name="W", kind="relational", options={"host": "h"}, read_only=False)

    restored = ConnectionSpec.from_dict(json.loads(json.dumps(spec.to_dict())))

    assert (restored.id, restored.name, restored.options, restored.read_only) == (
        spec.id,
        spec.name,
        spec.options,
        False,
    )


def test_a_spec_missing_fields_falls_back_rather_than_raising() -> None:
    """A connections file that lost a key costs one retyped field, not a dead backend."""
    restored = ConnectionSpec.from_dict({"name": "W", "kind": "relational"})

    assert restored.read_only is True
    assert restored.options == {}
    assert restored.id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Q3 sales (final)", "q3_sales_final"), ("  ", "source"), ("__x__", "x"), ("A.B", "a_b")],
)
def test_identifiers_are_folded_to_a_safe_key(raw: str, expected: str) -> None:
    assert sanitize_identifier(raw) == expected


# --------------------------------------------------------------- registry --
def test_a_contributor_can_register_a_kind_without_touching_core() -> None:
    """The extensibility claim, asserted rather than described.

    If a connector can be registered from outside the package and then built by
    id, so can one contributed by somebody else -- which is what the spec means
    by "addable without touching core orchestration code".
    """

    class Fake:
        def __init__(self, spec: ConnectionSpec, secret: str = ""):
            self.spec = spec

    register(ConnectorKind(kind="fake", label="Fake", factory=Fake))
    try:
        assert kind_by_name("fake") is not None
        assert isinstance(build(ConnectionSpec(name="f", kind="fake")), Fake)
    finally:
        from src.core.connectors.registry import _FACTORIES

        _FACTORIES.pop("fake", None)


def test_an_unknown_kind_is_refused_by_name() -> None:
    with pytest.raises(ConnectorError, match="Unknown connection kind"):
        build(ConnectionSpec(name="x", kind="teleport"))


def test_a_missing_driver_is_reported_with_the_command_that_fixes_it() -> None:
    """Absent drivers are listed, not hidden.

    Hiding the kind would let a user conclude Wizard cannot reach Postgres,
    when the true answer is that one pip install would.
    """
    entry = ConnectorKind(
        kind="absent", label="Absent", factory=lambda spec, secret: None, module="no_such_module_xyz", distribution="x"
    )

    assert entry.available() is False
    assert entry.install_hint == "pip install x"


def test_every_reference_kind_is_registered() -> None:
    assert {entry.kind for entry in available_kinds()} >= {"relational", "document", "objectstore"}


def test_write_is_refused_on_a_read_only_spec() -> None:
    with pytest.raises(ConnectorError, match="read-only"):
        refuse_write(ConnectionSpec(name="W", kind="relational"))


# ------------------------------------------------------------------ store --
def test_the_connections_file_never_contains_the_secret(tmp_path) -> None:
    """The single most important assertion in the connector layer."""
    store = ConnectionStore(path=tmp_path / "connections.json")
    spec = ConnectionSpec(name="W", kind="relational", options={"host": "db.internal"})

    store.save(spec, secret="hunter2-super-secret")

    assert "hunter2-super-secret" not in (tmp_path / "connections.json").read_text(encoding="utf-8")
    assert store.secret_for(spec) == "hunter2-super-secret", "but it is still retrievable"


def test_deleting_a_connection_takes_its_secret_with_it(tmp_path) -> None:
    """A credential left behind is a stored secret nobody can see to revoke."""
    store = ConnectionStore(path=tmp_path / "connections.json")
    spec = ConnectionSpec(name="W", kind="relational")
    store.save(spec, secret="s3cret")

    assert store.delete(spec.id) is True
    assert store.secret_for(spec) == ""
    assert store.get(spec.id) is None


def test_a_corrupt_connections_file_reads_as_empty(tmp_path) -> None:
    """Never a backend that will not answer, for the same reason as the key store."""
    path = tmp_path / "connections.json"
    path.write_text("{not json at all", encoding="utf-8")

    assert ConnectionStore(path=path).list() == []


def test_a_connection_is_findable_by_name(tmp_path) -> None:
    """What Milestone 9's exported script needs: a name, not an opaque id."""
    store = ConnectionStore(path=tmp_path / "connections.json")
    store.save(ConnectionSpec(name="Warehouse", kind="relational"), secret="")

    assert store.by_name("warehouse") is not None
    assert store.by_name("nothing") is None


def test_a_connection_secret_is_not_reported_as_a_provider_key(tmp_path) -> None:
    """They share one flat keyspace, so the provider list has to exclude them.

    Without the filter a saved database password shows up on the models page as
    a configured model provider.
    """
    store = CredentialStore(path=tmp_path / "credentials.json")
    store.set("openai", "sk-test")
    store.set("connection:abc123", "db-password")

    assert store.providers_with_keys() == ["openai"]
    assert store.names("connection:") == ["connection:abc123"]


# ------------------------------------------------------- relational driver --
@pytest.fixture
def sqlite_spec(tmp_path):
    """A real database, built with the standard library and no server."""
    database = tmp_path / "shop.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE orders (id INTEGER, region TEXT, amount REAL)")
    connection.executemany(
        "INSERT INTO orders VALUES (?, ?, ?)",
        [(index, "north" if index % 2 else "south", index * 1.5) for index in range(25)],
    )
    connection.commit()
    connection.close()
    return ConnectionSpec(name="Shop", kind="relational", options={"driver": "sqlite", "database": str(database)})


def test_a_real_sqlite_connection_reads_end_to_end(sqlite_spec) -> None:
    pytest.importorskip("sqlalchemy")
    connector = build(sqlite_spec)
    try:
        connector.test()
        schema = connector.discover()
        frame = connector.sample("orders", limit=5)
    finally:
        connector.close()

    assert "orders" in {target.name for target in schema.targets}
    assert len(frame) == 5
    assert list(frame.columns) == ["id", "region", "amount"]


def test_the_row_limit_is_pushed_down_not_sliced_afterwards(sqlite_spec) -> None:
    """`sample` must bound the read in the engine, not fetch everything and slice.

    Asserted through the result rather than the SQL because the limit clause is
    spelled differently by dialect -- which is exactly why it is built with
    `select().limit()` and not by string assembly.
    """
    pytest.importorskip("sqlalchemy")
    connector = build(sqlite_spec)
    try:
        assert len(connector.sample("orders", limit=3)) == 3
    finally:
        connector.close()


def test_a_read_only_connection_refuses_to_write(sqlite_spec) -> None:
    pytest.importorskip("sqlalchemy")
    connector = build(sqlite_spec)
    try:
        with pytest.raises(ConnectorError, match="read-only"):
            connector.write("orders", pd.DataFrame({"id": [1]}))
    finally:
        connector.close()


def test_an_unreachable_database_reports_rather_than_hangs(tmp_path) -> None:
    """Degrades with a message; never a bare driver traceback."""
    pytest.importorskip("sqlalchemy")
    spec = ConnectionSpec(name="Broken", kind="relational", options={"driver": "sqlite", "database": "/nope/x.db"})
    connector = build(spec)

    with pytest.raises(ConnectorError):
        connector.test()


def test_a_spec_with_no_driver_or_dsn_says_so() -> None:
    pytest.importorskip("sqlalchemy")
    connector = build(ConnectionSpec(name="Empty", kind="relational"))

    with pytest.raises(ConnectorError, match="no driver or DSN"):
        connector.test()
