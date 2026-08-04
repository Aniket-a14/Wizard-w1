"""Connecting to a data source that is not a file.

Importing this package registers the three reference connectors. Each imports its
driver lazily, so an install with none of them still imports cleanly -- an absent
driver surfaces as ``available: false`` on the kind, with the pip command to fix
it, rather than as an ImportError at startup.
"""

from .base import DEFAULT_SAMPLE_ROWS, Connector, refuse_write
from .registry import ConnectorKind, available_kinds, build, kind_by_name, register
from .spec import (
    ColumnInfo,
    ConnectionSchema,
    ConnectionSpec,
    ConnectorError,
    DriverMissing,
    TargetInfo,
    inject_secret_into_dsn,
    sanitize_identifier,
    split_secret_from_dsn,
)
from .store import ConnectionStore, connection_store


# Registration by import. Kept last so the names above are bound before a
# connector module imports back from this package.
from . import document, objectstore, relational  # noqa: E402,F401  isort:skip


__all__ = [
    "DEFAULT_SAMPLE_ROWS",
    "ColumnInfo",
    "ConnectionSchema",
    "ConnectionSpec",
    "ConnectionStore",
    "Connector",
    "ConnectorError",
    "ConnectorKind",
    "DriverMissing",
    "TargetInfo",
    "available_kinds",
    "build",
    "connection_store",
    "inject_secret_into_dsn",
    "kind_by_name",
    "refuse_write",
    "register",
    "sanitize_identifier",
    "split_secret_from_dsn",
]
