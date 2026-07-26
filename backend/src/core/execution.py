"""The single path through which generated code reaches a Python interpreter.

Previously there were three: the sandbox, an in-process ``exec`` fallback in the
agent, and a *completely unguarded* ``exec`` in ``ScientificAgent.clean_dataset``
that ran on every upload. Only the first was checked. Everything now funnels
through :meth:`CodeExecutor.execute`, which guards first and executes second.

The local fallback is retained (it is what makes the app usable without Docker)
but is now restricted and clearly reported as degraded, rather than silently
running arbitrary model output in the API process.
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
from src.core.tools.sandbox import sandbox_pool
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
    sandboxed: bool = True
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
            "has_image": self.image is not None,
            "warnings": self.warnings,
        }


class CodeExecutor:
    """Guards, repairs and runs generated Python for a given session."""

    def __init__(self, session_id: str):
        self.session_id = session_id

    # ------------------------------------------------------------------ #
    def guard(self, code: str) -> tuple[GuardVerdict, str]:
        """Repairs then scans. Returns the verdict and the (possibly repaired) code."""
        _, repaired = CodeGuard.repair(code)
        return CodeGuard.scan(repaired), repaired

    def execute(
        self,
        code: str,
        df: pd.DataFrame | None = None,
        on_stdout: Callable[[str], None] | None = None,
    ) -> ExecutionResult:
        """Runs ``code``, preferring the container and falling back to in-process."""
        verdict, prepared = self.guard(code)

        if not verdict.ok:
            if verdict.syntax_error:
                # Malformed output is the model's problem to fix; route it back
                # into the correction loop rather than reporting a policy block.
                return ExecutionResult(
                    output=f"Error executing code:\n{verdict.reason}",
                    code=prepared,
                    ok=False,
                    retryable_error=True,
                    sandboxed=sandbox_pool.available,
                )
            logger.warning("Execution blocked by guard", reason=verdict.reason, session=self.session_id)
            return ExecutionResult(
                output=f"This step was blocked by the safety guard: {verdict.reason}",
                code=prepared,
                ok=False,
                blocked=True,
                blocked_reason=verdict.reason,
                sandboxed=sandbox_pool.available,
            )

        session = sandbox_pool.get(self.session_id) if sandbox_pool.available else None
        if session is not None:
            output, image = session.run_code(prepared, on_stdout)
            failed = output.startswith("Error executing code:")
            return ExecutionResult(
                output=output,
                code=prepared,
                image=image,
                ok=not failed,
                retryable_error=failed,
                sandboxed=True,
            )

        logger.warning("Docker unavailable; running in degraded local mode", session=self.session_id)
        return self._execute_locally(prepared, df, on_stdout)

    # ------------------------------------------------------------------ #
    def _execute_locally(
        self,
        code: str,
        df: pd.DataFrame | None,
        on_stdout: Callable[[str], None] | None = None,
    ) -> ExecutionResult:
        """In-process fallback used only when Docker is unreachable."""
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
            "__builtins__": safe_builtins,
        }
        if df is not None:
            namespace["df"] = df.copy()

        buffer = io.StringIO()
        original_stdout = sys.stdout
        warning = "Docker is unavailable, so this ran in a restricted local interpreter instead of the sandbox."

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
            return ExecutionResult(output=output, code=code, image=image, ok=True, sandboxed=False, warnings=[warning])
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
                warnings=[warning],
            )
        finally:
            sys.stdout = original_stdout
            plt.close("all")

    # ------------------------------------------------------------------ #
    def inspect_variables(self) -> dict:
        session = sandbox_pool.get(self.session_id, create=False)
        return session.inspect_variables() if session else {}

    def interrupt(self) -> bool:
        session = sandbox_pool.get(self.session_id, create=False)
        return session.interrupt() if session else False

    def reload_dataset(self) -> bool:
        session = sandbox_pool.get(self.session_id, create=False)
        return session.reload_dataset() if session else False

    def reset(self) -> bool:
        session = sandbox_pool.get(self.session_id, create=False)
        return session.reset_namespace() if session else False


def plot_output_path(session_id: str) -> str:
    """Path the worker is told to write interactive charts to, inside the container."""
    return "/workspace/plot.html"


def host_plot_path(session_id: str):
    """Corresponding path on the host for the session's chart."""
    return sandbox_pool.workspace_for(session_id) / "plot.html"


__all__ = ["CodeExecutor", "ExecutionResult", "plot_output_path", "host_plot_path", "settings"]
