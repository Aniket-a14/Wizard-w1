"""Restricting a config file to the account that owns it.

Extracted from ``core/credentials.py`` when Milestone 4's ``connections.json``
needed the same treatment. Deliberately shared rather than copied: the Windows
half has one non-obvious rule in it -- grant to the SID read from the process
token, never to ``%USERNAME%`` -- and that rule was already got wrong once. A
second copy is a second chance to get it wrong.

Enforced on all three platforms rather than documented on two. Every failure
degrades to a warning and inherited permissions: a config file nobody can write
is a worse outcome than one with default permissions, and it would fail at
exactly the moment someone is trying to save something.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from src.utils.logging import logger


def _icacls(*args: str) -> bool:
    try:
        subprocess.run(  # noqa: S603 - fixed executable, arguments are not user input
            ["icacls", *args], check=True, capture_output=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def current_user_sid() -> str:
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


def _restrict_windows(path: Path, description: str) -> None:
    """Grants the running account sole access. ``os.chmod`` does not touch the ACL here.

    Verified afterwards, and rolled back if it went wrong.
    """
    sid = current_user_sid()
    if not sid:
        logger.warning(f"Could not identify the running account; {description} keeps inherited permissions")
        return

    if not _icacls(str(path), "/inheritance:r", "/grant:r", f"*{sid}:F"):
        logger.warning(f"Could not restrict permissions on the {description}", path=str(path))
        return

    if not os.access(path, os.W_OK):
        _icacls(str(path), "/reset")
        logger.warning(f"Restricting the {description} made it unwritable; inherited permissions restored")


def restrict(path: Path, description: str = "config file") -> None:
    """Makes ``path`` readable and writable only by the account that runs this process."""
    if str(sys.platform) == "win32":
        _restrict_windows(path, description)
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        logger.warning(f"Could not restrict permissions on the {description}", path=str(path), error=str(exc))


__all__ = ["current_user_sid", "restrict"]
