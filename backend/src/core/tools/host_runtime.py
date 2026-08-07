"""Host execution backend: one subprocess per session, no Docker required.

This is the default. Not everyone wants Docker, and on a laptop the daemon plus
a per-session image can cost more memory than the model does. This runs the
*same* daemon as the container backend in a child process talking over a
loopback socket, which buys back most of what a container was providing:

* a **persistent namespace**, so iteration 3 of an investigation can use what
  iteration 1 computed -- the in-process fallback rebuilt its globals on every
  call, which quietly broke the one thing the agentic loop is built around;
* a real **execution timeout**, because the socket deadline applies here too;
* a working **Stop button** -- the child is signalled directly;
* a **memory ceiling** on POSIX via ``RLIMIT_AS``;
* **crash isolation**: a segfault or a runaway allocation takes down the child,
  not the API process serving every other session.

Whether it is a *security* boundary depends on ``HOST_SANDBOX``. With it off the
child runs as the same user with the same filesystem access, and
:class:`CodeGuard` is the only thing between model output and the machine. With
it on, :mod:`src.core.security.sandbox` restricts the child through the OS --
Landlock and seccomp, an ``sandbox-exec`` profile, or a job object and a low
integrity level -- and the runtime reports back which of those actually took,
rather than the configuration being taken as evidence that they did.
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
from dataclasses import replace
from pathlib import Path

from src.config import settings
from src.core.security.sandbox import SpawnPlan, plan_spawn, policy_for
from src.core.security.sandbox.bootstrap import render_bootstrap
from src.core.tools.daemon import DaemonClient, find_free_port, render_daemon
from src.utils.logging import logger


class HostSession(DaemonClient):
    """One subprocess bound to one user session."""

    def __init__(self, session_id: str, workspace_dir: Path, extra_roots: tuple[str, ...] = ()):
        self.session_id = session_id
        self.workspace_dir = workspace_dir
        # Directories the user consented to. The sandbox must not deny what the
        # permission profile was asked about and allowed, or the grant reads as
        # broken.
        self.extra_roots = extra_roots
        self.process: subprocess.Popen | None = None
        self.port: int | None = None
        self.created_at = time.time()
        self._script_path: Path | None = None
        self._bootstrap_path: Path | None = None
        self._plan: SpawnPlan | None = None
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
                allow_pip=settings.SANDBOX_ALLOW_RUNTIME_PIP and settings.HOST_RUNTIME_ALLOW_PIP,
                workspace=str(self.workspace_dir),
                bind_host="127.0.0.1",
                mem_bytes=settings.host_runtime_mem_bytes,
            ),
            encoding="utf-8",
        )

        entry = self._script_path
        policy = policy_for(self.workspace_dir, self.extra_roots)
        if policy.enabled:
            entry = self.workspace_dir / ".runtime_bootstrap.py"
            self._bootstrap_path = entry

        # `plan_spawn` is what actually attempts the Windows workspace label
        # (a side effect of building the plan), so it must run *before* the
        # bootstrap is rendered -- the bootstrap's policy needs to know
        # whether that label took, not just what was requested.
        plan = plan_spawn(policy, [sys.executable, "-u", str(entry), str(self.port)], self.workspace_dir)
        self._plan = plan

        if policy.enabled:
            # The daemon is run *through* the bootstrap so the restrictions are
            # in force before it imports anything; it still ends up as
            # `__main__` in a process of its own, so nothing else changes.
            bootstrap_policy = policy
            if sys.platform == "win32" and "low-integrity" not in plan.mechanism:
                bootstrap_policy = replace(policy, windows_lower_integrity=False)
            entry.write_text(render_bootstrap(bootstrap_policy, self._script_path), encoding="utf-8")

        env = dict(os.environ)
        env["MPLBACKEND"] = "Agg"
        # The child inherits our interpreter but must not inherit our import
        # path assumptions: it only ever needs the third-party analysis stack.
        env.pop("PYTHONSTARTUP", None)
        # Matplotlib, fontconfig and pip cache under the user's home, which no
        # writable root covers -- so an unredirected child fails on `import
        # matplotlib`, before any generated code exists.
        env.update(plan.env)

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
                plan.argv,
                cwd=str(self.workspace_dir),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
                preexec_fn=preexec,  # noqa: PLW1509 - a new session, not an exec hook
            )
        except OSError as exc:
            logger.error("Could not spawn host runtime", session=self.session_id, error=str(exc))
            self.process = None
            raise

        if plan.adopt is not None:
            plan.adopt(self.process)

        if not self._wait_ready():
            detail = self._drain_startup_output()
            self.stop()
            raise RuntimeError(f"Host runtime did not start: {detail or 'no output'}")

        logger.info(
            "Host runtime started",
            session=self.session_id,
            port=self.port,
            pid=self.process.pid,
            sandbox=plan.mechanism,
            enforced=self._enforced_summary() if policy.enabled else "off",
        )

    def _enforced_summary(self) -> str:
        """What the child says actually took, asked of the child.

        The configuration is not evidence -- only the process that made the
        syscalls knows whether they succeeded, and a restriction that was
        refused must be visible somewhere the operator can find it.
        """
        report = self.sandbox_report()
        if not report:
            return "unreported"
        applied = sorted(name for name, entry in report.items() if (entry or {}).get("enforced"))
        refused = sorted(name for name, entry in report.items() if not (entry or {}).get("enforced"))
        parts = [f"+{','.join(applied)}" if applied else "+none"]
        if refused:
            parts.append(f"-{','.join(refused)}")
        return " ".join(parts)

    def _wait_ready(self) -> bool:
        """Waits for the daemon to listen, giving up early if the child died.

        The first start imports pandas and matplotlib, which on a cold page
        cache is seconds -- so the timeout is generous, but a child that has
        already exited is not waited on at all.
        """
        deadline = time.time() + settings.HOST_RUNTIME_START_TIMEOUT
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
            logger.info("Host runtime interrupt signalled", session=self.session_id)
            return True
        except (OSError, ValueError) as exc:
            logger.error("Failed to interrupt host runtime", session=self.session_id, error=str(exc))
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
        plan, self._plan = self._plan, None
        if plan is not None and plan.teardown is not None:
            plan.teardown()

        for path in (self._script_path, self._bootstrap_path, self.pid_file):
            try:
                if path is not None:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
        logger.info("Host runtime stopped", session=self.session_id)


class HostRuntimePool:
    """Creates and reaps one :class:`HostSession` per user session.

    Mirrors :class:`~src.core.tools.sandbox.SandboxPool` so
    :mod:`src.core.tools.runtime` can treat the two interchangeably.
    """

    def __init__(self):
        self._sessions: dict[str, HostSession] = {}
        self._lock = threading.Lock()
        atexit.register(self.shutdown)

    @property
    def available(self) -> bool:
        """True when this backend is permitted; spawning is only tried on use.

        There is nothing to probe -- a Python interpreter is by definition
        present -- so unlike Docker this cannot be usefully checked in advance.
        """
        return settings.host_backend_allowed

    def workspace_for(self, session_id: str) -> Path:
        from src.core.tools.sandbox import sandbox_pool

        return sandbox_pool.workspace_for(session_id)

    @staticmethod
    def _consented_roots(session_id: str) -> tuple[str, ...]:
        """Directories the permission profile has already granted this session.

        Read here rather than passed in, because a runtime is created lazily
        from several call sites and none of them holds the session. Imported
        inside the function: `core.session` imports this module's pool.

        A subagent's composite id is not a real key in `session_manager` -- it
        is resolved back to the owning session's id first, since permission
        grants are deliberately session-wide (see `SubagentSession`): a branch
        should see the same consented roots its parent already has, not none.
        """
        try:
            from src.core.session import session_manager
            from src.core.tools.runtime import is_subagent_id, parent_session_id

            real_id = parent_session_id(session_id) if is_subagent_id(session_id) else session_id
            session = session_manager.get(real_id)
            return tuple(session.permissions.extra_roots) if session is not None else ()
        except Exception:  # noqa: BLE001 - a missing session is not an error here
            return ()

    def get(self, session_id: str, create: bool = True) -> HostSession | None:
        session = self._sessions.get(session_id)
        if session is not None:
            # A child that died -- OOM-killed, or crashed on a bad extension --
            # must not be handed out as though it were live.
            if session.is_running or not create:
                return session
            logger.warning("Host runtime had exited; restarting", session=session_id)
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
            session = HostSession(session_id, self.workspace_for(session_id), self._consented_roots(session_id))
            try:
                session.start()
            except Exception as exc:
                logger.error("Failed to start host runtime", session=session_id, error=str(exc))
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


host_runtime_pool = HostRuntimePool()

__all__ = ["HostRuntimePool", "HostSession", "host_runtime_pool"]
