import docker
import os
import io
import tarfile
import time
import atexit
from typing import Tuple, Optional
from src.config import settings
from src.utils.logging import logger, trace_agent

class SandboxManager:
    """
    Manages Docker containers for secure code execution.
    Optimized with a 'Warmer' container pool to eliminate startup latency.
    Implemented as a Singleton to prevent resource exhaustion.
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
            self._warm_pool = []
            
            # Adaptive Pool Size based on profile
            self.pool_size = 1 if settings.SYSTEM_PROFILE == "laptop" else 3 if settings.SYSTEM_PROFILE == "server" else 5
            self.mem_limit = "512m" if settings.SYSTEM_PROFILE == "laptop" else "2g"
            self.cpu_limit = 500000000 if settings.SYSTEM_PROFILE == "laptop" else 1000000000 # 0.5 vs 1.0 CPU
            
            self._prune_orphans()
            self._initialize_pool()
            
            # Register cleanup on exit
            atexit.register(self.cleanup_pool)
            self._initialized = True
        except Exception as e:
            logger.error("Failed to connect to Docker daemon", error=str(e))
            self.client = None

    def _prune_orphans(self):
        """Removes any stale containers from previous crashed runs."""
        if not self.client: return
        try:
            orphans = self.client.containers.list(all=True, filters={"label": "wizard_managed=true"})
            if orphans:
                logger.info(f"Pruning {len(orphans)} orphan sandbox containers...")
                for container in orphans:
                    try:
                        container.remove(force=True)
                    except:
                        pass
        except Exception as e:
            logger.warning("Failed to prune orphans", error=str(e))

    def _initialize_pool(self):
        """Pre-starts containers to have them ready."""
        if not self.client:
            return
        logger.info(f"Initializing Sandbox Pool ({settings.SYSTEM_PROFILE} profile)...")
        for _ in range(self.pool_size):
            container = self._create_container()
            if container:
                self._warm_pool.append(container)

    def _create_container(self):
        """Creates a fresh container with profile-aware limits."""
        try:
            container = self.client.containers.run(
                self.IMAGE_NAME,
                command="tail -f /dev/null", 
                mem_limit=self.mem_limit,
                nano_cpus=self.cpu_limit,
                network_disabled=True,
                detach=True,
                labels={"wizard_managed": "true"}
            )
            return container
        except Exception as e:
            logger.error("Failed to create sandbox container", error=str(e))
            return None

    def _get_container(self):
        """Gets a warm container from the pool or creates a new one."""
        if self._warm_pool:
            return self._warm_pool.pop(0)
        return self._create_container()

    def run_code(self, code: str, df_bytes: bytes, timeout: int = 30) -> Tuple[str, Optional[str]]:
        """
        Executes code using a warm container from the pool.
        """
        if not self.client:
            return "Error: Docker not available for sandboxing.", None

        container = self._get_container()
        if not container:
            return "Error: Failed to acquire sandbox container.", None

        try:
            # Prepare execution script
            executor_script = f"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import io
import base64
import sys

# Load Data
df = pd.read_csv(io.BytesIO({df_bytes!r}))

# Execute User Code
try:
{self._indent_code(code)}
    
    # Check for plots
    if plt.get_fignums():
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)
        print("---PLOT_START---")
        print(base64.b64encode(buf.read()).decode('utf-8'))
        print("---PLOT_END---")
except Exception as e:
    print(f"Error executing code: {{e}}", file=sys.stderr)
"""
            # 1. Inject script
            self._put_file(container, "/tmp/executor.py", executor_script)

            # 2. Execute
            exec_res = container.exec_run("python /tmp/executor.py", demux=True)
            
            stdout = exec_res.output[0].decode("utf-8") if exec_res.output[0] else ""
            stderr = exec_res.output[1].decode("utf-8") if exec_res.output[1] else ""
            
            if stderr:
                return f"Error: {stderr}", None

            # Extract plot
            image_base64 = None
            if "---PLOT_START---" in stdout:
                parts = stdout.split("---PLOT_START---")
                main_logs = parts[0]
                plot_part = parts[1].split("---PLOT_END---")
                image_base64 = plot_part[0].strip()
                stdout = main_logs + (plot_part[1] if len(plot_part) > 1 else "")

            return stdout.strip(), image_base64

        except Exception as e:
            logger.error("Sandbox execution failed", error=str(e))
            return f"Sandbox error: {str(e)}", None
        finally:
            # Recycling: Instead of removing, we restart it or just replace it
            # For robustness, we'll replace it to ensure a clean state
            try:
                container.remove(force=True)
            except Exception:
                pass
            # Refill pool
            new_container = self._create_container()
            if new_container:
                self._warm_pool.append(new_container)

    def cleanup_pool(self):
        """Kills all containers in the warm pool on system shutdown."""
        if not self._warm_pool: return
        logger.info(f"Shutting down Sandbox Pool ({len(self._warm_pool)} containers)...")
        while self._warm_pool:
            container = self._warm_pool.pop()
            try:
                container.remove(force=True)
            except:
                pass

    def _indent_code(self, code: str) -> str:
        return "\n".join(["    " + line for line in code.split("\n")])

    def _put_file(self, container, path: str, content: str):
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            content_bytes = content.encode('utf-8')
            info = tarfile.TarInfo(name=os.path.basename(path))
            info.size = len(content_bytes)
            tar.addfile(info, io.BytesIO(content_bytes))
        
        tar_stream.seek(0)
        container.put_archive(os.path.dirname(path), tar_stream)
