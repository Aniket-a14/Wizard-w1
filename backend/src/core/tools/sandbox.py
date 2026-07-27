"""Stateful Docker sandbox for executing model-generated Python.

Changes from the previous implementation
----------------------------------------
* **Lazy, not import-time.** ``SandboxManager()`` used to build an image and start
  a container as a side effect of importing ``src.api.api``. That made every test
  run and every CI job depend on a Docker daemon. Containers are now created on
  first use and only when ``SANDBOX_ENABLED`` is true.
* **Per-session containers.** One shared container meant one shared ``exec_globals``
  namespace: any user could read another user's variables. Each session now gets
  its own container and its own bind-mounted workspace subdirectory.
* **Interrupt actually interrupts.** ``interrupt()`` sent ``kill -2 1``, but PID 1
  is the container's ``sleep`` command, not the daemon -- pressing Stop destroyed
  the sandbox. The daemon now records its own PID and is signalled directly.
* **No redundant serialisation.** ``run_code`` accepted a Feather-encoded frame it
  then ignored, so every execution paid a full DataFrame serialisation for
  nothing. The dataset is passed through the bind mount instead.
* **Resource limits.** Memory, PID and CPU caps plus ``no-new-privileges`` and
  dropped capabilities, so runaway generated code cannot exhaust the host.
* **Execution timeout.** A socket deadline bounds any single execution.
"""

from __future__ import annotations

import atexit
import io
import json
import os
import socket
import struct
import tarfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from src.config import settings
from src.utils.logging import logger


DAEMON_PATH = "/tmp/wizard_sandbox_daemon.py"
PID_FILE = "/tmp/wizard_sandbox_daemon.pid"
DAEMON_PORT = 5005

