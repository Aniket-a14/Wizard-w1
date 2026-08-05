"""Turning a connection read into a session dataset.

The join between this package and the rest of the app, and deliberately the only
module here that imports ``Session``. Everything above it deals in frames and
specs; everything below it deals in drivers.

It ends in the same five calls as the upload route (``routes/datasets.py``
100-110) -- ``CatalogEngine.analyze`` → ``add_dataset`` → ``register_dataframe``
→ ``reload_dataset`` -- because a connection is an ingest source *parallel* to a
file, not a second kind of thing. Once the frame is registered nothing
downstream can tell where it came from, which is the property that keeps
``table_key`` sanitisation, per-source data policy, Feather materialisation and
the daemon's ``tables`` dict working with no special-casing.

**This runs in the parent process, always.** Generated code never holds a
connector and never opens a socket -- see ``base.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.config import settings
from src.core.session import DatasetHandle, Session
from src.core.tools.catalog import CatalogEngine
from src.core.tools.schema_registry import SchemaRegistry
from src.utils.logging import logger

from .base import Connector
from .spec import ConnectionSpec


@dataclass
class ImportResult:
    """What one import produced, including what it had to leave behind."""

    handle: DatasetHandle
    rows: int
    truncated: bool
    row_limit: int

    @property
    def message(self) -> str:
        if self.truncated:
            return (
                f"Imported the first {self.rows:,} rows of '{self.handle.name}'. "
                f"The source has more; the import stopped at CONNECTOR_MAX_ROWS ({self.row_limit:,})."
            )
        return f"Imported {self.rows:,} rows into '{self.handle.name}'."


def import_target(
    session: Session,
    spec: ConnectionSpec,
    connector: Connector,
    target: str,
    make_active: bool = True,
    row_limit: int | None = None,
) -> ImportResult:
    """Reads one target from a connection and registers it as a dataset.

    Synchronous, and blocking on purpose: every driver call is. Callers reach it
    through ``asyncio.to_thread`` exactly as the upload route reaches
    ``DatasetLoader.load``, so one slow database cannot stall the event loop and
    every other session in the process with it.
    """
    limit = int(row_limit or settings.CONNECTOR_MAX_ROWS)
    # One row past the ceiling, so "there was more" is a fact read off the result
    # rather than an assumption made because the count came back exactly equal.
    frame = connector.sample(target, limit=limit + 1)
    truncated = len(frame) > limit
    if truncated:
        frame = frame.head(limit)
        logger.warning(
            "A connection import hit the row ceiling",
            connection=spec.name,
            target=target,
            row_limit=limit,
        )

    name = spec.dataset_name(target)
    catalog = CatalogEngine.analyze(frame)
    handle = session.add_dataset(
        name=name,
        df=frame,
        catalog=catalog,
        profile=_profile(frame, spec, target, truncated, limit),
        # Prefixed so the UI can say where a table came from without parsing its
        # name, and so `DatasetSummary` carries the provenance for free.
        source_format=f"connection:{spec.kind}",
        make_active=make_active,
    )
    handle.origin = spec.name

    SchemaRegistry.register_dataframe(name, frame, session_id=session.id)
    session.executor.reload_dataset()

    logger.info(
        "Imported a table from a connection",
        connection=spec.name,
        target=target,
        dataset=name,
        rows=len(frame),
        session=session.id,
    )
    return ImportResult(handle=handle, rows=len(frame), truncated=truncated, row_limit=limit)


def _profile(frame: pd.DataFrame, spec: ConnectionSpec, target: str, truncated: bool, limit: int) -> dict:
    """The same shape ``DatasetProfile.to_dict`` produces, plus the source.

    ``truncated`` and ``original_rows`` already exist on the upload path and are
    already rendered, so a bounded import reports itself through the surface the
    UI has rather than through a new one.
    """
    return {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "truncated": truncated,
        # `None` when the read was bounded, not `limit + 1`. The source's real
        # size was never queried, and the trust layer renders this figure as an
        # exact total ("down-sampled to N of M"), so a plausible number here
        # becomes an invented one on screen -- the precise thing `grounding.py`
        # exists to prevent. Not knowing is reported as not knowing.
        "original_rows": None if truncated else int(len(frame)),
        "connection": spec.name,
        "target": target,
    }


__all__ = ["ImportResult", "import_target"]
