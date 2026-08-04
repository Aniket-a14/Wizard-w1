"""Connecting a session to a data source that is not a file."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Response

from src.api.deps import SESSION_HEADER, get_session, require_api_key
from src.api.schemas import (
    ConnectionImportRequest,
    ConnectionImportResponse,
    ConnectionListResponse,
    ConnectionRequest,
    ConnectionSchemaResponse,
    ConnectionSummary,
    ConnectionTestResponse,
    ConnectionWriteRequest,
    ConnectorKindResponse,
    DatasetSummary,
    WriteBackRequest,
)
from src.core.connectors import ConnectionSpec, ConnectorError, DriverMissing, available_kinds, build, kind_by_name
from src.core.connectors.gate import authorize, require_writable
from src.core.connectors.ingest import import_target
from src.core.connectors.store import connection_store
from src.core.session import Session
from src.utils.logging import logger


router = APIRouter(prefix="/api", tags=["connections"])


def _summary(spec: ConnectionSpec) -> ConnectionSummary:
    entry = kind_by_name(spec.kind)
    return ConnectionSummary(
        id=spec.id,
        name=spec.name,
        kind=spec.kind,
        options=dict(spec.options),
        read_only=spec.read_only,
        created_at=spec.created_at,
        has_secret=bool(connection_store.secret_for(spec)),
        available=entry.available() if entry else False,
        install_hint=entry.install_hint if entry else "",
    )


def _require_spec(connection_id: str) -> ConnectionSpec:
    spec = connection_store.get(connection_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"No connection with id {connection_id!r}.")
    return spec


def _open(spec: ConnectionSpec):
    """Builds a connector, turning a missing driver into a 501 with the remedy.

    501 rather than 500 because the server is working and the feature is simply
    not installed -- the same code the document upload route returns when pypdf
    is absent.
    """
    try:
        return build(spec, connection_store.secret_for(spec))
    except DriverMissing as exc:
        raise HTTPException(status_code=501, detail=f"{exc.message} {exc.detail}")
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.message} {exc.detail}".strip())


def _permit(session: Session, category: str, subject: str) -> None:
    """Applies the permission profile to a user-initiated action, or 403s."""
    ruling = authorize(session.permissions, category, subject)
    if not ruling.allowed:
        raise HTTPException(status_code=403, detail=ruling.reason)


# ------------------------------------------------------------------ #
@router.get("/connections", response_model=ConnectionListResponse)
async def list_connections(session: Session = Depends(get_session)) -> ConnectionListResponse:
    """Every saved connection, plus what this install can actually reach.

    Network-free on purpose: this renders on every page load, so it reports what
    is configured and which drivers are importable, and probes nothing.
    """
    return ConnectionListResponse(
        connections=[_summary(spec) for spec in connection_store.list()],
        kinds=[ConnectorKindResponse(**entry.to_dict()) for entry in available_kinds()],  # type: ignore[arg-type]
    )


@router.post("/connections", response_model=ConnectionSummary, dependencies=[Depends(require_api_key)])
async def create_connection(request: ConnectionRequest, session: Session = Depends(get_session)) -> ConnectionSummary:
    """Saves a connection. Reaches nothing, so it is not permission-gated.

    Storing a hostname is not connecting to it -- the gate is on opening the
    connection, which is where data actually moves. See `connectors/gate.py`.
    """
    name = (request.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="A connection needs a name.")
    if kind_by_name(request.kind) is None:
        known = ", ".join(entry.kind for entry in available_kinds())
        raise HTTPException(status_code=400, detail=f"Unknown connection kind {request.kind!r}. Known kinds: {known}.")
    if connection_store.by_name(name) is not None:
        raise HTTPException(status_code=409, detail=f"A connection named {name!r} already exists.")

    spec = ConnectionSpec(name=name, kind=request.kind, options=dict(request.options))
    if not connection_store.save(spec, secret=request.secret or ""):
        raise HTTPException(status_code=500, detail="Could not save the connection.")
    return _summary(spec)


@router.delete("/connections/{connection_id}", dependencies=[Depends(require_api_key)])
async def delete_connection(connection_id: str, session: Session = Depends(get_session)) -> dict[str, str]:
    """Removes a connection, its stored secret, and anything imported from it.

    The imported tables go too. Leaving them would keep rows from a source the
    user just disconnected queryable by generated code, and their data-policy
    overrides would outlive the thing they were set on.
    """
    spec = _require_spec(connection_id)
    for name in [handle.name for handle in session.datasets.values() if handle.origin == spec.name]:
        session.remove_dataset(name)
    session.data_policy.forget(spec.name)
    connection_store.delete(connection_id)
    return {"message": f"Removed the connection {spec.name!r}."}


@router.post("/connections/{connection_id}/test", response_model=ConnectionTestResponse)
async def test_connection(connection_id: str, session: Session = Depends(get_session)) -> ConnectionTestResponse:
    """Reaches the source and reports what happened.

    Not gated, and it never raises for a refused connection: this is the
    diagnostic someone runs *while* typing a hostname, and a diagnostic that
    fails instead of reporting is useless at exactly the moment it is needed.
    """
    spec = _require_spec(connection_id)
    connector = _open(spec)
    try:
        await asyncio.to_thread(connector.test)
    except ConnectorError as exc:
        return ConnectionTestResponse(ok=False, detail=f"{exc.message} {exc.detail}".strip())
    except Exception as exc:
        logger.warning("A connection test failed", connection=spec.name, error=str(exc))
        return ConnectionTestResponse(ok=False, detail=str(exc))
    finally:
        await asyncio.to_thread(connector.close)
    return ConnectionTestResponse(ok=True, detail="Reached the source.")


@router.get("/connections/{connection_id}/schema", response_model=ConnectionSchemaResponse)
async def discover_connection(connection_id: str, session: Session = Depends(get_session)) -> ConnectionSchemaResponse:
    """Lists what the source contains. Gated: metadata leaves the source."""
    spec = _require_spec(connection_id)
    _permit(session, "db_connect", spec.id)
    connector = _open(spec)
    try:
        schema = await asyncio.to_thread(connector.discover)
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.message} {exc.detail}".strip())
    finally:
        await asyncio.to_thread(connector.close)
    return ConnectionSchemaResponse(**schema.to_dict())  # type: ignore[arg-type]


@router.post(
    "/connections/{connection_id}/import",
    response_model=ConnectionImportResponse,
    dependencies=[Depends(require_api_key)],
)
async def import_from_connection(
    connection_id: str,
    request: ConnectionImportRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> ConnectionImportResponse:
    """Reads one table into the session, exactly as an upload would.

    Gated: this is the moment rows enter the analysis and become reachable by
    generated code and by a cloud-bound prompt.
    """
    spec = _require_spec(connection_id)
    _permit(session, "db_connect", spec.id)
    target = (request.target or "").strip()
    if not target:
        raise HTTPException(status_code=422, detail="Name the table to import.")

    connector = _open(spec)
    try:
        result = await asyncio.to_thread(import_target, session, spec, connector, target, request.make_active)
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.message} {exc.detail}".strip())
    except Exception as exc:
        logger.error("A connection import failed", connection=spec.name, target=target, error=str(exc))
        raise HTTPException(status_code=400, detail=f"Could not import {target!r}: {exc}")
    finally:
        await asyncio.to_thread(connector.close)

    response.headers[SESSION_HEADER] = session.id
    return ConnectionImportResponse(
        message=result.message,
        dataset=DatasetSummary(**result.handle.summary()),
        truncated=result.truncated,
        session_id=session.id,
    )


@router.post(
    "/connections/{connection_id}/write",
    response_model=ConnectionTestResponse,
    dependencies=[Depends(require_api_key)],
)
async def write_to_connection(
    connection_id: str, request: ConnectionWriteRequest, session: Session = Depends(get_session)
) -> ConnectionTestResponse:
    """Writes one of this session's tables back to the source.

    Three independent locks, and all three have to be open:

    1. ``spec.read_only`` must have been turned off for *this* connection, once,
       with the name typed back. Checked first, and **without asking anything** --
       a question whose only permitted answer is no is worse than no question.
    2. The ``db_write`` category must not be set to deny. It carries
       ``always_ask``, so no profile can pre-approve it either.
    3. The grant is recorded per ``connection:table``, not per connection:
       approving a write to ``staging.results`` is not approving one to
       ``prod.orders``.
    """
    spec = _require_spec(connection_id)
    writable = require_writable(spec)
    if not writable.allowed:
        raise HTTPException(status_code=403, detail=writable.reason)

    handle = session.datasets.get(request.dataset)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"No dataset named {request.dataset!r} in this session.")

    target = (request.target or "").strip()
    if not target:
        raise HTTPException(status_code=422, detail="Name the table to write to.")
    _permit(session, "db_write", f"{spec.id}:{target}")

    connector = _open(spec)
    try:
        await asyncio.to_thread(connector.write, target, handle.df)
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=f"{exc.message} {exc.detail}".strip())
    except Exception as exc:
        logger.error("A write-back failed", connection=spec.name, target=target, error=str(exc))
        raise HTTPException(status_code=400, detail=f"Could not write to {target!r}: {exc}")
    finally:
        await asyncio.to_thread(connector.close)

    logger.info("Wrote a table back to a source", connection=spec.name, target=target, rows=len(handle.df))
    return ConnectionTestResponse(ok=True, detail=f"Wrote {len(handle.df):,} rows to '{target}'.")


@router.post(
    "/connections/{connection_id}/write-back",
    response_model=ConnectionSummary,
    dependencies=[Depends(require_api_key)],
)
async def set_write_back(
    connection_id: str, request: WriteBackRequest, session: Session = Depends(get_session)
) -> ConnectionSummary:
    """Turns write-back on or off for one connection.

    Enabling requires the connection's name typed back. This is the one decision
    in the app whose consequences land outside this machine, and the spec is
    explicit that it is made once, deliberately, per connection -- never by a
    permission profile, which `db_write`'s `always_ask` already guarantees.

    Enabling does **not** grant a write. It says this connection *may* be written
    to at all; every session still asks the first time the agent actually writes.
    """
    spec = _require_spec(connection_id)
    if request.enable and (request.confirm or "").strip() != spec.name:
        raise HTTPException(
            status_code=400,
            detail=f"Type the connection's name ({spec.name!r}) to confirm enabling write-back.",
        )

    updated = ConnectionSpec(
        name=spec.name,
        kind=spec.kind,
        options=dict(spec.options),
        id=spec.id,
        read_only=not request.enable,
        created_at=spec.created_at,
    )
    if not connection_store.save(updated, secret=None):
        raise HTTPException(status_code=500, detail="Could not update the connection.")
    logger.info("Changed write-back for a connection", connection=spec.name, write_back=request.enable)
    return _summary(updated)


__all__ = ["router"]
