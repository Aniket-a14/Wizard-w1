"""Local execution backend: one subprocess per session, no Docker required.

Not everyone wants Docker, and on a laptop the daemon plus a per-session image
can cost more memory than the model does. This runs the *same* daemon as the
container backend in a child process talking over a loopback socket, which buys
back most of what a container was providing:

* a **persistent namespace**, so iteration 3 of an investigation can use what
  iteration 1 computed -- the in-process fallback rebuilt its globals on every
  call, which quietly broke the one thing the agentic loop is built around;
* a real **execution timeout**, because the socket deadline applies here too;
* a working **Stop button** -- the child is signalled directly;
* a **memory ceiling** on POSIX via ``RLIMIT_AS``;
* **crash isolation**: a segfault or a runaway allocation takes down the child,
  not the API process serving every other session.

What it is not is a security boundary. The child runs as the same user with the
same filesystem access, so :class:`CodeGuard` is the only thing standing between
model output and the machine. Docker remains the right answer for untrusted
input; this is the right answer for running your own analysis on your own laptop.
"""

from __future__ import annotations

import atexit
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from src.config import settings
from src.core.tools.daemon import DaemonClient, find_free_port, render_daemon
from src.utils.logging import logger


class LocalSession(DaemonClient):
    """One subprocess bound to one user session."""

    def __init__(self, session_id: str, workspace_dir: Path):
        self.session_id = session_id
        self.workspace_dir = workspace_dir
        self.process: subprocess.Popen | None = None
        self.port: int | None = None
        self.created_at = time.time()
        self._script_path: Path | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def endpoint(self) -> tuple[str, int]:
        return "127.0.0.1", int(self.port or 0)

    @property
    def pid_file(self) -> Path:
        return self.workspace_dir / ".runtime.pid"

    # ------------------------------------------------------------------ #
    def start(self):
        if self.is_running:
            return

        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.port = find_free_port()
        self._script_path = self.workspace_dir / ".runtime_daemon.py"
        self._script_path.write_text(
            render_daemon(
                port=self.port,
                pid_file=str(self.pid_file),
                # Runtime pip would install into the *backend's* environment
                # here, not a throwaway container, so it is off unless the
                # operator opts in.
                allow_pip=settings.SANDBOX_ALLOW_RUNTIME_PIP and settings.LOCAL_RUNTIME_ALLOW_PIP,
                workspace=str(self.workspace_dir),
                bind_host="127.0.0.1",
                mem_bytes=settings.local_runtime_mem_bytes,
            ),
            encoding="utf-8",
        )

        env = dict(os.environ)
        env["MPLBACKEND"] = "Agg"
        # The child inherits our interpreter but must not inherit our import
        # path assumptions: it only ever needs the third-party analysis stack.
        env.pop("PYTHONSTARTUP", None)

        creation_flags = 0
        preexec = None
        if sys.platform == "win32":
            # A new process group is what makes CTRL_BREAK_EVENT deliverable to
            # the child alone; without it the signal would hit this process too.
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            preexec = os.setsid

        try:
            self.process = subprocess.Popen(
                [sys.executable, "-u", str(self._script_path), str(self.port)],
                cwd=str(self.workspace_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
                preexec_fn=preexec,  # noqa: PLW1509 - a new session, not an exec hook
            )
        except OSError as exc:
            logger.error("Could not spawn local runtime", session=self.session_id, error=str(exc))
            self.process = None
            raise

        if not self._wait_ready():
            detail = self._drain_startup_output()
            self.stop()
            raise RuntimeError(f"Local runtime did not start: {detail or 'no output'}")

        logger.info("Local runtime started", session=self.session_id, port=self.port, pid=self.process.pid)

    def _wait_ready(self) -> bool:
        """Waits for the daemon to listen, giving up early if the child died.

        The first start imports pandas and matplotlib, which on a cold page
        cache is seconds -- so the timeout is generous, but a child that has
        already exited is not waited on at all.
        """
        deadline = time.time() + settings.LOCAL_RUNTIME_START_TIMEOUT
        host, port = self.endpoint()
        while time.time() < deadline:
            if self.process is None or self.process.poll() is not None:
                return False
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.15)
        return False

    def _drain_startup_output(self, limit: int = 2000) -> str:
        """Whatever the child managed to say before failing."""
        if self.process is None or self.process.stdout is None:
            return ""
        try:
            self.process.stdout.flush()
        except Exception:
            pass
        try:
            # The child is dead or about to be killed, so this cannot block for
            # long; it is only ever read on the failure path.
            data = self.process.stdout.read(limit) or b""
        except Exception:
            return ""
        return data.decode("utf-8", "replace").strip() if isinstance(data, bytes) else str(data).strip()

    # ------------------------------------------------------------------ #
    def interrupt(self) -> bool:
        """Interrupts the running cell without killing the runtime.

        The daemon catches KeyboardInterrupt around ``exec`` and reports the
        execution as interrupted, so the namespace and the loaded frames survive
        -- which is the whole point of interrupting rather than restarting.
        """
        if not self.is_running or self.process is None:
            return False
        try:
            if sys.platform == "win32":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.kill(self.process.pid, signal.SIGINT)
            logger.info("Local runtime interrupt signalled", session=self.session_id)
            return True
        except (OSError, ValueError) as exc:
            logger.error("Failed to interrupt local runtime", session=self.session_id, error=str(exc))
            return False

    def stop(self):
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            except OSError:
                pass
        for handle in (getattr(process, "stdout", None),):
            try:
                if handle is not None:
                    handle.close()
            except Exception:
                pass
        for path in (self._script_path, self.pid_file):
            try:
                if path is not None:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        logger.info("Local runtime stopped", session=self.session_id)


class LocalRuntimePool:
    """Creates and reaps one :class:`LocalSession` per user session.

    Mirrors :class:`~src.core.tools.sandbox.SandboxPool` so
    :mod:`src.core.tools.runtime` can treat the two interchangeably.
    """

    def __init__(self):
        self._sessions: dict[str, LocalSession] = {}
        self._lock = threading.Lock()
        atexit.register(self.shutdown)

    @property
    def available(self) -> bool:
        """True when this backend is permitted; spawning is only tried on use.

        There is nothing to probe -- a Python interpreter is by definition
        present -- so unlike Docker this cannot be usefully checked in advance.
        """
        return settings.local_backend_allowed

    def workspace_for(self, session_id: str) -> Path:
        from src.core.tools.sandbox import sandbox_pool

        return sandbox_pool.workspace_for(session_id)

    def get(self, session_id: str, create: bool = True) -> LocalSession | None:
        session = self._sessions.get(session_id)
        if session is not None:
            # A child that died -- OOM-killed, or crashed on a bad extension --
            # must not be handed out as though it were live.
            if session.is_running or not create:
                return session
            logger.warning("Local runtime had exited; restarting", session=session_id)
            with self._lock:
                self._sessions.pop(session_id, None)
        elif not create:
            return None

        if not self.available:
            return None

        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None and existing.is_running:
                return existing
            session = LocalSession(session_id, self.workspace_for(session_id))
            try:
                session.start()
            except Exception as exc:
                logger.error("Failed to start local runtime", session=session_id, error=str(exc))
                session.stop()
                return None
            self._sessions[session_id] = session
            return session

    def release(self, session_id: str):
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.stop()

    def shutdown(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.stop()

    @property
    def active_count(self) -> int:
        return len(self._sessions)


local_runtime_pool = LocalRuntimePool()

__all__ = ["LocalRuntimePool", "LocalSession", "local_runtime_pool"]
