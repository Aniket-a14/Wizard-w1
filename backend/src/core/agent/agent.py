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
from ..prompts import create_prompt, create_simple_prompt
from ..tools.stats import StatisticalToolkit


class DataAnalysisAgent:
    def __init__(self):
        self.llm = None
        self.local_generator = None
        self._initialize_llm()

    def _initialize_llm(self):
        """Lazy initialization of the LLM connection."""
        if settings.MODEL_TYPE in ["ollama", "hybrid"]:
            # We don't correct eagerly connect here to keep it lazy,
            # but we set up the potential to connect.
            # actually, lazy loading means we do it in run().
            pass

    def _get_llm(self):
        """Get or initialize the LLM client."""
        if self.llm is None and settings.MODEL_TYPE in ["ollama", "hybrid"]:
            try:
                logger.info("Initializing ChatOllama", model=settings.MODEL_NAME)
                self.llm = ChatOllama(model=settings.MODEL_NAME)
            except Exception as e:
                logger.warning("Failed to initialize ChatOllama", error=str(e))
                self.llm = None
        return self.llm

    def _get_local_generator(self):
        """Get or initialize local transformer model."""
        if self.local_generator is None:
            logger.info("Loading local model...", path=settings.MODEL_PATH)
            try:
                from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
                import torch

                # Use float16 for memory efficiency
                dtype = torch.float16 if torch.cuda.is_available() else torch.float32

                quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=dtype,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    llm_int8_enable_fp32_cpu_offload=True
                )

                tokenizer = AutoTokenizer.from_pretrained(settings.MODEL_PATH)
                model = AutoModelForCausalLM.from_pretrained(
                    settings.MODEL_PATH,
                    quantization_config=quant_config,
                    device_map="auto",
                    low_cpu_mem_usage=True,
                    offload_folder="offload"
                )
                self.local_generator = pipeline(
                    "text-generation", model=model, tokenizer=tokenizer
                )
            except Exception as e:
                logger.error("Error loading local model", error=str(e))
                return None
        return self.local_generator

    def run(self, instruction: str, df: pd.DataFrame) -> Tuple[str, str, Optional[str]]:
        """
        Main entry point for agent execution.
        Returns: (Response Text, Code Executed, Base64 Image)
        """
        log = logger.bind(instruction=instruction, df_shape=df.shape)
        log.info("Agent received instruction")

        code = ""
        llm = self._get_llm()

        # Strategy:
        # - Ollama Mode: Use Strong Model for everything.
        # - Hybrid Mode: Strong Model (Plan) -> Local Model (Code).
        # - Local Mode: Local Model (No Plan) -> Local Model (Code).
        
        # Only use strong model for CODE if explicitly in 'ollama' mode.
        # In 'hybrid' mode, flow.py used DeepSeek to create a plan,
        # and now we want the LOCAL model to execute that plan.
        use_strong_model_for_code = settings.MODEL_TYPE == "ollama"

        if use_strong_model_for_code:
            if llm:
                prompt = create_prompt(instruction, df)
                try:
                    log.info("Invoking LLM")
                    response = llm.invoke(prompt)
                    code = self._extract_code_block(response.content)
                except Exception as e:
                    log.error("LLM Invocation failed", error=str(e))
                    return f"Error communicating with AI Agent: {e}", "", None
            else:
                log.warning("Strong model requested but unavailable. Falling back?")
                # Fallback logic could go here

        # Hybrid or Local or Fallback: Use Local Model for Code
        if not code and settings.MODEL_TYPE in ["local", "hybrid"]:
            # Fallback
            local_gen = self._get_local_generator()
            if local_gen:
                # Use simple prompt for the 1.5B model to prevent context overflow,
                # but instruction now contains the "Approved Plan" from flow.py (if hybrid).
                prompt = create_simple_prompt(instruction, list(df.columns))
                try:
                    # Increase token limit slightly for the 'Worker' to write full code
                    response = local_gen(
                        prompt, max_new_tokens=256, pad_token_id=50256
                    )[0]["generated_text"]
                    code = self._extract_code_block(response.replace(prompt, ""))
                except Exception as e:
                    return f"Error with local model: {e}", "", None

        if not code:
            return "Could not generate code.", "", None

        return self._process_code(code, df)

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

        # Execute
        return self._execute_safe(code, df)

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
