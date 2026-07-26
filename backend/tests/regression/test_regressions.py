"""Regression tests.

Each test here pins a defect found during the audit of the previous
implementation. The docstrings record what broke and why, so a future change
that reintroduces the behaviour fails with an explanation rather than a bare
assertion.
"""

from __future__ import annotations

import json
import threading

import pandas as pd

from src.api.deps import SlidingWindowRateLimiter
from src.config import Settings
from src.core.database import DatabaseManager
from src.core.execution import CodeExecutor
from src.core.ingest.loader import json_safe_records, sanitize_columns
from src.core.memory import working_memory
from src.core.reporting import ReportingEngine
from src.core.security.code_guard import CodeGuard
from src.core.session import Session, SessionManager
from src.core.tools.evaluator import Evaluator
from src.core.tools.sandbox import PID_FILE, SandboxSession


def test_report_endpoint_does_not_raise_attribute_error() -> None:
    """`ReportingEngine` read `working_memory.memories` as a plain list.

    The SQLite migration removed that attribute while the reporting engine still
    referenced it, so `GET /report` raised AttributeError and returned 500 on
    every single call.
    """
    report = ReportingEngine.generate_executive_summary(timespan_seconds=3600)
    assert isinstance(report, str)
    assert report

    # The compatibility property must also still resolve.
    assert isinstance(working_memory.memories, list)


def test_database_does_not_leak_connections(tmp_path) -> None:
    """`with sqlite3.connect(...)` commits a transaction; it does not close the
    connection. Every call leaked one until garbage collection, and without WAL
    or a busy timeout concurrent writers hit 'database is locked'.
    """
    manager = DatabaseManager(db_path=str(tmp_path / "leak.db"))
    for index in range(50):
        manager.save_feedback(f"task-{index}", "code")

    # One pooled connection per thread, not one per call.
    connection = manager._connection()
    assert manager._connection() is connection

    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode.lower() == "wal"
    manager.close()


def test_sanitized_columns_never_collide() -> None:
    """Stripping punctuation mapped distinct headers onto one name.

    `a-b` and `a.b` both became `ab`, producing duplicate column labels that
    later broke Feather serialisation and made column selection ambiguous.
    """
    columns, _ = sanitize_columns(["a-b", "a.b", "a b", "a/b", "a\\b"])
    assert len(columns) == len(set(columns))


def test_preview_records_are_json_serialisable(missing_values_df: pd.DataFrame) -> None:
    """`df.replace({float('nan'): None})` did not cover every dtype, so NaN and
    Inf reached the JSON encoder and `/data/preview` returned 500.
    """
    json.dumps(json_safe_records(missing_values_df))


def test_evaluator_ignores_the_word_error_in_prose() -> None:
    """Scoring matched the bare substring "Error", so any output mentioning it —
    including a column named `error_rate` — lost 50 points.
    """
    scored = Evaluator.score_execution("Mean error_rate is 0.01, variance is low.")
    assert scored["score"] >= 90


def test_sandbox_interrupt_targets_the_daemon_not_pid_one() -> None:
    """`interrupt()` sent `kill -2 1`, but PID 1 is the container's `sleep`
    command, so pressing Stop destroyed the sandbox instead of the running cell.
    The daemon now writes its own PID and is signalled directly.
    """

    class RecordingContainer:
        def __init__(self) -> None:
            self.commands: list[object] = []

        def exec_run(self, command):
            self.commands.append(command)
            return type("Result", (), {"exit_code": 0})()

    session = SandboxSession.__new__(SandboxSession)
    session.container = RecordingContainer()
    session.session_id = "test"

    assert session.interrupt() is True

    issued = " ".join(str(part) for part in session.container.commands[0])
    assert PID_FILE in issued, "the daemon's own PID file must be consulted"
    assert "kill -INT" in issued
    assert "kill -2 1" not in issued, "signalling PID 1 kills the container, not the cell"


def test_sandbox_run_code_takes_no_dataframe_payload() -> None:
    """`run_code(code, df_bytes, ...)` accepted a Feather-encoded frame and then
    ignored it, so every execution paid a full DataFrame serialisation for
    nothing. The dataset travels through the bind mount instead.
    """
    import inspect

    signature = inspect.signature(SandboxSession.run_code)
    assert "df_bytes" not in signature.parameters


