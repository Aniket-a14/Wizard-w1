import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from langchain_ollama import ChatOllama 
from langchain.agents import create_agent 
from langchain.tools import BaseTool, tool
import re
from typing import List

from config import MODEL_NAME, MODEL_TYPE, MODEL_PATH
from prompts import create_prompt, create_simple_prompt
from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM 
import ast 
import io
import base64

if MODEL_TYPE == 'ollama':
    llm = ChatOllama(model=MODEL_NAME)
else:
    llm = None

local_generator = None

# Define regex patterns for code and natural language
CODE_PATTERNS = [
    r'df\.[a-zA-Z_]+\(.*\)',  # DataFrame methods
    r'plt\.[a-zA-Z_]+\(.*\)',  # Matplotlib commands
    r'sns\.[a-zA-Z_]+\(.*\)',  # Seaborn commands
    r'np\.[a-zA-Z_]+\(.*\)',   # NumPy operations
    r'pd\.[a-zA-Z_]+\(.*\)',   # Pandas operations
    r'\[.*\]',                 # List/array operations
    r'=(?!=)',                 # Assignment (but not ==)
    r'\(.*\)',                 # Function calls
]

NATURAL_LANGUAGE_PATTERNS = [
    r'^[A-Z][^()]*\.$',       # Sentences starting with capital letter (strict)
    r'^[A-Z].*\.$',           # Sentences starting with capital letter (general)
    r'^[A-Z].*:$',            # Sentences ending with colon (e.g. "To do this:")
    r'^\d+\..*',              # Numbered lists (e.g. "1. Step one")
    r'^[-*]\s.*',             # Bullet points (e.g. "- Step one")
    r'\b(I|we|let|think|need|want|should|could|would|may|might|can)\b',  # Common words
    r'\b(okay|so|then|now|here|there|just|try|using|remember|recall)\b',
    r'[?!]',                  # Question/exclamation marks
    r'^#.*',                  # Comments
    r'```.*```',              # Code blocks markers
]

def is_code_line(line: str) -> bool:
    """Check if a line looks like code"""
    return any(re.search(pattern, line) for pattern in CODE_PATTERNS)

def is_natural_language(line: str) -> bool:
    """Check if a line looks like natural language"""
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in NATURAL_LANGUAGE_PATTERNS)

def is_complex_task(instruction: str) -> bool:
    """Determine if a task is complex/multi-step"""
    complexity_keywords = [
        'and', 'then', 'plot', 'chart', 'graph', 'visualize', 'predict',
        'correlation', 'regression', 'clean', 'process'
    ]
    
    instruction = instruction.lower()
    
    # Check for keywords
    if any(keyword in instruction for keyword in complexity_keywords):
        return True
        
    # Check length
    if len(instruction.split()) > 10:
        return True
        
    return False

def interpret_and_execute(instruction: str, df: pd.DataFrame) -> tuple[str, str, str | None]:
    """Uses deepseek-r1 or local model to generate code"""
    global local_generator, llm
    
    # Determine which model to use
    use_local = False
    if MODEL_TYPE == 'local':
        use_local = True
    elif MODEL_TYPE == 'hybrid':
        if not is_complex_task(instruction):
            use_local = True
            
    if use_local:
        if local_generator is None:
            print("Loading local model...")
            tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
            model = AutoModelForCausalLM.from_pretrained(MODEL_PATH)
            local_generator = pipeline('text-generation', model=model, tokenizer=tokenizer)
            
        prompt = create_simple_prompt(instruction, list(df.columns))
        # Generate code with constraints appropriate for the small model
        response = local_generator(prompt, max_new_tokens=50, num_return_sequences=1, pad_token_id=50256)[0]['generated_text']
        
        # Extract code part
        code = response.replace(prompt, "").strip()
        
        # Basic cleanup
        if code.count("print(") > 1 and '\n' not in code:
             first_print_index = code.find("print(")
             second_print_index = code.find("print(", first_print_index + 1)
             if second_print_index != -1:
                code = code[:second_print_index].strip()
        
        code = code.split('\n')[0].strip()
    else:
        # Using Ollama / LangGraph Agent
        if llm is None:
            llm = ChatOllama(model=MODEL_NAME)
            
        # For simple tool use simulation, we can just invoke the LLM directly with a prompt
        # But if we want to use the agent tool structure:
        
        # Define the tool
        def execute_analysis(code_snippet: str) -> str:
            """Executes pandas code on the dataframe"""
            # This is a bit recursive/meta, usually the agent decides to use this tool.
            # But here `interpret_and_execute` is called by the API.
            # If we just want the CODE from the LLM, we can ask for code.
            return code_snippet

        # If we use the agent to GET the code:
        prompt = create_prompt(instruction, list(df.columns))
        response = llm.invoke(prompt)
        code = response.content.strip()

    return process_code(code, df, instruction)

