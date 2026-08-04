"""Which kinds of data source this install can reach.

The extension point. Adding support for a database is a ``register()`` call and a
module implementing ``Connector`` -- no change to the orchestrator, the session,
the routes or the UI, all of which deal in ``ConnectionSpec`` and never in a
driver.

**Keyed by an explicit ``kind``, not by a URL scheme sniffed from the DSN.** The
two look equivalent and are not: ``s3://`` and ``mongodb+srv://`` are not
SQLAlchemy dialects, an object store is often configured with a bare endpoint and
no scheme at all, and a string that parses as neither would resolve to whichever
driver matched first rather than to an error. The user picks the kind; an unknown
one is refused by name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.util import find_spec

from src.utils.logging import logger

from .base import Connector
from .spec import ConnectionSpec, ConnectorError


#: kind -> how to build one. Populated by `register`, read by `build`.
_FACTORIES: dict[str, ConnectorKind] = {}


@dataclass(frozen=True)
class ConnectorKind:
    """One registered kind, and what the UI needs to offer it."""

    kind: str
    label: str
    factory: Callable[[ConnectionSpec, str], Connector]
    #: Import name probed to decide whether this kind is usable, and the pip
    #: distribution to name when it is not. Probed with `find_spec` rather than
    #: by importing: this is consulted whenever the connections page renders, and
    #: it must cost a path search rather than pulling boto3 into the API process.
    module: str = ""
    distribution: str = ""
    #: Which non-secret fields this kind needs, so one form renders every kind
    #: without the frontend hardcoding a schema per database.
    fields: tuple[str, ...] = field(default_factory=tuple)
    #: Whether the secret is required, or merely allowed. A SQLite file needs
    #: none; a warehouse does.
    requires_secret: bool = False
    description: str = ""

    def available(self) -> bool:
        """Whether the driver behind this kind can actually be imported."""
        if not self.module:
            return True
        try:
            return find_spec(self.module) is not None
        except (ImportError, ValueError):
            # A namespace package in a broken state raises rather than returning
            # None. Unusable either way, and not worth failing the page render.
            return False

    @property
    def install_hint(self) -> str:
        return f"pip install {self.distribution}" if self.distribution else ""

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "label": self.label,
            "fields": list(self.fields),
            "requires_secret": self.requires_secret,
            "description": self.description,
            "available": self.available(),
            "install_hint": self.install_hint,
        }


def register(kind: ConnectorKind) -> None:
    """Adds a kind to the registry, replacing any earlier one of the same name."""
    _FACTORIES[kind.kind] = kind
    logger.debug("Registered a connector kind", kind=kind.kind)


def available_kinds() -> tuple[ConnectorKind, ...]:
    """Every registered kind, whether or not its driver is installed.

    Absent drivers are listed rather than hidden: a user looking for Postgres
    should be told to install the driver, not left to conclude Wizard cannot
    talk to Postgres.
    """
    return tuple(_FACTORIES[key] for key in sorted(_FACTORIES))


def kind_by_name(kind: str) -> ConnectorKind | None:
    return _FACTORIES.get((kind or "").strip().lower())


def build(spec: ConnectionSpec, secret: str = "") -> Connector:
    """Constructs the connector for ``spec``.

    Raises ``ConnectorError`` for an unknown kind and ``DriverMissing`` when the
    kind is known but its driver is not installed -- two different problems with
    two different remedies, so they are not collapsed into one message.
    """
    entry = kind_by_name(spec.kind)
    if entry is None:
        known = ", ".join(sorted(_FACTORIES)) or "none"
        raise ConnectorError(
            f"Unknown connection kind: {spec.kind or '(empty)'}.",
            detail=f"Registered kinds: {known}.",
        )
    return entry.factory(spec, secret)


__all__ = ["ConnectorKind", "available_kinds", "build", "kind_by_name", "register"]
