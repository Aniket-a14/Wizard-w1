"""Saved connections on local disk.

A connection is *configuration*, not data: the tables it imports belong to a
session and die with it, but the way of reaching the source outlives every
session that used it. So this persists, in the platform config directory beside
``credentials.json`` -- and it has to, because Milestone 9's exported script
looks a connection up by name at run time, which is impossible if the connection
vanished with a TTL-reaped session.

**The file holds no secrets.** ``ConnectionSpec`` carries a reference to a
credential, never the credential, so the split is structural rather than a rule
this module has to remember to apply: there is no field here to forget to strip.
The secret half lives in ``credential_store`` under ``connection:<id>``, which
gets the restricted-permissions treatment already built for API keys.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from src.core.credentials import credential_store
from src.utils.appdirs import config_dir
from src.utils.fileperms import restrict
from src.utils.logging import logger

from .spec import ConnectionSpec


CONNECTIONS_FILENAME = "connections.json"


class ConnectionStore:
    """Every saved connection, read once and cached in memory."""

    def __init__(self, path: Path | None = None):
        self._path = path
        self._cache: dict[str, ConnectionSpec] | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        # Resolved per access, not at construction: this is a singleton and the
        # test suite pins the config directory after import.
        return self._path or (config_dir() / CONNECTIONS_FILENAME)

    # ------------------------------------------------------------------ #
    def _load(self) -> dict[str, ConnectionSpec]:
        if self._cache is not None:
            return self._cache
        with self._lock:
            if self._cache is None:
                self._cache = self._read()
            return self._cache

    def _read(self) -> dict[str, ConnectionSpec]:
        path = self.path
        try:
            if not path.exists():
                return {}
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # A corrupt file means "no saved connections", never a backend that
            # will not answer. The same rule the credential store follows.
            logger.warning("Could not read saved connections", path=str(path), error=str(exc))
            return {}

        rows = payload.get("connections") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return {}

        specs: dict[str, ConnectionSpec] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                spec = ConnectionSpec.from_dict(row)
            except (TypeError, ValueError) as exc:
                logger.warning("Skipped an unreadable connection entry", error=str(exc))
                continue
            if spec.name and spec.kind:
                specs[spec.id] = spec
        return specs

    def _write(self, specs: dict[str, ConnectionSpec]) -> bool:
        path = self.path
        payload = {"connections": [spec.to_dict() for spec in specs.values()]}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Restricted even though there is no secret in it. The file still maps
            # somebody's internal network -- hosts, ports, database names, usernames
            # -- which is not something to leave world-readable.
            path.touch(exist_ok=True)
            restrict(path, "connections file")
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            restrict(path, "connections file")
        except OSError as exc:
            logger.error("Could not save connections", path=str(path), error=str(exc))
            return False
        return True

    # ------------------------------------------------------------------ #
    def list(self) -> list[ConnectionSpec]:
        return sorted(self._load().values(), key=lambda spec: spec.name.lower())

    def get(self, connection_id: str) -> ConnectionSpec | None:
        return self._load().get((connection_id or "").strip())

    def by_name(self, name: str) -> ConnectionSpec | None:
        """Looks a connection up the way a human refers to it.

        What Milestone 9's exported script needs: the script names the connection
        rather than embedding its id, so it stays readable and stays portable
        between machines that saved the same source under the same name.
        """
        wanted = (name or "").strip().lower()
        for spec in self._load().values():
            if spec.name.lower() == wanted:
                return spec
        return None

    def save(self, spec: ConnectionSpec, secret: str | None = None) -> bool:
        """Persists a connection, and its secret if one was given.

        ``secret=None`` means "leave whatever is stored alone", which is what an
        edit that did not retype the password must do. An empty string means
        "there is no secret", which is a real answer for a SQLite file.
        """
        with self._lock:
            specs = dict(self._read())
            specs[spec.id] = spec
            if not self._write(specs):
                return False
            self._cache = specs

        if secret is not None:
            if secret:
                credential_store.set(spec.credential_key, secret)
            else:
                credential_store.delete(spec.credential_key)
        logger.info("Saved a connection", connection=spec.name, kind=spec.kind)
        return True

    def delete(self, connection_id: str) -> bool:
        """Removes a connection and the secret that belonged to it.

        Both halves together: a credential left behind would be a stored secret
        for a source the user can no longer see to revoke.
        """
        key = (connection_id or "").strip()
        with self._lock:
            specs = dict(self._read())
            spec = specs.pop(key, None)
            if spec is None:
                self._cache = specs
                return False
            if not self._write(specs):
                return False
            self._cache = specs

        credential_store.delete(spec.credential_key)
        logger.info("Removed a connection", connection=spec.name)
        return True

    def secret_for(self, spec: ConnectionSpec) -> str:
        return credential_store.get(spec.credential_key)

    def reload(self) -> None:
        """Drops the cache so the next read goes back to disk."""
        with self._lock:
            self._cache = None

    def clear(self) -> None:
        """Removes every saved connection and its secret.

        For the test suite's teardown. Connections persist on purpose, which
        means that without this they persist *between tests* too -- the same
        cross-test leak the semantic cache already has a note about, and it
        surfaces as a name conflict in whichever test happens to run second.
        """
        for spec in self.list():
            self.delete(spec.id)
        self.reload()


connection_store = ConnectionStore()


__all__ = ["CONNECTIONS_FILENAME", "ConnectionStore", "connection_store"]
