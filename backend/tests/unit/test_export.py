"""`core.agent.export` -- the shared builder behind both the always-on
per-turn script and the on-demand `GET /api/export/{message_id}` route.

Real `Session`/`DatasetHandle` objects throughout rather than mocks: the whole
point of these builders is producing code that references real table keys and
real connection names, so a mock would hide exactly the bug (a wrong key, a
leaked secret) these tests exist to catch.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.core.agent import export
from src.core.connectors.spec import ConnectionSpec
from src.core.connectors.store import connection_store
from src.core.session import Session, session_manager


SECRET = "s3cr3t-password"


@pytest.fixture
def session() -> Session:
    created = session_manager.create()
    yield created
    session_manager.drop(created.id)


STEPS = [
    {"goal": "load and inspect", "code": "print(df.head())"},
    {"goal": "summarise", "code": "print(df['A'].sum())"},
]


# --------------------------------------------------------------------------- #
# build_script
# --------------------------------------------------------------------------- #
def test_build_script_with_no_steps_is_empty(session: Session) -> None:
    assert export.build_script("q", [], session) == ""


def test_build_script_binds_df_and_includes_every_step(session: Session) -> None:
    session.add_dataset("orders.csv", pd.DataFrame({"id": [1, 2]}))

    script = export.build_script("How many orders?", STEPS, session)

    assert "How many orders?" in script
    assert "print(df.head())" in script
    assert "print(df['A'].sum())" in script
    assert "df = tables['orders']" in script


def test_in_workspace_script_reads_the_materialised_feather_files(session: Session) -> None:
    """`bundle=False` is the always-on artifact: it stays inside the workspace,
    next to the per-table Feather files `Session._materialize` already wrote,
    so it must read those in place rather than a CSV that was never bundled."""
    session.add_dataset("orders.csv", pd.DataFrame({"id": [1]}))

    script = export.build_script("q", STEPS, session, bundle=False)

    assert 'pd.read_feather("tables/orders.feather")' in script
    assert "data/orders.csv" not in script


def test_bundled_script_reads_the_shipped_csv(session: Session) -> None:
    """`bundle=True` is the downloaded zip: it ships its own CSV copies, since
    the workspace's Feather files do not travel with it."""
    session.add_dataset("orders.csv", pd.DataFrame({"id": [1]}))

    script = export.build_script("q", STEPS, session, bundle=True)

    assert 'pd.read_csv("data/orders.csv")' in script
    assert "tables/orders.feather" not in script


def test_multiple_tables_are_all_loaded_not_just_the_active_one(session: Session) -> None:
    """A session with more than one table produces code addressing
    `tables['other_table']` -- the bug this milestone exists to fix: the old
    header only ever loaded `dataset.csv`, so a second table's name was never
    bound and the script `NameError`d the moment it ran standalone."""
    session.add_dataset("orders.csv", pd.DataFrame({"id": [1], "customer_id": [10]}))
    session.add_dataset("customers.csv", pd.DataFrame({"customer_id": [10], "name": ["a"]}))

    script = export.build_script("join them", STEPS, session, bundle=True)

    assert "tables['orders'] = pd.read_csv(\"data/orders.csv\")" in script
    assert "tables['customers'] = pd.read_csv(\"data/customers.csv\")" in script
    # The active dataset is whichever was added last, per `Session.add_dataset`.
    assert "df = tables['customers']" in script


# --------------------------------------------------------------------------- #
# Connector-sourced tables
# --------------------------------------------------------------------------- #
def _connector_backed_session(session: Session) -> Session:
    spec = ConnectionSpec(name="Shop", kind="relational", options={"driver": "sqlite", "database": "x.db"})
    connection_store.save(spec, secret=SECRET)

    handle = session.add_dataset("orders", pd.DataFrame({"id": [1]}))
    handle.origin = "Shop"
    handle.profile["target"] = "orders"
    return session


def test_a_connector_sourced_table_is_looked_up_by_name_not_embedded(session: Session) -> None:
    session = _connector_backed_session(session)

    script = export.build_script("q", STEPS, session)

    assert "connection_store.by_name('Shop')" in script
    assert "_conn.sample('orders'" in script
    assert "from src.core.connectors.registry import build as build_connector" in script
    assert "from src.core.connectors.store import connection_store" in script


def test_no_secret_ever_appears_in_generated_output(session: Session) -> None:
    session = _connector_backed_session(session)

    script = export.build_script("q", STEPS, session, bundle=True)
    notebook = export.build_notebook("q", STEPS, session, bundle=True)

    assert SECRET not in script
    assert SECRET not in str(notebook)


def test_a_connector_sourced_table_is_never_bundled(session: Session) -> None:
    session = _connector_backed_session(session)

    assert export.bundle_files(session) == {}


def test_a_mixed_session_bundles_only_the_file_based_table(session: Session) -> None:
    session = _connector_backed_session(session)
    session.add_dataset("extras.csv", pd.DataFrame({"a": [1]}))

    bundle = export.bundle_files(session)

    assert set(bundle) == {"data/extras.csv"}
    assert bundle["data/extras.csv"].decode("utf-8").splitlines() == ["a", "1"]


# --------------------------------------------------------------------------- #
# build_notebook
# --------------------------------------------------------------------------- #
def test_build_notebook_carries_every_step_as_its_own_cell(session: Session) -> None:
    session.add_dataset("orders.csv", pd.DataFrame({"id": [1]}))

    notebook = export.build_notebook("How many orders?", STEPS, session)

    assert notebook["nbformat"] == 4
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    # One import/loader cell plus one per step.
    assert len(code_cells) == 1 + len(STEPS)
    sources = ["".join(cell["source"]) for cell in code_cells]
    assert any("print(df.head())" in source for source in sources)
    assert any("print(df['A'].sum())" in source for source in sources)


def test_build_notebook_with_no_steps_is_empty(session: Session) -> None:
    assert export.build_notebook("q", [], session) == {}