def process_code(code: str, df: pd.DataFrame, instruction: str = "") -> tuple[str, str, str | None]:
    """Process and execute the generated code"""
    try:
        if instruction and instruction.lower().strip() in ['show full dataset', 'show all data', 'display full dataset', 'show data']:
            pd.set_option('display.max_rows', None)
            pd.set_option('display.max_columns', None)
            pd.set_option('display.width', None)
            pd.set_option('display.max_colwidth', None)
            return df.to_string(), "df.to_string()", None
        
        code_lines = []
        for line in code.split('\n'):
            line = line.strip()
            
            if not line or re.match(r'^[^a-zA-Z0-9_]+$', line):
                continue
            
            # Remove ```python or ```
            if line.startswith('```'):
                continue

            if is_natural_language(line):
                continue
                
            if is_code_line(line) or True: # Relaxed check, trust the model a bit more or clean better
                 code_lines.append(line)
        
        code = '\n'.join(code_lines).strip()
        
        if not code:
            return "No valid code generated.", "", None
            
        # Fix column names and special characters
        for col in df.columns:
            if col.lower() in code.lower():
                code = code.replace(col.lower(), col)
        
        code = re.sub(r'[''—]', "'", code)  # Replace special quotes and dashes
        
        return process_and_execute(code, df)
        
    except Exception as e:
        return f"Error processing code: {str(e)}", code, None

def process_and_execute(code: str, df: pd.DataFrame) -> tuple[str, str, str | None]:
    """Helper function to execute the processed code"""
    print("\n--- Generated Code ---")
    print(code)
    print("----------------------\n")
    import io
    
    exec_globals = {
        "np": np, 
        "pd": pd, 
        "sns": sns, 
        "plt": plt,
        "df": df,
        "__builtins__": {
            k: __builtins__[k] for k in __builtins__ 
            if k not in ['eval', 'exec', 'open']
        }
    }
    
    try:
        # Set display options
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', None)
        pd.set_option('display.max_colwidth', None)
        
        if 'plt.' in code or 'sns.' in code:
            exec(code, exec_globals)
            # Capture plot
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            image_base64 = base64.b64encode(buf.read()).decode('utf-8')
            plt.close()
            return "Plot generated successfully.", code, image_base64
            
        elif code.strip().startswith('print') and '\n' not in code.strip():
            # Only optimize single-line print statements
            print_content = code.strip()[6:-1]  
            if print_content == 'df':
                return df.to_string(), code, None
            else:
                result = eval(print_content, exec_globals)
                return str(result), code, None
        else:
            # For multi-line code or non-print statements, use exec
            # Capture stdout to return it
            import io
            import sys
            import ast
            
            # Transform code to print expressions (REPL-like behavior)
            try:
                tree = ast.parse(code)
                new_body = []
                for node in tree.body:
                    if isinstance(node, ast.Expr):
                        # Wrap expression in print()
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
            except Exception as e:
                print(f"AST transformation failed: {e}")
                code_to_run = code # Fallback to original code
            
            # Create a buffer to capture stdout
            buffer = io.StringIO()
            original_stdout = sys.stdout
            sys.stdout = buffer
            
            try:
                exec(code_to_run, exec_globals)
                output = buffer.getvalue()
            finally:
                sys.stdout = original_stdout
                
            if not output:
                return "Code executed successfully (no output).", code, None
                
            return output, code, None
    except Exception as e:
        if 'plt.' in code:
            plt.close()
        return f"Error executing code: {str(e)}", code, None

def create_agent(df):
    """
    Create and return a compiled agent graph.
    """
    
    def python_expert(input_text: str):
        # This is a dummy tool for now as the logic is handled in interpret_and_execute
        # But if we were to fully implement the agent:
        return interpret_and_execute(input_text, df)

    tools = [python_expert]
    
    if llm:
         # In the new API, we pass the model and tools
         agent_graph = create_agent(
            model=llm,
            tools=tools,
            system_prompt="You are a data analysis assistant."
         )
         return agent_graph
    return None

# this code creates an agent that uses deepseek-r1 with our curated examples
# to generate and execute Python code for data analysis tasks