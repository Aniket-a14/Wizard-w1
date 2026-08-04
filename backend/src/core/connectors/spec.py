"""What a connection *is*, as inert data.

Deliberately JSON-safe and free of live handles, drivers and secrets, for the
same reason ``security/sandbox/policy.py`` is: it is the single description of a
data source, and everything else -- the drivers, the REST surface, the stored
file -- is a rendering of it. A spec can be constructed, serialised and asserted
on with no driver installed and nothing running.

**The secret is not in here.** ``ConnectionSpec`` carries a *reference* to a
credential (``credential_key``), never the credential. That is what makes it safe
to write this object to ``connections.json``, return it from a route and put it
in a log line, and it is why the store and the API can stay simple: there is no
field to remember to strip.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


#: Prefix for the key a connection's secret is stored under in `credential_store`.
#: Namespaced so a connection can never collide with a provider API key, which
#: shares that flat keyspace.
CREDENTIAL_PREFIX = "connection:"


class ConnectorError(Exception):
    """Anything that went wrong reaching or reading a data source.

    One exception type rather than a hierarchy per driver: the caller's options
    are the same whichever engine refused, and the driver's own message is what
    actually says what happened. ``detail`` carries that message verbatim.
    """

    def __init__(self, message: str, *, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


class DriverMissing(ConnectorError):
    """The driver for this kind is not installed.

    Its own type because it is the one failure with a *remedy* rather than a
    cause: the caller renders ``install_hint`` and the user runs one command.
    Everything else is a fault to report.
    """

    def __init__(self, kind: str, distribution: str):
        super().__init__(
            f"The driver for {kind} is not installed.",
            detail=f"Install it with: pip install {distribution}",
        )
        self.kind = kind
        self.distribution = distribution

    @property
    def install_hint(self) -> str:
        return f"pip install {self.distribution}"


def sanitize_identifier(value: str) -> str:
    """Folds an arbitrary name to the ``[a-z0-9_]`` a table key may contain.

    Shared by the connection name and the remote target name so that the dataset
    name built from the two cannot contain a dot. That matters more than it
    looks: ``DatasetHandle.table_key`` derives from ``Path(name).stem``, so a
    dataset called ``public.orders`` would silently become ``public`` -- dropping
    the table and colliding with every other schema's tables.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return cleaned or "source"


@dataclass
class ColumnInfo:
    """One column, as the source describes it before pandas sees it."""

    name: str
    type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type}


@dataclass
class TargetInfo:
    """One readable thing in a source: a table, a collection, an object prefix."""

    name: str
    #: Free-form and engine-specific -- a schema for Postgres, a database for
    #: Mongo, a bucket for S3. Rendered for the user, never parsed.
    namespace: str = ""
    columns: list[ColumnInfo] = field(default_factory=list)
    #: `None` when the engine cannot say cheaply. An estimate that cost a full
    #: scan to produce would defeat the point of discovery being fast.
    row_estimate: int | None = None

    @property
    def qualified(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "qualified": self.qualified,
            "columns": [column.to_dict() for column in self.columns],
            "row_estimate": self.row_estimate,
        }


@dataclass
class ConnectionSchema:
    """What one source contains, as discovery found it."""

    targets: list[TargetInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"targets": [target.to_dict() for target in self.targets]}


@dataclass
class ConnectionSpec:
    """A saved way of reaching one data source.

    Configuration, not data. It outlives the session that used it -- which is why
    it is persisted -- while the tables it imports do not.
    """

    name: str
    kind: str
    #: Driver-specific, non-secret connection detail: host, port, database,
    #: bucket, region. What belongs here rather than in the credential store is
    #: anything you would be willing to read aloud.
    options: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    #: Read-only until the user says otherwise, per connection, once. Nothing in
    #: the permission profile can flip this -- see `core/permissions.py`, where
    #: `db_write` carries `always_ask`.
    read_only: bool = True
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.name = (self.name or "").strip()
        self.kind = (self.kind or "").strip().lower()

    @property
    def credential_key(self) -> str:
        """Where this connection's secret lives in ``credential_store``."""
        return f"{CREDENTIAL_PREFIX}{self.id}"

    @property
    def slug(self) -> str:
        """The connection's half of an imported table's name."""
        return sanitize_identifier(self.name)

    def dataset_name(self, target: str) -> str:
        """The name an imported table is registered in the session under.

        Built here rather than at the call site so every connector produces the
        same shape, and so the no-dots rule described on `sanitize_identifier`
        holds for all of them.
        """
        return f"{self.slug}_{sanitize_identifier(target)}"

    def to_dict(self) -> dict[str, Any]:
        """The whole object. Safe to persist, return and log -- there is no secret in it."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "options": dict(self.options),
            "read_only": self.read_only,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ConnectionSpec:
        """Rebuilds a spec from disk, tolerating a file written by an older build.

        Every field falls back rather than raising: a connections file that has
        lost a key should cost the user one re-entered field, not a backend that
        will not boot.
        """
        options = payload.get("options")
        created = payload.get("created_at")
        return cls(
            name=str(payload.get("name") or ""),
            kind=str(payload.get("kind") or ""),
            options=dict(options) if isinstance(options, dict) else {},
            id=str(payload.get("id") or uuid.uuid4().hex),
            read_only=bool(payload.get("read_only", True)),
            created_at=float(created) if isinstance(created, (int, float)) else time.time(),
        )


__all__ = [
    "CREDENTIAL_PREFIX",
    "ColumnInfo",
    "ConnectionSchema",
    "ConnectionSpec",
    "ConnectorError",
    "DriverMissing",
    "TargetInfo",
    "sanitize_identifier",
]