def test_sandbox_daemon_source_is_valid_python() -> None:
    """The daemon lives in a string literal and only ever runs inside Docker, so
    a syntax error in it is invisible to every other test and to the type
    checker — it would surface as a container that silently never accepts
    connections.
    """
    import ast

    from src.core.tools.sandbox import DAEMON_PORT, DAEMON_SCRIPT

    for allow_pip in ("True", "False"):
        rendered = DAEMON_SCRIPT % {
            "port": DAEMON_PORT,
            "pid_file": PID_FILE,
            "allow_pip": allow_pip,
        }
        ast.parse(rendered)  # must not raise

    # The placeholders must all be substituted; a stray one would be a runtime
    # NameError inside the container.
    assert "%(" not in rendered


def test_rate_limiter_evicts_idle_clients() -> None:
    """The old limiter used an unbounded `defaultdict(list)` that was never
    swept, so every IP that ever connected stayed resident for the process
    lifetime.
    """
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=1, max_keys=10)
    for index in range(200):
        limiter.allow(f"client-{index}")

    assert len(limiter._hits) <= 10


def test_rate_limiter_blocks_past_the_threshold() -> None:
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
    assert all(limiter.allow("client") for _ in range(3))
    assert not limiter.allow("client")


def test_rate_limiter_is_thread_safe() -> None:
    limiter = SlidingWindowRateLimiter(max_requests=1000, window_seconds=60)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            for _ in range(200):
                limiter.allow("shared")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors


def test_cors_credentials_are_disabled_for_wildcard_origins() -> None:
    """`allow_origins=["*"]` with `allow_credentials=True` is rejected by every
    browser and is a spec violation. The two settings are now resolved together.
    """
    wildcard = Settings(CORS_ALLOW_ORIGINS="*")
    assert wildcard.cors_allow_credentials is False

    explicit = Settings(CORS_ALLOW_ORIGINS="http://localhost:3000")
    assert explicit.cors_allow_credentials is True


def test_sessions_do_not_share_a_sandbox_namespace() -> None:
    """A single global `state` dict plus one shared container meant a second
    user could read the first user's variables.
    """
    manager = SessionManager()
    first = manager.create()
    second = manager.create()

    assert first.id != second.id
    assert first.workspace != second.workspace
    assert first.executor.session_id != second.executor.session_id

    manager.drop(first.id)
    manager.drop(second.id)


def test_import_healing_runs_on_parseable_code() -> None:
    """Import healing was gated behind a SyntaxError, but a missing import is a
    runtime NameError and parses fine — so the branch could never fire.
    """
    parses, code = CodeGuard.repair("total = pd.Series([1, 2]).sum()\nprint(total)")
    assert parses
    assert "import pandas as pd" in code


def test_guard_blocks_open_self_traversal() -> None:
    """`open.__self__` reaches the builtins module; neither `__self__` nor
    `__dict__` was in the original attribute denylist.
    """
    assert not CodeGuard.scan("print(open.__self__.__dict__)").ok


def test_cleaning_path_is_guarded(loaded_session: Session) -> None:
    """`ScientificAgent.clean_dataset` called the builtin `exec()` directly in
    the API process, with no guard and no sandbox, on every upload — while the
    uploaded file's column names were already inside the prompt.
    """
    executor = CodeExecutor(loaded_session.id)
    result = executor.execute("import os\nos.system('id')", loaded_session.df)

    assert result.blocked
    assert not result.ok


def test_local_fallback_reports_that_it_is_degraded(loaded_session: Session) -> None:
    """Without Docker the executor still runs code, but the caller must be able
    to tell that isolation was not available."""
    result = CodeExecutor(loaded_session.id).execute("print(df.shape)", loaded_session.df)

    assert result.ok
    assert result.sandboxed is False
    assert any("Docker" in warning for warning in result.warnings)


def test_syntax_errors_are_retryable_not_policy_violations(loaded_session: Session) -> None:
    """Blocking and malformed output used to be conflated: both terminated the
    run as `completed`, so the model never got a chance to fix its own typo.
    """
    result = CodeExecutor(loaded_session.id).execute("print('unterminated", loaded_session.df)

    assert not result.ok
    assert result.retryable_error
    assert not result.blocked
