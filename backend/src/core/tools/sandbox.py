import docker
import os
import io
import tarfile
import atexit
import socket
import json
import struct
import time
from typing import Tuple, Optional
from src.config import settings
from src.utils.logging import logger

# Daemon script to run inside the container for persistent stateful execution
DAEMON_SCRIPT = """
import socket
import json
import sys
import io
import traceback
import base64
import os
import struct

def recvall(sock, n):
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data

def read_message(sock):
    raw_msglen = recvall(sock, 4)
    if not raw_msglen:
        return None
    msglen = struct.unpack('>I', raw_msglen)[0]
    raw_payload = recvall(sock, msglen)
    if not raw_payload:
        return None
    return json.loads(raw_payload.decode('utf-8'))

def send_message(sock, response_dict):
    msg = json.dumps(response_dict).encode('utf-8')
    msg = struct.pack('>I', len(msg)) + msg
    sock.sendall(msg)

def run_server(port=5005):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', port))
    server.listen(1)
    
    # Initialize persistent state namespace
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    import seaborn as sns
    
    exec_globals = {
        "pd": pd,
        "np": np,
        "plt": plt,
        "sns": sns,
        "__builtins__": __builtins__
    }
    
    # Preload dataset if exists
    if os.path.exists('/workspace/dataset.feather'):
        try:
            exec_globals["df"] = pd.read_feather('/workspace/dataset.feather')
            print("Dataset preloaded successfully in exec_globals.")
        except Exception as e:
            print(f"Error preloading dataset: {e}")

    print(f"Sandbox daemon listening on port {port}...")
    
    while True:
        try:
            conn, addr = server.accept()
            payload = read_message(conn)
            if not payload:
                conn.close()
                continue
                
            code = payload.get("code", "")
            
            # Setup output capture
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            sys.stdout = stdout_buf
            sys.stderr = stderr_buf
            
            plot_data = None
            status = "success"
            
            try:
                # Clear matplotlib plot state
                plt.clf()
                plt.close('all')
                
                # Exec user code in the persistent namespace
                exec(code, exec_globals)
                
                # Check for plots
                if plt.get_fignums():
                    buf = io.BytesIO()
                    plt.savefig(buf, format='png', bbox_inches='tight')
                    buf.seek(0)
                    plot_data = base64.b64encode(buf.read()).decode('utf-8')
                    plt.close('all')
            except KeyboardInterrupt:
                status = "interrupted"
                print("Execution interrupted by user.", file=sys.stderr)
            except Exception as e:
                status = "error"
                print(traceback.format_exc(), file=sys.stderr)
            finally:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
                
            response = {
                "status": status,
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue(),
                "plot": plot_data
            }
            send_message(conn, response)
            conn.close()
        except Exception as e:
            # Prevent server from crashing on connection errors
            try:
                conn.close()
            except:
                pass

if __name__ == '__main__':
    run_server()
"""

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


