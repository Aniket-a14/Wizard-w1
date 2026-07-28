"""Chooses which execution backend serves a session, and reports what it can do.

Two supported backends and one last resort:

===========  ====================================================================
docker       A container per session. Real isolation; needs a daemon and an image.
local        A subprocess per session. No Docker, still a separate process.
inprocess    Guarded ``exec`` in the API process. No isolation; CI and locked-down
             environments only.
===========  ====================================================================

``EXECUTION_BACKEND=auto`` prefers Docker and falls back to local, which is what
someone who simply has not installed Docker should get -- rather than the
in-process interpreter with a warning banner on every message, which is what
they used to get.

The choice is made per call rather than cached, because Docker can appear or
disappear while the app is running and the answer to "where does code run" has
to stay true rather than reflect what was true at boot.
"""

from __future__ import annotations

from functools import lru_cache

from src.config import settings
from src.core.tools.daemon import PROBE_MODULES, DaemonClient


#: Backend names in the order ``auto`` prefers them.
BackendName = str


def active_backend() -> BackendName:
    """Which backend a new session would use right now.

    ``inprocess`` is reported when neither real backend is permitted, which is
    an honest answer rather than a fallback hidden behind an availability flag.
    """
    if settings.EXECUTION_BACKEND == "inprocess":
        return "inprocess"

    from src.core.tools.sandbox import sandbox_pool

    if settings.docker_backend_allowed and sandbox_pool.available:
        return "docker"
    if settings.local_backend_allowed:
        return "local"
    return "inprocess"


def get_runtime(session_id: str, create: bool = True) -> DaemonClient | None:
    """The live runtime for a session, or ``None`` when there is no daemon.

    A ``None`` here is not an error: it means execution falls through to the
    in-process interpreter, which :class:`~src.core.execution.CodeExecutor`
    handles.
    """
    backend = active_backend()

    if backend == "docker":
        from src.core.tools.sandbox import sandbox_pool

        return sandbox_pool.get(session_id, create=create)

    if backend == "local":
        from src.core.tools.local_runtime import local_runtime_pool

        runtime = local_runtime_pool.get(session_id, create=create)
        if runtime is not None or not create:
            return runtime
        # Spawning failed -- a locked-down host, no interpreter on PATH. The
        # in-process interpreter still works, so the session degrades instead
        # of failing outright.
        from src.utils.logging import logger

        logger.warning("Local runtime unavailable; falling back to in-process execution", session=session_id)
        return None

    return None


def release_runtime(session_id: str) -> None:
    """Releases whatever this session holds, in either backend.

    Both pools are asked rather than only the active one: the backend can change
    while a session is alive, and a container left behind by the previous choice
    would otherwise leak until the process exits.
    """
    from src.core.tools.local_runtime import local_runtime_pool
    from src.core.tools.sandbox import sandbox_pool

    sandbox_pool.release(session_id)
    local_runtime_pool.release(session_id)


def workspace_for(session_id: str):
    from src.core.tools.sandbox import sandbox_pool

    return sandbox_pool.workspace_for(session_id)


def workspace_path(session_id: str | None, filename: str = "") -> str:
    """A path inside the session workspace **as the running backend sees it**.

    A container is always at ``/workspace``; a local runtime works out of the
    session's own directory. Any code that builds a path for generated Python to
    write to has to go through here, because the two are not interchangeable:
    on the local backend ``/workspace/cleaned.csv`` resolves to a directory that
    does not exist, and pandas raises rather than writing anywhere useful.

    That is not hypothetical -- it silently disabled semantic cleaning and CSV
    export on every Docker-less install until it was caught by running one.
    """
    root = "/workspace"
    if active_backend() != "docker" and session_id:
        root = workspace_for(session_id).as_posix()
    return f"{root}/{filename}" if filename else f"{root}/"


def active_runtime_count() -> int:
    from src.core.tools.local_runtime import local_runtime_pool
    from src.core.tools.sandbox import sandbox_pool

    return sandbox_pool.active_count + local_runtime_pool.active_count


@lru_cache(maxsize=1)
def _local_modules() -> frozenset[str]:
    """Modules importable in *this* process, probed once.

    Used for the in-process interpreter, and as the answer for a local runtime
    that has not been started yet -- it is the same interpreter, so the set is
    the same without paying to spawn a child to be told so.
    """
    from importlib.util import find_spec

    available = set()
    for name in PROBE_MODULES:
        try:
            if find_spec(name) is not None:
                available.add(name)
        except (ImportError, ValueError, AttributeError):
            continue
    return frozenset(available)


#: Cached per session: a container's library set cannot change under it, and
#: this is consulted on every prompt build.
_capability_cache: dict[str, frozenset[str]] = {}


def capabilities(session_id: str | None = None) -> frozenset[str]:
    """Modules generated code may actually import, as reported by the runtime.

    This replaced a hand-maintained list in ``prompts.TOOLKIT`` that had to be
    edited in step with the Dockerfile and twice was not -- scikit-learn and
    statsmodels went unadvertised for months, and duckdb was advertised to a
    process that did not have it, which cost a correction retry every time.

    Never raises and never blocks for long: an unreachable runtime yields this
    process's own module set, which is the better wrong answer of the two.
    """
    backend = active_backend()
    if backend != "docker" or not session_id:
        return _local_modules()

    cached = _capability_cache.get(session_id)
    if cached is not None:
        return cached

    runtime = get_runtime(session_id, create=False)
    if runtime is None:
        # Do not start a container merely to build a prompt; the image is built
        # from a known tier, so the declared set is a sound answer until a real
        # runtime exists to correct it.
        return tier_modules()

    reported = runtime.capabilities()
    resolved = reported or tier_modules()
    _capability_cache[session_id] = resolved
    return resolved


def forget_capabilities(session_id: str) -> None:
    _capability_cache.pop(session_id, None)


#: What each sandbox image tier installs. Mirrors `backend/docker/Dockerfile`,
#: and is only a fallback for "the container is not up yet" -- once a runtime
#: exists, its own report wins.
TIER_MODULES: dict[str, frozenset[str]] = {
    "core": frozenset({"pandas", "numpy", "pyarrow", "matplotlib", "duckdb", "openpyxl"}),
    "standard": frozenset(
        {
            "pandas",
            "numpy",
            "pyarrow",
            "matplotlib",
            "duckdb",
            "openpyxl",
            "scipy",
            "statsmodels",
            "sklearn",
            "xgboost",
            "lightgbm",
            "plotly",
            "seaborn",
            "networkx",
            "PIL",
            "xlsxwriter",
            "tabulate",
        }
    ),
}
TIER_MODULES["full"] = TIER_MODULES["standard"] | {"lifelines", "geopandas", "shapely"}


def tier_modules() -> frozenset[str]:
    return TIER_MODULES.get(settings.SANDBOX_TIER, TIER_MODULES["standard"])


__all__ = [
    "TIER_MODULES",
    "active_backend",
    "active_runtime_count",
    "capabilities",
    "forget_capabilities",
    "get_runtime",
    "release_runtime",
    "tier_modules",
    "workspace_for",
    "workspace_path",
]
