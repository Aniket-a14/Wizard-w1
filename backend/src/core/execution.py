"""The single path through which generated code reaches a Python interpreter.

Previously there were three: the sandbox, an in-process ``exec`` fallback in the
agent, and a *completely unguarded* ``exec`` in ``ScientificAgent.clean_dataset``
that ran on every upload. Only the first was checked. Everything now funnels
through :meth:`CodeExecutor.execute`, which guards first and executes second.

Which runtime serves a session is decided by :mod:`src.core.tools.runtime`: a
container, a local subprocess, or -- only when neither is permitted -- a guarded
``exec`` in this process. The first two are both fully supported; the third is
the genuinely degraded one and says so.
"""

from __future__ import annotations

import base64
import builtins
import io
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.config import settings
from src.core.security.code_guard import CodeGuard, GuardVerdict
from src.core.tools import runtime as runtime_backend
from src.utils.logging import logger


# Builtins removed from the local fallback namespace. This is a mitigation, not a
# boundary -- Docker is the boundary. Anything the guard already rejects will
# never get here.
BLOCKED_BUILTINS = frozenset(
    {"eval", "exec", "compile", "open", "input", "exit", "quit", "help", "__import__", "breakpoint"}
)


@dataclass
class ExecutionResult:
    output: str
    code: str
    image: str | None = None
    ok: bool = True
    blocked: bool = False
    blocked_reason: str = ""
    retryable_error: bool = False
    #: True only for a container. A local subprocess is isolated from the API
    #: process but is not a security boundary, so it does not claim to be one.
    sandboxed: bool = True
    #: Which backend actually ran this: ``docker`` / ``local`` / ``inprocess``.
    backend: str = "docker"
    warnings: list[str] = field(default_factory=list)

    @property
    def is_error(self) -> bool:
        return not self.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "ok": self.ok,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "sandboxed": self.sandboxed,
            "backend": self.backend,
            "has_image": self.image is not None,
            "warnings": self.warnings,
        }


