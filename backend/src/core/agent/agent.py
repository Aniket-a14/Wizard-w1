import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from langchain_ollama import ChatOllama
import re
import io
import base64
import ast
import traceback
import builtins
import sys
from typing import Optional, Tuple

from ...config import settings
from ...utils.logging import logger
from ..prompts import create_prompt
from ..tools.stats import StatisticalToolkit
from ..tools.sandbox import SandboxManager


class DataAnalysisAgent:
    def __init__(self):
        self.llm = None
        self.worker_llm = None
        self.sandbox = SandboxManager()
        self.search_tool = None

    def _get_llm(self):
        """Get or initialize the Manager LLM (Planning & Critique)."""
        if self.llm is None:
            try:
                logger.info("Initializing Manager (ChatOllama)", 
                            model=settings.MODEL_NAME, 
                            temp=settings.TEMPERATURE)
                self.llm = ChatOllama(
                    model=settings.MODEL_NAME, 
                    base_url=settings.OLLAMA_BASE_URL,
                    temperature=settings.TEMPERATURE,
                    num_predict=settings.MAX_TOKENS,
                    num_ctx=settings.LLM_NUM_CTX,
                    num_thread=settings.LLM_NUM_THREAD,
                    repeat_penalty=1.1
                )
            except Exception as e:
                logger.warning("Failed to initialize Manager", error=str(e))
        return self.llm

    def _get_worker_llm(self):
        """Get or initialize the Worker LLM (Coding)."""
        if self.worker_llm is None:
            try:
                logger.info("Initializing Worker (ChatOllama)", 
                            model=settings.WORKER_MODEL_NAME,
                            temp=settings.TEMPERATURE)
                self.worker_llm = ChatOllama(
                    model=settings.WORKER_MODEL_NAME, 
                    base_url=settings.OLLAMA_BASE_URL,
                    temperature=settings.TEMPERATURE,
                    num_predict=settings.MAX_TOKENS,
                    num_ctx=settings.LLM_NUM_CTX,
                    num_thread=settings.LLM_NUM_THREAD
                )
            except Exception as e:
                logger.warning("Failed to initialize Worker", error=str(e))
        return self.worker_llm

    def run(self, instruction: str, df: pd.DataFrame, previous_error: Optional[str] = None, catalog: Optional[dict] = None, plan: Optional[str] = None, mode: str = "standard") -> Tuple[str, str, Optional[str]]:
        """
        Refactored main entry point: Plan (DeepSeek) -> Execute (Qwen) -> Critique (DeepSeek).
        """
        log = logger.bind(instruction=instruction, df_shape=df.shape)
        log.info("Agent starting execution loop", mode=mode)

        # 1. PLANNING PHASE (Manager Brain - DeepSeek)
        # Skip internal planning if a plan is provided or in fast mode
        if not plan and mode != "fast":
            from ..prompts import create_planning_prompt, create_replan_prompt
            from ..tools.search import WebSearchTool
            
            if self.search_tool is None:
                self.search_tool = WebSearchTool()
            
            planning_prompt = create_planning_prompt(instruction, df, catalog=catalog, mode=mode)
            
            llm = self._get_llm()
            plan_text = ""
            if llm:
                try:
                    log.info("Manager (DeepSeek) is planning...")
                    plan_response = llm.invoke(planning_prompt).content
                    
                    # Check for SEARCH request
                    if "SEARCH:" in plan_response:
                        search_match = re.search(r'SEARCH:\s*"(.*?)"', plan_response)
                        if search_match:
                            query = search_match.group(1)
                            log.info("Manager requested search", query=query)
                            results = self.search_tool.search(query)
                            
                            # Re-plan with results
                            thought = re.search(r"<thought>(.*?)</thought>", plan_response, re.DOTALL)
                            thought_content = thought.group(1) if thought else "Initial thought"
                            
                            replan_prompt = create_replan_prompt(instruction, results, thought_content)
                            log.info("Manager is re-planning with search results...")
                            plan_text = llm.invoke(replan_prompt).content
                        else:
                            plan_text = plan_response
                    else:
                        plan_text = plan_response
                        
                    log.info("Final Plan obtained", plan_snippet=plan_text[:100])
                except Exception as e:
                    log.error("Manager planning/search failed", error=str(e))
                    plan_text = f"1. Analyze instruction: {instruction}\n2. Generate code using local worker."
        else:
            # Use provided plan or a dummy plan for fast mode if instruction is the direct task
            plan_text = plan if plan else instruction
            log.info("Bypassing internal planning", source="provided" if plan else "fast_mode")

        # 2. EXECUTION PHASE (Worker Brain - Qwen)
        # Qwen is the coding specialist.
        worker_llm = self._get_worker_llm()
        
        max_retries = 2
        previous_error = None
        
        for attempt in range(max_retries + 1):
            # Inject plan into the worker's prompt
            worker_prompt = create_prompt(instruction, df, plan=plan_text, previous_error=previous_error, catalog=catalog)
            
            code = ""
            if worker_llm:
                try:
                    log.info(f"Worker (Qwen) is coding (Attempt {attempt+1})...")
                    response = worker_llm.invoke(worker_prompt).content
                    code = self._extract_code_block(response)
                except Exception as e:
                    log.error("Worker code generation failed", error=str(e))
                    return f"Worker error: {e}", "", None
            
            if not code:
                return "Failed to generate code.", "", None

            # 3. EXECUTION & FEEDBACK LOOP
            result, executed_code, image_base64 = self._process_code(code, df)
            
            # Check for errors in the result
            if "Error executing code" in result or "Traceback" in result:
                log.warning(f"Execution failed on attempt {attempt+1}", error=result)
                previous_error = result
                # On next loop, we retry with the error context
                continue
            else:
                # Success!
                return result, executed_code, image_base64

        return f"Failed after {max_retries} retries. Final error: {previous_error}", code, None

    def _extract_code_block(self, response_text: str) -> str:
        """Robustly extracts code from LLM response."""
        python_block = re.search(r"```python\s*(.*?)```", response_text, re.DOTALL)
        if python_block:
            return python_block.group(1).strip()

        code_block = re.search(r"```\s*(.*?)```", response_text, re.DOTALL)
        if code_block:
            return code_block.group(1).strip()

        return response_text.strip()

    def _process_code(
        self, code: str, df: pd.DataFrame
    ) -> Tuple[str, str, Optional[str]]:
        """Sanitizes and executes code."""
        # Cleanups
        if code.startswith("python"):
            code = code[6:].strip()

        # Execute via Sandbox with Local Fallback
        if self.sandbox.client:
            return self._execute_sandboxed(code, df)
        else:
            logger.warning("Docker unavailable, falling back to local execution.")
            return self._execute_safe(code, df)

    def _execute_sandboxed(
        self, code: str, df: pd.DataFrame
    ) -> Tuple[str, str, Optional[str]]:
        """Executes code in a Docker sandbox."""
        logger.info("Executing code in sandbox", code_snippet=code[:50])
        
        # Serialize DF to pass to sandbox using fastest IPC (Feather)
        buf = io.BytesIO()
        df.to_feather(buf)
        df_bytes = buf.getvalue()

        result, image_base64 = self.sandbox.run_code(code, df_bytes)
        
        return result, code, image_base64

    def _execute_safe(
        self, code: str, df: pd.DataFrame
    ) -> Tuple[str, str, Optional[str]]:
        """Executes code in a sandbox."""
        logger.info("Executing code", code_snippet=code[:50])

        # Capture buffers
        output_buffer = io.StringIO()
        sys_stdout_backup = sys.stdout

        # Globals
        exec_globals = {
            "np": np,
            "pd": pd,
            "sns": sns,
            "plt": plt,
            "df": df,
            "stats": StatisticalToolkit,
            "__builtins__": {
                k: v
                for k, v in builtins.__dict__.items()
                if k not in ["eval", "exec", "open", "exit", "quit"]
            },
        }

        try:
            pd.set_option("display.max_rows", None)

            is_plotting = "plt." in code or "sns." in code or ".plot(" in code

            if is_plotting:
                plt.clf()
                exec(code, exec_globals)
                buf = io.BytesIO()
                plt.savefig(buf, format="png", bbox_inches="tight")
                buf.seek(0)
                image_base64 = base64.b64encode(buf.read()).decode("utf-8")
                plt.close()
                return "Plot generated successfully.", code, image_base64
            else:
                sys.stdout = output_buffer
                # Try eval for single expression
                try:
                    tree = ast.parse(code)
                    if len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
                        result = eval(
                            compile(tree, filename="<string>", mode="eval"),
                            exec_globals,
                        )
                        if result is not None:
                            print(result)
                    else:
                        exec(code, exec_globals)
                except Exception:
                    exec(code, exec_globals)

                output = output_buffer.getvalue()
                return (
                    output.strip() if output else "Executed successfully.",
                    code,
                    None,
                )

        except Exception as e:
            logger.error(
                "Execution error", error=str(e), traceback=traceback.format_exc()
            )
            return f"Error executing code: {e}", code, None
        finally:
            if sys.stdout != sys_stdout_backup:
                sys.stdout = sys_stdout_backup
            if "plt" in locals():
                plt.close()


# Singleton instance
agent = DataAnalysisAgent()
