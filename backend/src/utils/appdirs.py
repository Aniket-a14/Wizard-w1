"""Where Wizard keeps configuration that is not part of the checkout.

An API key belongs to the person, not to the clone, so it lives in the platform's
own configuration location rather than in ``backend/.env``. Milestone 8's CLI
manages the same directory, so this is the only place the answer is computed.

``WIZARD_CONFIG_DIR`` overrides everything; the test suite pins it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Wizard"


def config_dir() -> Path:
    """Wizard's user-level configuration directory. Not created here."""
    override = os.environ.get("WIZARD_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    # Read into a local: type checkers narrow `sys.platform` to the analysing
    # machine and call the other branches dead code.
    platform = str(sys.platform)

    if platform == "win32":
        base = os.environ.get("APPDATA", "").strip()
        return Path(base) / APP_NAME if base else Path.home() / "AppData" / "Roaming" / APP_NAME

    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / APP_NAME.lower()


def ensure_config_dir() -> Path:
    """:func:`config_dir`, created if it does not exist."""
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


__all__ = ["APP_NAME", "config_dir", "ensure_config_dir"]