# Runs inside the container. Kept as a string so it can be injected into a
# generic python image without rebuilding when it changes.
DAEMON_SCRIPT = '''
import base64
import io
import json
import os
import socket
import struct
import subprocess
import sys
import traceback

PID_FILE = "%(pid_file)s"
ALLOW_PIP = %(allow_pip)s


def recvall(sock, n):
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data


def read_message(sock):
    header = recvall(sock, 4)
    if not header:
        return None
    length = struct.unpack(">I", header)[0]
    payload = recvall(sock, length)
    if not payload:
        return None
    return json.loads(payload.decode("utf-8"))


def send_message(sock, payload):
    raw = json.dumps(payload).encode("utf-8")
    sock.sendall(struct.pack(">I", len(raw)) + raw)


class StreamingStdout:
    """Mirrors writes to the client socket so the UI sees output live."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = io.StringIO()

    def write(self, text):
        self.buf.write(text)
        try:
            raw = json.dumps({"status": "stdout", "content": text}).encode("utf-8")
            self.sock.sendall(struct.pack(">I", len(raw)) + raw)
        except Exception:
            pass
        return len(text)

    def flush(self):
        pass

    def getvalue(self):
        return self.buf.getvalue()


def load_dataset(exec_globals, pd):
    """Binds `df` to the active table and `tables` to every loaded table.

    Cross-table questions are the common case for a real analytical request, so
    every table the session holds is in the namespace at once. `df` stays bound
    to the active one, which is what every existing prompt, cache entry and
    generated script already assumes.
    """
    tables = {}
    tables_dir = "/workspace/tables"
    if os.path.isdir(tables_dir):
        for entry in sorted(os.listdir(tables_dir)):
            if not entry.endswith(".feather"):
                continue
            key = entry[: -len(".feather")]
            try:
                tables[key] = pd.read_feather(os.path.join(tables_dir, entry))
            except Exception as exc:
                print("Could not load table " + key + ": " + str(exc))
    exec_globals["tables"] = tables
    if tables:
        print("Tables available: " + ", ".join(sorted(tables)))

    for filename, reader in (
        ("/workspace/dataset.feather", pd.read_feather),
        ("/workspace/dataset.parquet", pd.read_parquet),
        ("/workspace/dataset.csv", pd.read_csv),
    ):
        if os.path.exists(filename):
            try:
                exec_globals["df"] = reader(filename)
                print("Dataset loaded from " + os.path.basename(filename))
                return
            except Exception as exc:
                print("Could not load " + filename + ": " + str(exc))
    print("No dataset present yet.")


def install_missing(module_name):
    # Import name -> distribution name, for the cases where they differ. A
    # missing entry is not a problem: the import name is tried as-is, which is
    # correct for the large majority of packages.
    mapping = {
        "sklearn": "scikit-learn",
        "bs4": "beautifulsoup4",
        "yaml": "pyyaml",
        "PIL": "pillow",
        "docx": "python-docx",
        "cv2": "opencv-python-headless",
        "dateutil": "python-dateutil",
        "sqlalchemy": "SQLAlchemy",
        "skimage": "scikit-image",
        "statsmodels.api": "statsmodels",
        "mpl_toolkits": "matplotlib",
        "pyarrow.parquet": "pyarrow",
        "Levenshtein": "python-Levenshtein",
        "fuzzywuzzy": "fuzzywuzzy",
        "wordcloud": "wordcloud",
        "umap": "umap-learn",
        "shap": "shap",
        "prophet": "prophet",
        "pmdarima": "pmdarima",
        "arch": "arch",
        "geopy": "geopy",
        "folium": "folium",
    }
    package = mapping.get(module_name, module_name)
    print("[sandbox] installing missing package: " + package)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--quiet", "--disable-pip-version-check", package],
        timeout=180,
    )


def describe(value, pd):
    type_name = type(value).__name__
    shape = None
    preview = ""
    try:
        if isinstance(value, pd.DataFrame):
            shape = list(value.shape)
            preview = "Columns: " + str(list(value.columns[:8]))
        elif isinstance(value, pd.Series):
            shape = list(value.shape)
            preview = "Name: " + str(value.name) + ", dtype: " + str(value.dtype)
        elif hasattr(value, "shape"):
            shape = list(value.shape)
            preview = str(value)[:120]
        elif isinstance(value, (list, dict, set, tuple)):
            shape = len(value)
            preview = str(value)[:120]
        else:
            preview = str(value)[:120]
    except Exception:
        preview = "<unrepresentable>"
    return {"type": type_name, "shape": shape, "preview": preview}


def run_server(port=%(port)d):
    with open(PID_FILE, "w") as handle:
        handle.write(str(os.getpid()))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    try:
        import seaborn as sns
    except Exception:
        sns = None

    exec_globals = {"pd": pd, "np": np, "plt": plt, "sns": sns, "__builtins__": __builtins__}
    load_dataset(exec_globals, pd)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", port))
    server.listen(4)
    print("Sandbox daemon listening on port " + str(port))
    sys.stdout.flush()

    while True:
        conn = None
        try:
            conn, _ = server.accept()
            payload = read_message(conn)
            if not payload:
                conn.close()
                continue

            action = payload.get("action", "execute")

            if action == "ping":
                send_message(conn, {"status": "success", "pong": True})
                conn.close()
                continue

            if action == "reload_dataset":
                load_dataset(exec_globals, pd)
                send_message(conn, {"status": "success"})
                conn.close()
                continue

            if action == "reset":
                exec_globals.clear()
                exec_globals.update(
                    {"pd": pd, "np": np, "plt": plt, "sns": sns, "__builtins__": __builtins__}
                )
                load_dataset(exec_globals, pd)
                send_message(conn, {"status": "success"})
                conn.close()
                continue

            if action == "inspect_variables":
                info = {}
                for name, value in list(exec_globals.items()):
                    if name.startswith("__"):
                        continue
                    if type(value).__name__ in ("module", "function", "builtin_function_or_method", "type"):
                        continue
                    info[name] = describe(value, pd)
                send_message(conn, {"status": "success", "variables": info})
                conn.close()
                continue

            code = payload.get("code", "")
            stdout_stream = StreamingStdout(conn)
            stderr_buffer = io.StringIO()
            real_stdout, real_stderr = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = stdout_stream, stderr_buffer

            plot_data = None
            status = "success"
            try:
                plt.close("all")
                try:
                    exec(code, exec_globals)
                except ModuleNotFoundError as exc:
                    if not ALLOW_PIP:
                        raise
                    install_missing(exc.name)
                    exec(code, exec_globals)

                if plt.get_fignums():
                    buffer = io.BytesIO()
                    plt.savefig(buffer, format="png", bbox_inches="tight", dpi=110)
                    buffer.seek(0)
                    plot_data = base64.b64encode(buffer.read()).decode("utf-8")
                    plt.close("all")
            except KeyboardInterrupt:
                status = "interrupted"
                print("Execution interrupted.", file=stderr_buffer)
            except BaseException:
                status = "error"
                stderr_buffer.write(traceback.format_exc())
            finally:
                sys.stdout, sys.stderr = real_stdout, real_stderr

            send_message(
                conn,
                {
                    "status": status,
                    "stdout": "",
                    "stderr": stderr_buffer.getvalue(),
                    "plot": plot_data,
                },
            )
            conn.close()
        except Exception:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    run_server()
'''


