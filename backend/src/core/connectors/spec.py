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
from urllib.parse import quote, unquote, urlsplit, urlunsplit


#: Prefix for the key a connection's secret is stored under in `credential_store`.
#: Namespaced so a connection can never collide with a provider API key, which
#: shares that flat keyspace.
CREDENTIAL_PREFIX = "connection:"

#: Hosts that do not leave the machine. `host.docker.internal` is deliberately
#: absent: it names the *host* from inside a container, which is a different
#: machine's loopback as far as this promise is concerned.
LOOPBACK_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"})


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


def split_secret_from_dsn(dsn: str) -> tuple[str, str]:
    """Separates a pasted connection string into its safe half and its password.

    Pasting a DSN is the most common way anyone configures a database, and the
    canonical form of one carries the password inline::

        postgresql://admin:hunter2@db.internal:5432/prod

    Left whole that string goes into ``spec.options``, and therefore into
    ``connections.json``, into every ``ConnectionSummary`` the API returns, and
    into anything that logs a spec -- which would make this module's central
    claim, that a spec holds no secret, false in exactly the case people use
    most. So the password is lifted out here, at the boundary, and stored where
    every other secret goes; the connector puts it back when it builds the URL.

    Returns ``(dsn_without_password, password)``. A DSN with no password comes
    back unchanged with an empty secret, and a string that does not parse is
    returned untouched rather than mangled -- the driver's own error message
    about a malformed DSN is more useful than anything invented here.
    """
    raw = (dsn or "").strip()
    if not raw or "@" not in raw:
        return raw, ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw, ""
    if not parsed.password:
        return raw, ""

    host = _host_and_port(parsed)
    if host is None:
        return raw, ""
    userinfo = quote(unquote(parsed.username or ""), safe="")
    netloc = f"{userinfo}@{host}" if userinfo else host
    stripped = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return stripped, unquote(parsed.password)


def inject_secret_into_dsn(dsn: str, secret: str) -> str:
    """Puts a stored password back into a DSN, undoing ``split_secret_from_dsn``."""
    raw = (dsn or "").strip()
    if not raw or not secret:
        return raw
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    if parsed.password or not parsed.username:
        # Already carries one, or there is no user to attach it to -- either way
        # rewriting would be guessing at what the user meant.
        return raw

    host = _host_and_port(parsed)
    if host is None:
        return raw
    userinfo = f"{quote(unquote(parsed.username), safe='')}:{quote(secret, safe='')}"
    return urlunsplit((parsed.scheme, f"{userinfo}@{host}", parsed.path, parsed.query, parsed.fragment))


def _host_and_port(parsed) -> str | None:
    """The authority's ``host[:port]``, IPv6-bracketed, or ``None`` on a port ``urlsplit`` won't parse.

    ``parsed.hostname`` already strips IPv6 brackets, so ``::1`` rebuilt with a
    port reads as ``::1:5432`` -- not a valid authority -- unless the brackets
    go back on. ``parsed.port`` separately raises ``ValueError`` for a port a
    driver would accept but the standard library won't parse as an int, and
    that access happens outside the caller's own ``try/except`` around
    ``urlsplit`` itself, so it needs its own handling here rather than
    crashing the caller on a DSN nobody asked this module to validate.
    """
    hostname = parsed.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError:
        return None
    return f"{hostname}:{port}" if port else hostname


def _hostname_of(url: str) -> str:
    """The host a URL names, or ``""`` when it names none.

    An empty answer is meaningful rather than a parse failure: ``sqlite:///x.db``
    and a bare filesystem path both reach nothing over a network.
    """
    try:
        parsed = urlsplit(url if "//" in url else f"//{url}")
    except ValueError:
        return ""
    return (parsed.hostname or "").strip().lower()


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

    def reaches_network(self) -> bool:
        """Whether opening this connection would leave the machine.

        `local-only` promises "nothing is sent anywhere", and a connection to a
        hosted warehouse or a public bucket would break that promise just as a
        web search would -- so the mode has to be able to tell the two apart.
        Judged from the endpoint, not from the kind: a SQLite file and a Postgres
        on loopback are local, the same driver pointed at a remote host is not.

        Unknown resolves to **True**. The safe direction, for the same reason
        `providers.is_cloud` treats an unrecognised provider as cloud: calling
        something unrecognised local would open the hole the check exists to close.
        """
        host = str(self.options.get("host") or "").strip().lower()
        endpoint = str(self.options.get("endpoint_url") or "").strip().lower()
        dsn = str(self.options.get("dsn") or "").strip().lower()

        if endpoint:
            return _hostname_of(endpoint) not in LOOPBACK_HOSTS
        if dsn:
            # Parsed rather than substring-matched, because a DSN can name no host
            # at all: `sqlite:///data.db` is a *file*, and judging it by whether a
            # loopback name appears in the string made every file-backed engine
            # look remote -- so `local-only` refused the one connection that never
            # leaves the machine.
            parsed_host = _hostname_of(dsn)
            if not parsed_host:
                return False
            return parsed_host not in LOOPBACK_HOSTS
        if host:
            return host not in LOOPBACK_HOSTS
        # No host, no endpoint, no DSN: a file-backed engine such as SQLite, or a
        # bucket reached through the AWS default chain. The bucket case is the
        # reason `bucket` alone counts as remote.
        return bool(str(self.options.get("bucket") or "").strip())

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
