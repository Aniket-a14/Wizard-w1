import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import scipy
import statsmodels.api as sm
import sklearn
import plotly.express as px
import plotly.graph_objects as go
from langchain_community.chat_models import ChatOllama
from langchain.agents import initialize_agent, AgentType
from langchain.tools import Tool
import re
import io
import base64
import ast
import sys
from typing import Tuple, Optional, Any
from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM 

from app.core.config import get_settings
from app.core.exceptions import CodeExecutionError, ModelError
from app.services.prompt_service import prompt_service

settings = get_settings()

class AgentService:
    """
    Service for AI Agent interactions (Senior Data Scientist pattern).
    Handles prompt engineering, code generation, and execution.
    """

    def __init__(self):
        self.llm = None
        self.local_generator = None
        self._initialize_models()
    
    def _initialize_models(self):
        """Initialize LLM models based on configuration."""
        if settings.MODEL_TYPE == 'ollama':
            print(f"Initializing Ollama with model: {settings.MODEL_NAME}")
            try:
                self.llm = ChatOllama(model=settings.MODEL_NAME)
            except Exception as e:
                print(f"Failed to initialize Ollama: {e}")
        elif settings.MODEL_TYPE == 'local':
            self._load_local_model()
    
    def _load_local_model(self):
        """Load local HuggingFace model (supports LoRA)."""
        if self.local_generator is None:
            print(f"Loading local model from {settings.MODEL_PATH}...")
            try:
                tokenizer = AutoTokenizer.from_pretrained(settings.MODEL_PATH)
                
                # Check if it's a LoRA adapter
                import os
                if os.path.exists(os.path.join(settings.MODEL_PATH, "adapter_config.json")):
                    from peft import PeftModel
                    # Load base model (assuming base model name is in config or known)
                    # For simplicity, we load the base model defined in settings, then attach adapter
                    base_model = AutoModelForCausalLM.from_pretrained(settings.MODEL_NAME)
                    model = PeftModel.from_pretrained(base_model, settings.MODEL_PATH)
                else:
                    model = AutoModelForCausalLM.from_pretrained(settings.MODEL_PATH)

                self.local_generator = pipeline('text-generation', model=model, tokenizer=tokenizer)
            except Exception as e:
                print(f"Failed to load local model: {e}")

    def is_complex_task(self, instruction: str) -> bool:
        """Determine if a task is complex/multi-step (heuristic)."""
        complexity_keywords = [
            'and', 'then', 'plot', 'chart', 'graph', 'visualize', 'predict',
            'correlation', 'regression', 'clean', 'process', 'train', 'evaluate',
            'model', 'forecast', 'cluster'
        ]
        instruction = instruction.lower()
        if any(keyword in instruction for keyword in complexity_keywords):
            return True
        if len(instruction.split()) > 10:
            return True
        return False

    async def interpret_and_execute(self, instruction: str, df: pd.DataFrame) -> Tuple[str, str, Optional[str]]:
        """
        Main entry point: Interpret instruction -> Generate Code -> Execute.
        Returns: (Result Text, Generated Code, Base64 Image if any)
        """
        code = await self._generate_code(instruction, df)
        return self._process_code(code, df, instruction)

    async def _generate_code(self, instruction: str, df: pd.DataFrame) -> str:
        """Generate Python code using the configured LLM."""
        columns = list(df.columns)
        
        # Decide strategy based on model type and task complexity
        use_local = False
        if settings.MODEL_TYPE == 'local':
            use_local = True
        elif settings.MODEL_TYPE == 'hybrid' and not self.is_complex_task(instruction):
            use_local = True

        try:
            prompt = prompt_service.get_dynamic_prompt(instruction, columns)

            if use_local:
                if self.local_generator is None:
                    self._load_local_model()
                
                # Greedy decoding for simple tasks
                response = self.local_generator(
                    prompt, 
                    max_new_tokens=100, 
                    num_return_sequences=1, 
                    pad_token_id=50256
                )[0]['generated_text']
                code = response.replace(prompt, "").strip().split('\n')[0].strip()
            else:
                if self.llm is None and settings.MODEL_TYPE == 'ollama':
                    self.llm = ChatOllama(model=settings.MODEL_NAME)
                
                response = self.llm.invoke(prompt)
                code = response.content.strip()

            return code
        except Exception as e:
            raise ModelError(str(e))

    def _process_code(self, code: str, df: pd.DataFrame, instruction: str) -> Tuple[str, str, Optional[str]]:
        """Clean and execute the generated code."""
        # 1. Pre-processing / Cleaning
        try:
            # Handle "show full dataset" requests specifically
            if instruction.lower().strip() in ['show full dataset', 'show all data', 'display full dataset', 'show data']:
                return df.to_string(), "df.to_string()", None
            
            # Remove Markdown code blocks if present
            code = re.sub(r'```python|```', '', code).strip()

            # Extract code blocks
            code_lines = []
            for line in code.split('\n'):
                line = line.strip()
                if not line: continue
                # Skip natural language explanations that are not comments
                if self._is_natural_language(line) and not self._is_code_line(line):
                    continue
                code_lines.append(line)
            
            clean_code = '\n'.join(code_lines).strip()
            if not clean_code:
                 return "No valid code generated.", code, None

            # Fix column names case sensitivity
            for col in df.columns:
                if col.lower() in clean_code.lower():
                    # Simple replace might be dangerous if col name is common word, but works for now
                    # A better way would be using regex with boundaries
                    pass 
            
            clean_code = re.sub(r'[''—]', "'", clean_code)

            return self._execute_code(clean_code, df)

        except Exception as e:
            return f"Error processing code: {str(e)}", code, None

    def _execute_code(self, code: str, df: pd.DataFrame) -> Tuple[str, str, Optional[str]]:
        """
        Execute python code in a controlled environment.
        WARNING: Uses exec(), potentially unsafe.
        """
        # Sandwiching exec in detailed logging
        print(f"\n--- Generated Code ---\n{code}\n----------------------")

        exec_globals = {
            "np": np, 
            "pd": pd, 
            "sns": sns, 
            "plt": plt,
            "scipy": scipy,
            "sm": sm,
            "sklearn": sklearn,
            "px": px,
            "go": go,
            "df": df,
            # Restrict builtins
            "__builtins__": {
                k: __builtins__[k] for k in __builtins__ 
                if k not in ['eval', 'open'] 
            }
        }
        
        try:
            # Setup plotting
            plt.clf() # Clear previous plots
            
            # Set pandas display options
            pd.set_option('display.max_rows', None)
            pd.set_option('display.max_columns', None)

            # Strategy: If plot code detected, execute and capture image
            if any(x in code for x in ['plt.', 'sns.', 'plot(', 'fig.show']):
                # Capture Plotly separately if needed, but for now assuming static image export or matplotlib fallback
                # For Plotly in backend, we might need to return JSON or HTML. 
                # For simplicity in this iteration, we focus on Matplotlib/Seaborn capture.
                # If code uses fig.show(), we might need to mock it or instruct agent to use matplotlib.
                
                # Intercept fig.show() for plotly
                if 'fig.show()' in code:
                    # POC: Just executing it might open a window on server, which is bad. 
                    # We should probably encourage static plots for now or return the fig object.
                    pass

                exec(code, exec_globals)
                
                # Check if a figure exists
                if plt.get_fignums():
                    buf = io.BytesIO()
                    plt.savefig(buf, format='png')
                    buf.seek(0)
                    image_base64 = base64.b64encode(buf.read()).decode('utf-8')
                    plt.close()
                    return "Plot generated successfully.", code, image_base64
            
            # Strategy: If simple print/expression, eval or capture stdout
            if code.strip().startswith('print') and '\n' not in code.strip():
                print_content = code.strip()[6:-1]
                if print_content == 'df':
                     return df.to_string(), code, None
                result = eval(print_content, exec_globals)
                return str(result), code, None
            
            # Strategy: Multiline code -> Capture stdout
            buffer = io.StringIO()
            original_stdout = sys.stdout
            sys.stdout = buffer
            
            try:
                # We try to auto-print expressions like a notebook
                tree = ast.parse(code)
                new_body = []
                for node in tree.body:
                    if isinstance(node, ast.Expr):
                        print_node = ast.Expr(
                            value=ast.Call(
                                func=ast.Name(id='print', ctx=ast.Load()),
                                args=[node.value],
                                keywords=[]
                            )
                        )
                        ast.copy_location(print_node, node)
                        new_body.append(print_node)
                    else:
                        new_body.append(node)
                tree.body = new_body
                code_to_run = compile(tree, filename="<string>", mode="exec")
                exec(code_to_run, exec_globals)
            except Exception:
                # Fallback to normal exec if AST transformation fails
                exec(code, exec_globals)
                
            output = buffer.getvalue()
            sys.stdout = original_stdout
            
            if not output:
                # If no output captured, maybe it was an assignment. Return success message.
                return "Code executed successfully (no output).", code, None
            return output, code, None

        except Exception as e:
            if 'plt.' in code: plt.close()
            raise CodeExecutionError(str(e))

    def _is_code_line(self, line: str) -> bool:
        # Reusing regex patterns from original agent.py
        patterns = [
            r'df\.[a-zA-Z_]+\(.*\)', r'plt\.[a-zA-Z_]+\(.*\)', r'sns\.[a-zA-Z_]+\(.*\)',
            r'np\.[a-zA-Z_]+\(.*\)', r'pd\.[a-zA-Z_]+\(.*\)', r'\[.*\]', r'=(?!=)', r'\(.*\)'
        ]
        return any(re.search(p, line) for p in patterns)

    def _is_natural_language(self, line: str) -> bool:
        patterns = [
            r'^[A-Z][^()]*\.$', r'^[A-Z].*\.$', r'^[A-Z].*:$', r'^\d+\..*',
            r'^[-*]\s.*', r'\b(I|we|let|think|need)\b', r'^#.*'
        ]
        return any(re.search(p, line, re.IGNORECASE) for p in patterns)

agent_service = AgentService()