class SandboxUnavailableError(RuntimeError):
    """Raised when a sandbox is required but Docker cannot provide one."""


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return int(sock.getsockname()[1])


def _in_container() -> bool:
    return os.path.exists("/.dockerenv")


def _connect_host() -> str:
    """Address the backend uses to reach a published sandbox port."""
    return "host.docker.internal" if _in_container() else "127.0.0.1"


def _bind_host() -> str:
    """Interface the sandbox port is published on."""
    return "0.0.0.0" if _in_container() else "127.0.0.1"


class SandboxSession:
    """One container bound to one user session."""

    IMAGE_NAME = "wizard-sandbox:latest"

    def __init__(self, client, session_id: str, workspace_dir: Path):
        self.client = client
        self.session_id = session_id
        self.workspace_dir = workspace_dir
        self.container = None
        self.port: int | None = None
        self.created_at = time.time()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    @property
    def is_running(self) -> bool:
        return self.container is not None

    def start(self):
        """Creates the container and waits for the daemon to accept connections."""
        if self.container is not None:
            return

        import docker.errors

        self.port = find_free_port()
        host_workspace = self._resolve_host_workspace()

        run_kwargs: dict = {
            "image": self.IMAGE_NAME,
            "command": "sleep infinity",
            "ports": {f"{DAEMON_PORT}/tcp": (_bind_host(), self.port)},
            "volumes": {host_workspace: {"bind": "/workspace", "mode": "rw"}},
            "working_dir": "/workspace",
            "detach": True,
            "labels": {"wizard_managed": "true", "wizard_session": self.session_id},
            "network_disabled": settings.SANDBOX_NETWORK_DISABLED,
            # Containment: generated code must not be able to starve the host or
            # gain privileges beyond what it starts with.
            "mem_limit": settings.SANDBOX_MEM_LIMIT,
            "pids_limit": settings.SANDBOX_PIDS_LIMIT,
            "security_opt": ["no-new-privileges:true"],
            "cap_drop": ["ALL"],
        }
        if settings.SANDBOX_CPU_QUOTA > 0:
            run_kwargs["cpu_quota"] = settings.SANDBOX_CPU_QUOTA
            run_kwargs["cpu_period"] = 100_000
        if settings.SANDBOX_DOCKER_RUNTIME:
            run_kwargs["runtime"] = settings.SANDBOX_DOCKER_RUNTIME

        try:
            self.container = self.client.containers.run(**run_kwargs)
        except docker.errors.ImageNotFound:
            self._build_image()
            self.container = self.client.containers.run(**run_kwargs)

        script = DAEMON_SCRIPT % {
            "port": DAEMON_PORT,
            "pid_file": PID_FILE,
            "allow_pip": "True" if settings.SANDBOX_ALLOW_RUNTIME_PIP else "False",
        }
        self._put_file(DAEMON_PATH, script)
        self.container.exec_run(f"python {DAEMON_PATH}", detach=True)

        if not self._wait_ready():
            logger.warning("Sandbox daemon did not become ready", session=self.session_id)

        logger.info("Sandbox session started", session=self.session_id, port=self.port)

    def _build_image(self):
        docker_context = Path(__file__).resolve().parents[3] / "docker"
        logger.info("Building sandbox image", image=self.IMAGE_NAME, context=str(docker_context))
        self.client.images.build(path=str(docker_context), tag=self.IMAGE_NAME, rm=True)

    def _resolve_host_workspace(self) -> str:
        """Maps the workspace path into a value the Docker daemon can bind-mount.

        When the backend itself runs in a container, the path it sees is not the
        path the daemon sees, so the real host path is read back off our own
        container's mount table.
        """
        if _in_container():
            try:
                own = self.client.containers.get(socket.gethostname())
                for mount in own.attrs.get("Mounts", []):
                    if mount.get("Destination") == "/workspace":
                        source = mount.get("Source")
                        relative = self.workspace_dir.relative_to(settings.WORKSPACE_DIR)
                        return str(Path(source).joinpath(relative)) if str(relative) != "." else source
            except Exception as exc:
                logger.warning("Could not resolve host workspace path", error=str(exc))
        return str(self.workspace_dir)

    def _wait_ready(self, timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection((_connect_host(), self.port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.2)
        return False

    def _put_file(self, path: str, content: str):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            payload = content.encode("utf-8")
            info = tarfile.TarInfo(name=os.path.basename(path))
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
        stream.seek(0)
        self.container.put_archive(os.path.dirname(path), stream)

    # ------------------------------------------------------------------ #
    def _request(self, payload: dict, on_stdout: Callable[[str], None] | None = None) -> dict:
        """Sends one request and drains the reply, forwarding stdout frames."""
        if self.container is None:
            raise SandboxUnavailableError("Sandbox session is not running.")

        timeout = settings.SANDBOX_EXEC_TIMEOUT
        sock = socket.create_connection((_connect_host(), self.port), timeout=timeout)
        sock.settimeout(timeout)
        try:
            raw = json.dumps(payload).encode("utf-8")
            sock.sendall(struct.pack(">I", len(raw)) + raw)

            stdout_parts: list[str] = []
            while True:
                header = self._recv_exactly(sock, 4)
                if header is None:
                    raise SandboxUnavailableError("Sandbox closed the connection unexpectedly.")
                length = struct.unpack(">I", header)[0]
                body = self._recv_exactly(sock, length)
                if body is None:
                    raise SandboxUnavailableError("Truncated response from sandbox.")

                message = json.loads(body.decode("utf-8"))
                if message.get("status") == "stdout":
                    chunk = message.get("content", "")
                    stdout_parts.append(chunk)
                    if on_stdout and chunk.strip():
                        on_stdout(chunk)
                    continue

                message["stdout"] = "".join(stdout_parts) + (message.get("stdout") or "")
                return message
        finally:
            sock.close()

    @staticmethod
    def _recv_exactly(sock: socket.socket, count: int) -> bytearray | None:
        data = bytearray()
        while len(data) < count:
            packet = sock.recv(count - len(data))
            if not packet:
                return None
            data.extend(packet)
        return data

    # ------------------------------------------------------------------ #
    def run_code(self, code: str, on_stdout: Callable[[str], None] | None = None) -> tuple[str, str | None]:
        """Executes ``code``. Returns ``(output_text, base64_png_or_None)``."""
        with self._lock:
            try:
                response = self._request({"action": "execute", "code": code}, on_stdout)
            except TimeoutError:
                return (
                    f"Error executing code:\nExecution exceeded the {settings.SANDBOX_EXEC_TIMEOUT}s time limit.",
                    None,
                )
            except SandboxUnavailableError as exc:
                return f"Error executing code:\n{exc}", None
            except Exception as exc:
                logger.error("Sandbox communication failed", error=str(exc))
                return f"Error executing code:\nSandbox communication failure: {exc}", None

        status = response.get("status")
        stdout = (response.get("stdout") or "").strip()
        stderr = (response.get("stderr") or "").strip()

        if status == "interrupted":
            return "Execution interrupted by user.", None
        if status == "error":
            detail = stderr or "Unknown execution error."
            return f"Error executing code:\n{detail}", None
        return (stdout or "Executed successfully."), response.get("plot")

    def inspect_variables(self) -> dict:
        try:
            with self._lock:
                response = self._request({"action": "inspect_variables"})
            return response.get("variables", {})
        except Exception as exc:
            logger.error("Variable inspection failed", error=str(exc))
            return {}

    def reload_dataset(self) -> bool:
        """Re-reads the dataset from the mount without recreating the container."""
        try:
            with self._lock:
                self._request({"action": "reload_dataset"})
            return True
        except Exception as exc:
            logger.warning("Dataset reload failed", error=str(exc))
            return False

    def reset_namespace(self) -> bool:
        try:
            with self._lock:
                self._request({"action": "reset"})
            return True
        except Exception as exc:
            logger.warning("Namespace reset failed", error=str(exc))
            return False

    def interrupt(self) -> bool:
        """Signals the daemon process itself.

        The previous implementation targeted PID 1, which is the container's
        ``sleep`` command -- interrupting therefore killed the container instead
        of the running cell. The daemon writes its PID at startup so it can be
        signalled precisely.
        """
        if self.container is None:
            return False
        try:
            result = self.container.exec_run(
                ["sh", "-c", f"kill -INT $(cat {PID_FILE} 2>/dev/null) 2>/dev/null || true"]
            )
            logger.info("Sandbox interrupt signalled", session=self.session_id, exit_code=result.exit_code)
            return True
        except Exception as exc:
            logger.error("Failed to interrupt sandbox", error=str(exc))
            return False

    def stop(self):
        if self.container is None:
            return
        try:
            self.container.remove(force=True)
        except Exception:
            pass
        finally:
            self.container = None
            logger.info("Sandbox session stopped", session=self.session_id)


class SandboxPool:
    """Creates and reaps one :class:`SandboxSession` per user session."""

    def __init__(self):
        self._client = None
        self._client_checked = False
        self._sessions: dict[str, SandboxSession] = {}
        self._lock = threading.Lock()
        atexit.register(self.shutdown)

    # ------------------------------------------------------------------ #
    @property
    def client(self):
        """The Docker client, or None when Docker is unavailable/disabled."""
        if self._client_checked:
            return self._client
        with self._lock:
            if self._client_checked:
                return self._client
            self._client_checked = True
            if not settings.SANDBOX_ENABLED:
                logger.info("Sandbox disabled by configuration")
                self._client = None
                return None
            try:
                import docker

                client = docker.from_env()
                client.ping()
                self._client = client
                logger.info("Docker connection established")
            except Exception as exc:
                logger.warning("Docker unavailable; sandboxed execution disabled", error=str(exc))
                self._client = None
            return self._client

    @property
    def available(self) -> bool:
        return self.client is not None

    def workspace_for(self, session_id: str) -> Path:
        """Per-session workspace directory, created on demand."""
        directory = settings.WORKSPACE_DIR / "sessions" / session_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def get(self, session_id: str, create: bool = True) -> SandboxSession | None:
        session = self._sessions.get(session_id)
        if session is not None or not create:
            return session

        if not self.available:
            return None

        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                return session
            session = SandboxSession(self.client, session_id, self.workspace_for(session_id))
            try:
                session.start()
            except Exception as exc:
                logger.error("Failed to start sandbox session", session=session_id, error=str(exc))
                session.stop()
                return None
            self._sessions[session_id] = session
            return session

    def release(self, session_id: str):
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.stop()

    def prune_orphans(self):
        """Removes containers left behind by a previous process."""
        if not self.available:
            return
        try:
            for container in self.client.containers.list(all=True, filters={"label": "wizard_managed=true"}):
                if container.labels.get("wizard_session") in self._sessions:
                    continue
                try:
                    container.remove(force=True)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Failed to prune orphaned sandboxes", error=str(exc))

    def shutdown(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.stop()

    @property
    def active_count(self) -> int:
        return len(self._sessions)


sandbox_pool = SandboxPool()
