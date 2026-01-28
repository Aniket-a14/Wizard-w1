from typing import List

def create_simple_prompt(instruction: str, columns: List[str]) -> str:
    """
    Creates a simple prompt for local models.
    """
    return f"""
You are a Python data analysis assistant.
You have a pandas dataframe 'df' with the following columns: {columns}

Task: {instruction}

Write python code to compute the result. 
Assign the result to variables or print it.
If plotting, use matplotlib.pyplot as plt.
Do not overwrite 'df'.

Code:
"""

def create_prompt(instruction: str, columns: List[str]) -> str:
    """
    Creates a more detailed prompt for stronger models (Ollama/DeepSeek).
    """
    return f"""
You are an expert Data Scientist and Python Programmer.
Your task is to write Python code to analyze a dataset based on the user's instruction.

Dataset Context:
- The data is loaded in a pandas DataFrame named 'df'.
- Columns available: {columns}

Instruction: {instruction}

Guidelines:
1. Use pandas, numpy, matplotlib, seaborn as needed.
2. If the user asks for a plot, assume 'plt.show()' might not work and just creating the figure is enough (or verify standard output).
3. If the user asks for a value, print it.
4. Handle edge cases (missing values) if obvious.
5. Return ONLY the python code block, or the code itself.

Response:
"""