class CodeExecutor:
    """Guards, repairs and runs generated Python for a given session."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    # ------------------------------------------------------------------ #
    def guard(self, code: str) -> tuple[GuardVerdict, str]:
        """Repairs then scans. Returns the verdict and the (possibly repaired) code.

        On a non-container backend the writable root is the session's own
        workspace directory rather than ``/workspace``, so it is passed in --
        otherwise the guard would reject the very chart path the prompt handed
        the model.
        """
        _, repaired = CodeGuard.repair(code)
        extra_roots: tuple[str, ...] = ()
        if runtime_backend.active_backend() != "docker":
            extra_roots = (runtime_backend.workspace_for(self.session_id).as_posix(),)
        return CodeGuard.scan(repaired, extra_roots=extra_roots), repaired

    def execute(
        self,
        code: str,
        df: pd.DataFrame | None = None,
        on_stdout: Callable[[str], None] | None = None,
        tables: dict[str, pd.DataFrame] | None = None,
    ) -> ExecutionResult:
        """Runs ``code``, preferring the container and falling back to in-process.

        ``tables`` matters only on the local path: the container reads every
        session table off its bind mount at startup, so passing them again would
        pay a full serialisation per call for something already there.
        """
        verdict, prepared = self.guard(code)
        backend = runtime_backend.active_backend()

        if not verdict.ok:
            if verdict.syntax_error:
                # Malformed output is the model's problem to fix; route it back
                # into the correction loop rather than reporting a policy block.
                return ExecutionResult(
                    output=f"Error executing code:\n{verdict.reason}",
                    code=prepared,
                    ok=False,
                    retryable_error=True,
                    sandboxed=backend == "docker",
                    backend=backend,
                )
            logger.warning("Execution blocked by guard", reason=verdict.reason, session=self.session_id)
            return ExecutionResult(
                output=f"This step was blocked by the safety guard: {verdict.reason}",
                code=prepared,
                ok=False,
                blocked=True,
                blocked_reason=verdict.reason,
                sandboxed=backend == "docker",
                backend=backend,
            )

        runtime = runtime_backend.get_runtime(self.session_id)
        if runtime is not None:
            output, image = runtime.run_code(prepared, on_stdout)
            failed = output.startswith("Error executing code:")
            return ExecutionResult(
                output=output,
                code=prepared,
                image=image,
                ok=not failed,
                retryable_error=failed,
                sandboxed=backend == "docker",
                backend=backend,
                # No warning for `local`: it is a supported way to run, and the
                # isolation actually in force is reported once on /settings
                # rather than restated on every message. Only the in-process
                # path below warns, because only it has no isolation at all.
            )

        return self._execute_locally(prepared, df, on_stdout, tables)

    # ------------------------------------------------------------------ #
    def _execute_locally(
        self,
        code: str,
        df: pd.DataFrame | None,
        on_stdout: Callable[[str], None] | None = None,
        tables: dict[str, pd.DataFrame] | None = None,
    ) -> ExecutionResult:
        """Last resort: guarded ``exec`` in the API process itself.

        Reached only when neither a container nor a subprocess can be had. The
        namespace does not persist between calls and nothing bounds the code, so
        this is the one path that genuinely warrants a warning.
        """
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        try:
            import seaborn as sns
        except ImportError:
            sns = None

        from src.core.tools.stats import StatisticalToolkit

        safe_builtins = {name: value for name, value in vars(builtins).items() if name not in BLOCKED_BUILTINS}
        namespace: dict[str, Any] = {
            "pd": pd,
            "np": np,
            "plt": plt,
            "sns": sns,
            "stats": StatisticalToolkit,
            # Always present, even when empty, so generated code can reference
            # `tables` unconditionally rather than guarding every use.
            "tables": {name: frame.copy() for name, frame in (tables or {}).items()},
            "__builtins__": safe_builtins,
        }
        if df is not None:
            namespace["df"] = df.copy()

        buffer = io.StringIO()
        original_stdout = sys.stdout
        warning = (
            "No isolated runtime was available, so this ran in a restricted interpreter "
            "inside the API process. Start Docker, or allow the local subprocess runtime, "
            "to restore isolation."
        )

        try:
            plt.close("all")
            sys.stdout = buffer
            exec(code, namespace)  # noqa: S102 - guarded above; Docker is the real boundary
            sys.stdout = original_stdout

            image = None
            if plt.get_fignums():
                image_buffer = io.BytesIO()
                plt.savefig(image_buffer, format="png", bbox_inches="tight", dpi=110)
                image_buffer.seek(0)
                image = base64.b64encode(image_buffer.read()).decode("utf-8")
                plt.close("all")

            output = buffer.getvalue().strip() or "Executed successfully."
            if on_stdout and output:
                on_stdout(output)
            return ExecutionResult(
                output=output,
                code=code,
                image=image,
                ok=True,
                sandboxed=False,
                backend="inprocess",
                warnings=[warning],
            )
        except Exception as exc:
            import traceback

            sys.stdout = original_stdout
            detail = traceback.format_exc(limit=6)
            logger.warning("Local execution failed", error=str(exc))
            return ExecutionResult(
                output=f"Error executing code:\n{detail}",
                code=code,
                ok=False,
                retryable_error=True,
                sandboxed=False,
                backend="inprocess",
                warnings=[warning],
            )
        finally:
            sys.stdout = original_stdout
            plt.close("all")

    # ------------------------------------------------------------------ #
    # Runtime control. All of these address an *existing* runtime only --
    # ``create=False`` -- because inspecting or resetting a session that has not
    # run anything should not be what brings a container up.
    # ------------------------------------------------------------------ #
    def _existing(self):
        return runtime_backend.get_runtime(self.session_id, create=False)

    @property
    def backend(self) -> str:
        return runtime_backend.active_backend()

    def inspect_variables(self) -> dict:
        runtime = self._existing()
        return runtime.inspect_variables() if runtime else {}

    def interrupt(self) -> bool:
        runtime = self._existing()
        return runtime.interrupt() if runtime else False

    def reload_dataset(self) -> bool:
        runtime = self._existing()
        return runtime.reload_dataset() if runtime else False

    def reset(self) -> bool:
        runtime = self._existing()
        return runtime.reset_namespace() if runtime else False

    def capabilities(self) -> frozenset[str]:
        """Modules generated code may import in this session's runtime."""
        return runtime_backend.capabilities(self.session_id)


def plot_output_path(session_id: str) -> str:
    """Path the worker is told to write interactive charts to.

    ``/workspace`` inside a container; the session's own directory for a local
    runtime, which is started with that directory as its working directory and
    as the daemon's ``WORKSPACE``.
    """
    return runtime_backend.workspace_path(session_id, "plot.html")


def host_plot_path(session_id: str):
    """Corresponding path on the host for the session's chart."""
    return runtime_backend.workspace_for(session_id) / "plot.html"


__all__ = ["CodeExecutor", "ExecutionResult", "plot_output_path", "host_plot_path", "settings"]
