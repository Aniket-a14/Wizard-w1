from functools import lru_cache
from .basic_operations import BASIC_EXAMPLES
from .statistical_operations import STATISTICAL_EXAMPLES
from .pandas_operations import PANDAS_EXAMPLES
from .numpy_operations import NUMPY_EXAMPLES
from .matplotlib_operations import MATPLOTLIB_EXAMPLES
from .seaborn_operations import SEABORN_EXAMPLES
from .seaborn_operations import SEABORN_EXAMPLES
from .advanced_analytics import ADVANCED_EXAMPLES
from .multi_step_operations import MULTI_STEP_EXAMPLES

@lru_cache(maxsize=None)
def get_examples():
    """Get all examples including learned ones (cached)"""
    return (BASIC_EXAMPLES + STATISTICAL_EXAMPLES + PANDAS_EXAMPLES + 
            NUMPY_EXAMPLES + MATPLOTLIB_EXAMPLES + SEABORN_EXAMPLES + 
            ADVANCED_EXAMPLES + MULTI_STEP_EXAMPLES)

def create_prompt(instruction: str, columns: list) -> str:
    """Creates a prompt combining examples and current instruction"""
    from . import get_feedback_examples
    
    examples = get_examples()
    successful_examples = get_feedback_examples()
    all_examples = examples + successful_examples
    
    prompt = f"""You are a Python data analysis assistant. IMPORTANT RULES:
1. The DataFrame is already loaded as 'df' - DO NOT load it again
2. The DataFrame has these columns: {', '.join(columns)}
3. Return ONLY the exact code needed - no explanations or comments
4. DO NOT include import statements - required libraries are already imported
5. Follow the examples below EXACTLY - they show the correct way to handle each task type
"""

    prompt += f"""
Here are some example tasks and their code:

# Basic Operations
{format_examples(examples)}  # Include ALL examples, not just first 5

# Statistical Operations
{format_examples([ex for ex in examples if any(op in ex['task'].lower() for op in 
    ['mean', 'sum', 'count', 'average', 'std', 'var', 'median', 'min', 'max'])])}

# Pandas Operations
{format_examples([ex for ex in examples if any(op in ex['task'].lower() for op in 
    ['filter', 'sort', 'group', 'merge', 'join', 'select'])])}

# Visualization
{format_examples([ex for ex in examples if any(op in ex['task'].lower() for op in 
    ['plot', 'chart', 'graph', 'visualize', 'histogram', 'scatter'])])}

# Advanced Analytics
{format_examples([ex for ex in examples if any(op in ex['task'].lower() for op in 
    ['correlation', 'regression', 'predict', 'analyze'])])}

# Multi-Step Operations
{format_examples(MULTI_STEP_EXAMPLES)}

# Learned from Experience
{format_examples(successful_examples)}

Now generate ONLY the code for this task: {instruction}
"""
    return prompt

def format_examples(examples):
    return '\n'.join(f"Task: {ex['task']}\nCode: {ex['code']}\n" for ex in examples)

def create_simple_prompt(instruction: str, columns: list) -> str:
    """Creates a simple prompt for smaller models"""
    return f"Instruction: {instruction}\nCode:" 


#this code is for the prompt to be used in the agent
#it is a function that formats the examples into a string
