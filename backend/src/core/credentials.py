"""Cloud API keys, stored on this machine and nowhere else.

Nothing is hosted and nothing is synced, so a key can only live on the user's own
disk. It also cannot live only in ``backend/.env``, which is inside the checkout:
typing a key into a settings field has to persist without editing a source file.

This is not encryption at rest. The file is protected by the operating system's
access control and nothing else — the same guarantee ``~/.aws/credentials`` has.
Encrypting it would need a passphrase at every backend start, which breaks the
unattended start Milestone 8 is built around, or a key stored beside the
ciphertext, which protects nothing. The OS keychain is the stronger option and is
deliberately not taken: three platform backends plus a dependency, and Secret
Service is often absent on headless Linux, so a file fallback would be needed
anyway. Everything goes through ``credential_store``, so a keychain backend can be
added later without touching a caller.

Permissions are enforced on all three platforms rather than documented on two.
An unreadable store degrades to "no stored keys"; a question never fails because
a credentials file has odd permissions.

Lives under ``core/`` rather than ``core/llm/`` because ``settings`` reads it, and
because Milestone 4's connection strings belong in the same store.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from src.utils.appdirs import config_dir
from src.utils.logging import logger


CREDENTIALS_FILENAME = "credentials.json"

#: Characters of a key shown back to the user. Enough to tell two keys apart.
HINT_CHARS = 4


def _icacls(*args: str) -> bool:
    try:
        subprocess.run(  # noqa: S603 - fixed executable, arguments are not user input
            ["icacls", *args], check=True, capture_output=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def _current_user_sid() -> str:
    """The SID of the account this process is actually running as.

    Read from the process token via ``whoami`` rather than from ``%USERNAME%``,
    which is an ordinary environment variable and can name someone else entirely
    — on the machine this was written on it read ``Wizard``. Granting to a name
    that is not the running user locks the owner out of their own file.
    """
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable, no user input
            ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, timeout=15, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    fields = result.stdout.decode(errors="replace").strip().strip('"').split('","')
    return fields[-1].strip() if len(fields) >= 2 and fields[-1].startswith("S-1-") else ""


def _restrict_windows(path: Path) -> None:
    """Grants the running account sole access. ``os.chmod`` does not touch the ACL here.

    Verified afterwards, and rolled back if it went wrong: a credentials file
    nobody can write is a worse outcome than one with inherited permissions, and
    it fails at exactly the moment someone is trying to save a key.
    """
    sid = _current_user_sid()
    if not sid:
        logger.warning("Could not identify the running account; credentials file keeps inherited permissions")
        return

    if not _icacls(str(path), "/inheritance:r", "/grant:r", f"*{sid}:F"):
        logger.warning("Could not restrict permissions on the credentials file", path=str(path))
        return

    if not os.access(path, os.W_OK):
        _icacls(str(path), "/reset")
        logger.warning("Restricting the credentials file made it unwritable; inherited permissions restored")


def _restrict(path: Path) -> None:
    if str(sys.platform) == "win32":
        _restrict_windows(path)
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        logger.warning("Could not restrict permissions on the credentials file", path=str(path), error=str(exc))


class CredentialStore:
    """Provider API keys on local disk, read once and cached in memory.

    Cached because ``available_providers()`` renders on every page load and asks
    whether each provider has a key.
    """

    def __init__(self, path: Path | None = None):
        self._path = path
        self._cache: dict[str, str] | None = None
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        # Resolved per access: this is a singleton, and tests pin the config dir
        # after import.
        return self._path or (config_dir() / CREDENTIALS_FILENAME)

    # ------------------------------------------------------------------ #
    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        with self._lock:
            if self._cache is None:
                self._cache = self._read()
            return self._cache

    def _read(self) -> dict[str, str]:
        path = self.path
        try:
            if not path.exists():
                return {}
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # A corrupt store means "no stored keys", never a failed request.
            logger.warning("Could not read stored credentials", path=str(path), error=str(exc))
            return {}
        keys = payload.get("api_keys") if isinstance(payload, dict) else None
        if not isinstance(keys, dict):
            return {}
        return {str(name): str(value) for name, value in keys.items() if isinstance(value, str) and value.strip()}

    def _write(self, keys: dict[str, str]) -> bool:
        path = self.path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Restricted before anything secret is in it, not just after.
            path.touch(exist_ok=True)
            _restrict(path)
            path.write_text(json.dumps({"api_keys": keys}, indent=2) + "\n", encoding="utf-8")
            _restrict(path)
        except OSError as exc:
            logger.error("Could not save credentials", path=str(path), error=str(exc))
            return False
        return True

    # ------------------------------------------------------------------ #
    def get(self, provider: str) -> str:
        """The stored key for ``provider``, or ``""``."""
        return self._load().get((provider or "").strip().lower(), "")

    def has(self, provider: str) -> bool:
        return bool(self.get(provider))

    def hint(self, provider: str) -> str:
        """A masked form of the key. The only representation that leaves the process."""
        key = self.get(provider)
        if not key:
            return ""
        return f"…{key[-HINT_CHARS:] if len(key) > HINT_CHARS else key}"

    def set(self, provider: str, key: str) -> bool:
        name = (provider or "").strip().lower()
        cleaned = (key or "").strip()
        if not name or not cleaned:
            return False
        with self._lock:
            keys = dict(self._read())
            keys[name] = cleaned
            if not self._write(keys):
                return False
            self._cache = keys
        logger.info("Stored an API key", provider=name)
        return True

    def delete(self, provider: str) -> bool:
        name = (provider or "").strip().lower()
        with self._lock:
            keys = dict(self._read())
            if name not in keys:
                self._cache = keys
                return False
            keys.pop(name)
            if not self._write(keys):
                return False
            self._cache = keys
        logger.info("Removed a stored API key", provider=name)
        return True

    def providers_with_keys(self) -> list[str]:
        return sorted(self._load())

    def reload(self) -> None:
        """Drops the cache so the next read goes back to disk."""
        with self._lock:
            self._cache = None


credential_store = CredentialStore()


__all__ = ["CREDENTIALS_FILENAME", "CredentialStore", "credential_store"]
