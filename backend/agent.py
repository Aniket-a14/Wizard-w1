import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from langchain_ollama import ChatOllama 
from langchain.agents import initialize_agent, AgentType
from langchain.tools import Tool
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
        # Use greedy decoding and stop at newlines if possible, though pipeline might not support stop_sequence easily
        response = local_generator(prompt, max_new_tokens=50, num_return_sequences=1, pad_token_id=50256)[0]['generated_text']
        
        # Extract code part
        code = response.replace(prompt, "").strip()
        
        # Fix run-on code (e.g. "print(df) print(df)") by taking only the first statement if it looks like multiple
        # This is a heuristic for the weak local model
        if code.count("print(") > 1:
            first_print_index = code.find("print(")
            second_print_index = code.find("print(", first_print_index + 1)
            
            # Only truncate if the second print is a repetition of the first or very similar
            # For now, we'll assume if it's on the same line it's likely a hallucination/repetition
            # But if we want to allow multi-step, we need to be smarter.
            # Let's check if there's a newline. If it's all one line, it's likely bad generation.
            if '\n' not in code:
                 if second_print_index != -1:
                    code = code[:second_print_index].strip()
        
        # Also stop at the first newline if multiple lines are generated AND it's a simple task
        # But for multi-step we might want multiple lines. 
        # However, the local model is usually used for simple tasks.
        # So we'll keep the single-line constraint for local model to be safe.
        code = code.split('\n')[0].strip()
    else:
        print("Using Ollama (DeepSeek)...")
        if llm is None:
            llm = ChatOllama(model=MODEL_NAME)
            
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
                
            if is_natural_language(line):
                continue
                
            if is_code_line(line):
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
    Create and return a LangChain agent that uses deepseek-r1 to:
    - Interpret natural language
    - Generate Python code
    - Execute data analysis tasks
    """
    tools = [
        Tool(
            name="Interpret and Execute Command",
            func=lambda x: interpret_and_execute(x, df),
            description="Executes data analysis tasks on the loaded DataFrame."
        )
    ]
    
    agent = initialize_agent(
        tools,
        llm, 
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        handle_parsing_errors=True
    )
    return agent

# This code creates an agent that uses deepseek-r1 with our curated examples
# to generate and execute Python code for data analysis tasks
# the code is based on the following article: https://medium.com/@josephroque/building-a-data-analysis-agent-with-langchain-and-ollama-2024-11-25-1e1441244e3e