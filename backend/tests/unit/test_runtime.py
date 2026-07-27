"""Execution backends, the daemon source, and what the model is told it may import.

None of these start a container or spawn a subprocess. What is checked is the
part that used to be unverifiable: the daemon lives in a string literal, and the
toolkit the model is offered now comes from the runtime rather than from a list
maintained by hand against the Dockerfile.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.core.security.code_guard import CodeGuard
from src.core.tools import runtime as runtime_backend
from src.core.tools.daemon import PROBE_MODULES, render_daemon


# --------------------------------------------------------------------------- #
# Backend selection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("setting", "expected"),
    [("inprocess", "inprocess"), ("local", "local"), ("docker", "inprocess")],
)
def test_backend_selection_follows_the_setting(monkeypatch, setting: str, expected: str) -> None:
    """`docker` with no reachable daemon must not silently become `local`.

    Asking for a container and getting an unannounced subprocess would be a
    different isolation guarantee than the one that was requested.
    """
    monkeypatch.setattr("src.config.settings.EXECUTION_BACKEND", setting, raising=False)
    assert runtime_backend.active_backend() == expected


def test_auto_falls_back_to_local_when_there_is_no_docker(monkeypatch) -> None:
    monkeypatch.setattr("src.config.settings.EXECUTION_BACKEND", "auto", raising=False)
    assert runtime_backend.active_backend() == "local"


# --------------------------------------------------------------------------- #
# The daemon source
# --------------------------------------------------------------------------- #
def test_daemon_renders_to_valid_python_for_every_runtime() -> None:
    for allow_pip in (True, False):
        for mem_bytes in (0, 1 << 30):
            source = render_daemon(allow_pip=allow_pip, mem_bytes=mem_bytes, bind_host="127.0.0.1")
            ast.parse(source)
            assert "%(" not in source


def test_a_windows_workspace_path_does_not_break_the_daemon_source() -> None:
    """The local runtime passes a real host path into a string literal.

    On Windows that path contains backslashes, which would become escape
    sequences -- `\\t` in a username is a tab -- and at best mis-resolve, at
    worst fail to parse.
    """
    source = render_daemon(workspace="C:\\Users\\a b\\workspace\\sessions\\x")
    ast.parse(source)
    assert "C:/Users/a b/workspace/sessions/x" in source


def test_the_daemon_reads_tables_from_its_own_workspace() -> None:
    """The path was hardcoded to /workspace, which only exists in a container."""
    source = render_daemon(workspace="/tmp/session-x")
    assert 'WORKSPACE = "/tmp/session-x"' in source
    assert '"/workspace/tables"' not in source


# --------------------------------------------------------------------------- #
# Capabilities: what the model is told it may import
# --------------------------------------------------------------------------- #
DOCKERFILE = Path(__file__).resolve().parents[2] / "docker" / "Dockerfile"

#: Distribution name -> import name, for the few that differ.
IMPORT_NAMES = {
    "scikit-learn": "sklearn",
    "xgboost-cpu": "xgboost",
    "pillow": "PIL",
}


def _packages_per_tier() -> dict[str, set[str]]:
    """Reads the pinned packages out of each tier's layer in the Dockerfile."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    tiers = {"core": set(), "standard": set(), "full": set()}
    current = "core"
    for line in text.splitlines():
        if line.startswith("RUN if") and 'SANDBOX_TIER" = "full"' in line:
            current = "full"
        elif line.startswith("RUN if") and 'SANDBOX_TIER" != "core"' in line:
            current = "standard"
        elif line.startswith("RUN $PIP"):
            current = "core"
        match = re.search(r'"([A-Za-z0-9_.-]+)==', line)
        if match:
            name = match.group(1).lower()
            tiers[current].add(IMPORT_NAMES.get(name, name))
    # Tiers are cumulative in the image, so they are cumulative here too.
    tiers["standard"] |= tiers["core"]
    tiers["full"] |= tiers["standard"]
    return tiers


def test_declared_tiers_match_what_the_dockerfile_installs() -> None:
    """The prompt's library list and the image drifted apart twice before.

    scikit-learn and statsmodels were installed and unadvertised for months, so
    generated code hand-rolled statistics that were already there; duckdb was
    advertised into a process without it, costing a correction retry every time.
    The runtime now reports its own modules, but this table is what a prompt is
    built from before any runtime exists -- so it has to stay true.
    """
    installed = _packages_per_tier()
    for tier, modules in runtime_backend.TIER_MODULES.items():
        assert modules == installed[tier], f"{tier} tier disagrees with the Dockerfile"


def test_every_declared_module_is_one_the_daemon_probes_for() -> None:
    """A module absent from PROBE_MODULES can never be reported as available."""
    for modules in runtime_backend.TIER_MODULES.values():
        assert modules <= set(PROBE_MODULES)


def test_the_toolkit_block_only_offers_what_is_importable(monkeypatch) -> None:
    from src.core import prompts

    monkeypatch.setattr(prompts, "_toolkit_block", prompts._toolkit_block)
    monkeypatch.setattr(
        "src.core.tools.runtime.capabilities",
        lambda session_id=None: frozenset({"pandas", "numpy", "matplotlib"}),
    )
    block = prompts._toolkit_block("session")

    assert "pandas" in block
    assert "duckdb" not in block
    assert "scikit-learn" not in block
    assert "Do not import a library that is not listed above." in block


def test_plotting_rules_do_not_ask_for_a_library_that_is_absent(monkeypatch) -> None:
    """PLOT_FORMAT=html needs plotly, and the `core` image tier has no plotly.

    Telling the worker to import it there would guarantee a failed step on the
    first chart of every run.
    """
    from src.core import prompts

    monkeypatch.setattr("src.config.settings.PLOT_FORMAT", "html", raising=False)
    monkeypatch.setattr(
        "src.core.tools.runtime.capabilities",
        lambda session_id=None: frozenset({"pandas", "matplotlib"}),
    )
    assert "matplotlib" in prompts._visualization_rules("session")

    monkeypatch.setattr(
        "src.core.tools.runtime.capabilities",
        lambda session_id=None: frozenset({"pandas", "matplotlib", "plotly"}),
    )
    assert "plotly" in prompts._visualization_rules("session").lower()


# --------------------------------------------------------------------------- #
# The guard has to follow the runtime's workspace
# --------------------------------------------------------------------------- #
def test_the_guard_accepts_the_workspace_the_local_runtime_actually_uses() -> None:
    """Without this the guard rejects the chart path the prompt itself supplied.

    A container works out of /workspace; a local runtime works out of the
    session's own directory, which on Windows is a drive-letter path that
    `posixpath.isabs` does not recognise.
    """
    root = "C:/3rd_Year/Wizard-w1/workspace/sessions/abc"
    code = f"df.to_csv('{root}/out.csv')"

    assert CodeGuard.scan(code).ok is False
    assert CodeGuard.scan(code, extra_roots=(root,)).ok is True


def test_widening_the_workspace_does_not_widen_anything_else() -> None:
    allowed = ("/srv/session",)
    assert CodeGuard.scan("df.to_csv('/etc/passwd')", extra_roots=allowed).ok is False
    assert CodeGuard.scan("open('/srv/session/../../etc/shadow')", extra_roots=allowed).ok is False
    # /workspace stays valid: the extra root is added to the list, not swapped in.
    assert CodeGuard.scan("df.to_csv('/workspace/out.csv')", extra_roots=allowed).ok is True
