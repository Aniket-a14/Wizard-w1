"""What a sandboxed runtime is allowed to do, as data.

Deliberately platform-neutral and free of any enforcement: this is the one
description of the boundary, and Landlock, SBPL and a Windows token are three
renderings of it. Keeping it inert also makes it the part that can be tested
without spawning anything, which is most of what there is to get wrong -- a
writable root that escapes the workspace is a policy bug, not a syscall bug.

The policy travels to the child as a plain dict, so it must stay JSON-safe.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


#: Environment variables that name a directory a library will try to write to.
#: Matplotlib, fontconfig and pip all cache under the user's home, which is
#: outside every writable root a sandbox grants -- so an unredirected child gets
#: a permission error from `import matplotlib`, before any generated code runs.
CACHE_ENV_VARS = ("MPLCONFIGDIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "TMPDIR", "TEMP", "TMP")


@dataclass(frozen=True)
class SandboxPolicy:
    """One session's boundary."""

    #: Directories the child may create and modify files in.
    writable: tuple[str, ...]
    #: Directories the child may read. The interpreter and its libraries live
    #: here; without them the child cannot import anything at all.
    readable: tuple[str, ...]
    #: ``deny`` permits loopback only, which is what the daemon protocol needs.
    network: str = "deny"
    #: Address-space / process-memory ceiling in bytes. 0 means uncapped.
    mem_bytes: int = 0
    #: Ceiling on processes in the child's job. 0 means uncapped.
    max_processes: int = 0
    #: ``off`` / ``best-effort`` / ``require``.
    mode: str = "best-effort"
    #: Directory used for the caches redirected out of the user's home.
    cache_dir: str = ""
    #: Extra roots the user has consented to through the permission profile.
    extra_roots: tuple[str, ...] = field(default_factory=tuple)
    #: Windows only. Whether the child may lower its own integrity level.
    #: Set to ``False`` by ``plan_spawn`` when the parent could not label the
    #: workspace Low -- a Low-IL child in a Medium-IL workspace cannot write
    #: even its own pid file, so lowering integrity must not be attempted
    #: unless the label actually took.
    windows_lower_integrity: bool = True

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def required(self) -> bool:
        return self.mode == "require"

    def to_dict(self) -> dict:
        return {
            "writable": list(self.writable),
            "readable": list(self.readable),
            "network": self.network,
            "mem_bytes": self.mem_bytes,
            "max_processes": self.max_processes,
            "mode": self.mode,
            "cache_dir": self.cache_dir,
            "extra_roots": list(self.extra_roots),
            "windows_lower_integrity": self.windows_lower_integrity,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> SandboxPolicy:
        return cls(
            writable=tuple(payload.get("writable") or ()),
            readable=tuple(payload.get("readable") or ()),
            network=payload.get("network") or "deny",
            mem_bytes=int(payload.get("mem_bytes") or 0),
            max_processes=int(payload.get("max_processes") or 0),
            mode=payload.get("mode") or "best-effort",
            cache_dir=payload.get("cache_dir") or "",
            extra_roots=tuple(payload.get("extra_roots") or ()),
            windows_lower_integrity=bool(payload.get("windows_lower_integrity", True)),
        )

    def cache_environment(self) -> dict[str, str]:
        """Environment redirecting library caches into the workspace."""
        if not self.cache_dir:
            return {}
        return dict.fromkeys(CACHE_ENV_VARS, self.cache_dir)


def _interpreter_roots() -> tuple[str, ...]:
    """Directories the child must be able to read to be a Python at all.

    Taken from this interpreter rather than guessed, because the child runs the
    same one: a venv, a conda prefix and a system install put their libraries in
    three different places, and a hardcoded ``/usr/lib`` would break two of them.
    """
    roots: list[str] = [sys.prefix, sys.base_prefix, os.path.dirname(sys.executable)]
    roots.extend(path for path in sys.path if path)

    # The platform's shared libraries. Python itself links against libc, and on
    # Linux an extension module resolved through the dynamic loader needs the
    # loader's own search path readable.
    if sys.platform.startswith("linux"):
        roots.extend(["/usr", "/lib", "/lib64", "/etc", "/proc/self", "/dev/urandom", "/dev/null"])
    elif sys.platform == "darwin":
        roots.extend(["/usr", "/System", "/Library", "/private/var/db/dyld", "/opt", "/etc", "/dev/null"])

    resolved = []
    for root in roots:
        try:
            path = Path(root).resolve()
        except (OSError, ValueError):
            continue
        if path.exists() and str(path) not in resolved:
            resolved.append(str(path))
    return tuple(resolved)


def policy_for(workspace: Path, extra_roots: tuple[str, ...] = ()) -> SandboxPolicy:
    """Builds the policy for one session from settings and its workspace.

    ``extra_roots`` are directories the user consented to through the permission
    profile. They widen the sandbox for the same reason they widen the AST
    guard, and through the same decision -- the sandbox must not deny what the
    user was asked about and said yes to, or the grant would look broken.
    """
    from src.config import settings

    workspace = Path(workspace)
    cache_dir = workspace / ".cache"

    writable = [str(workspace)]
    writable.extend(str(Path(root)) for root in extra_roots)

    return SandboxPolicy(
        writable=tuple(dict.fromkeys(writable)),
        readable=_interpreter_roots(),
        network=settings.HOST_SANDBOX_NETWORK,
        mem_bytes=settings.host_runtime_mem_bytes,
        max_processes=settings.SANDBOX_PIDS_LIMIT,
        mode=settings.HOST_SANDBOX,
        cache_dir=str(cache_dir),
        extra_roots=tuple(extra_roots),
    )


__all__ = ["CACHE_ENV_VARS", "SandboxPolicy", "policy_for"]