class SandboxManager:
    """
    Manages a stateful Docker container for persistent code execution.
    Mounts local ./workspace to container /workspace.
    """
    
    _instance = None
    IMAGE_NAME = "wizard-sandbox:latest"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SandboxManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if getattr(self, '_initialized', False):
            return
            
        try:
            self.client = docker.from_env()
            self.container = None
            self.port = None
            
            # Ensure Image Exists
            try:
                self.client.images.get(self.IMAGE_NAME)
            except docker.errors.ImageNotFound:
                logger.info(f"Image {self.IMAGE_NAME} not found. Building...")
                self._build_image()
            
            self._prune_orphans()
            self.start_session()
            
            atexit.register(self.cleanup)
            self._initialized = True
        except Exception as e:
            logger.error("Failed to connect to Docker or initialize session", error=str(e))
            self.client = None

    def _build_image(self):
        """Builds the sandbox image from backend/docker/Dockerfile."""
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            docker_context = os.path.abspath(os.path.join(current_dir, "..", "..", "..", "docker"))
            logger.info(f"Building {self.IMAGE_NAME} from {docker_context}...")
            self.client.images.build(path=docker_context, tag=self.IMAGE_NAME, rm=True)
            logger.info(f"Successfully built {self.IMAGE_NAME}")
        except Exception as e:
            logger.error(f"Failed to build sandbox image: {e}")
            raise

    def _prune_orphans(self):
        """Prunes stale containers."""
        if not self.client:
            return
        try:
            orphans = self.client.containers.list(all=True, filters={"label": "wizard_managed=true"})
            for container in orphans:
                try:
                    container.remove(force=True)
                except:
                    pass
        except Exception as e:
            logger.warning("Failed to prune orphans", error=str(e))

    def start_session(self):
        """Starts a persistent container session with mounted workspace."""
        if not self.client:
            return
        
        try:
            self.port = find_free_port()
            logger.info("Starting stateful container session", port=self.port)
            
            # Start Docker container
            self.container = self.client.containers.run(
                self.IMAGE_NAME,
                command="sleep 365d",
                ports={'5005/tcp': self.port},
                volumes={str(settings.WORKSPACE_DIR): {'bind': '/workspace', 'mode': 'rw'}},
                working_dir="/workspace",
                detach=True,
                labels={"wizard_managed": "true"}
            )
            
            # Inject daemon script
            self._put_file(self.container, "/tmp/sandbox_agent_daemon.py", DAEMON_SCRIPT)
            
            # Run the daemon inside the container in the background
            self.container.exec_run("python /tmp/sandbox_agent_daemon.py", detach=True)
            
            # Wait briefly for daemon port to open
            time.sleep(1.0)
        except Exception as e:
            logger.error("Failed to start container session", error=str(e))
            if self.container:
                try:
                    self.container.remove(force=True)
                except:
                    pass
                self.container = None

    def run_code(self, code: str, df_bytes: Optional[bytes] = None) -> Tuple[str, Optional[str]]:
        """
        Runs code inside the persistent session container.
        df_bytes parameter is kept for backward compatibility but is ignored
        in favor of workspace preloading.
        """
        if not self.client or not self.container:
            return "Error: Sandbox container session is not running.", None

        # Connect to container daemon
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(('127.0.0.1', self.port))
            
            # Send code message
            payload = json.dumps({"code": code}).encode('utf-8')
            msg = struct.pack('>I', len(payload)) + payload
            s.sendall(msg)
            
            # Read header
            raw_msglen = s.recv(4)
            if not raw_msglen:
                return "Error: Connection closed by sandbox daemon.", None
            msglen = struct.unpack('>I', raw_msglen)[0]
            
            # Read payload
            data_bytes = bytearray()
            while len(data_bytes) < msglen:
                packet = s.recv(msglen - len(data_bytes))
                if not packet:
                    break
                data_bytes.extend(packet)
            
            response = json.loads(data_bytes.decode('utf-8'))
            s.close()
            
            status = response.get("status")
            stdout = response.get("stdout", "")
            stderr = response.get("stderr", "")
            plot = response.get("plot")
            
            if status == "interrupted":
                return "Error: Execution interrupted by user.", None
            elif status == "error":
                return f"Error executing code:\n{stderr}", None
            
            output = stdout.strip() if stdout else "Executed successfully."
            return output, plot
        except Exception as e:
            logger.error("Sandbox socket communication failed", error=str(e))
            return f"Sandbox communication error: {e}", None

    def interrupt(self):
        """Sends a SIGINT (signal 2) to the main process inside the container to stop execution."""
        if not self.container:
            return
        try:
            logger.info("Interrupting sandbox execution...")
            # PID 1 is the main daemon execution script in the container
            self.container.exec_run("kill -2 1")
        except Exception as e:
            logger.error("Failed to interrupt execution", error=str(e))

    def cleanup(self):
        """Cleans up container session on application shutdown."""
        if self.container:
            logger.info("Cleaning up sandbox container session")
            try:
                self.container.remove(force=True)
            except:
                pass
            self.container = None

    def _put_file(self, container, path: str, content: str):
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            content_bytes = content.encode('utf-8')
            info = tarfile.TarInfo(name=os.path.basename(path))
            info.size = len(content_bytes)
            tar.addfile(info, io.BytesIO(content_bytes))
        
        tar_stream.seek(0)
        container.put_archive(os.path.dirname(path), tar_stream)
