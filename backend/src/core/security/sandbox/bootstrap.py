"""The script the sandboxed child runs instead of the daemon directly.

It applies the pre-bind restrictions, leaves the post-bind network seal where
the daemon can reach it, and then runs the daemon in the same process. Two
consequences are load-bearing:

* the daemon still ends up as ``__main__`` in a process of its own, so nothing
  about the existing protocol, PID file or interrupt handling changes;
* :mod:`child` is loaded **by path**, so the child never imports ``src`` and a
  sandbox that has already denied the repository directory cannot break its own
  bootstrap.

Rendered with ``%r`` for every path, for the reason ``render_daemon`` documents:
a Windows path inside a quoted literal is a set of escape sequences.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.security.sandbox.policy import SandboxPolicy


BOOTSTRAP_SCRIPT = """
import builtins
import importlib.util
import json
import runpy
import sys

POLICY = json.loads(%(policy)r)
CHILD_MODULE = %(child_module)r
DAEMON = %(daemon)r

_spec = importlib.util.spec_from_file_location("wizard_sandbox_child", CHILD_MODULE)
_child = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_child)

# What was actually applied, read back by the daemon's `capabilities` action so
# the parent reports enforcement rather than intent.
builtins.__wizard_sandbox__ = _child.apply_policy(POLICY)
builtins.__wizard_seal__ = lambda: _child.seal_network(POLICY)

sys.argv = [DAEMON] + sys.argv[1:]
runpy.run_path(DAEMON, run_name="__main__")
"""


def render_bootstrap(policy: SandboxPolicy, daemon_path: Path | str) -> str:
    """Renders the bootstrap for one runtime."""
    child_module = Path(__file__).with_name("child.py")
    return BOOTSTRAP_SCRIPT % {
        "policy": json.dumps(policy.to_dict()),
        "child_module": str(child_module),
        "daemon": str(daemon_path),
    }


__all__ = ["BOOTSTRAP_SCRIPT", "render_bootstrap"]
