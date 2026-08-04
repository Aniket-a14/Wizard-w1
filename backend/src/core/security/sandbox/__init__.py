"""OS-level containment for the host execution backend.

The AST guard in :mod:`src.core.security.code_guard` is unchanged and still runs
first; this is the layer beneath it, and with Docker now opt-in it is what stands
between generated code and the machine on a default install.

Deliberately split so the majority is testable without spawning anything:
:mod:`policy` is inert data, :mod:`profiles` generates platform artifacts as
pure functions, :mod:`capability` reports what this machine supports and why
not, :mod:`spawn` decorates the launch, and :mod:`child` is the only part that
actually restricts a running process -- loaded by path, importing nothing from
``src``.
"""

from src.core.security.sandbox.capability import Feature, SandboxCapability, detect
from src.core.security.sandbox.policy import SandboxPolicy, policy_for
from src.core.security.sandbox.spawn import SandboxUnavailableError, SpawnPlan, plan_spawn


__all__ = [
    "Feature",
    "SandboxCapability",
    "SandboxPolicy",
    "SandboxUnavailableError",
    "SpawnPlan",
    "detect",
    "plan_spawn",
    "policy_for",
]
