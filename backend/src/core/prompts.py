from typing import List
import pandas as pd
import io


def generate_system_context(df: pd.DataFrame) -> str:
    """
    Generates a rich context description of the dataframe.
    """
    buffer = io.StringIO()
    df.info(buf=buffer)
    info_str = buffer.getvalue()

    # Get a glimpse of the data
    head_str = df.head(3).to_markdown(index=False)

    # Get statistical summary for numeric columns
    description = df.describe().to_markdown()

    # Identify categorical columns and their unique values (limit to avoid token overflow)
    cat_summary = ""
    for col in df.select_dtypes(include=["object", "category", "string"]).columns:
        unique_vals = df[col].unique()
        if len(unique_vals) < 20:  # Only show for low cardinality
            cat_summary += f"- {col}: {list(unique_vals)}\n"
        else:
            cat_summary += f"- {col}: {len(unique_vals)} unique values (e.g., {list(unique_vals[:5])}...)\n"

    context = f"""
Dataset Overview:
{info_str}

First 3 rows:
{head_str}

Statistical Summary (Numeric):
{description}

Categorical Columns:
{cat_summary}
"""
    return context


def create_simple_prompt(instruction: str, columns: List[str]) -> str:
    """
    Creates a simple prompt for local models (legacy/fallback).
    """
    return f"""
You are a Python data analysis assistant.
You have a pandas dataframe 'df' with the following columns: {columns}

Instruction: {instruction}

Write python code to compute the result. 
Assign the result to variables or print it.
If plotting, use matplotlib.pyplot as plt.
Do not overwrite 'df'.

Code:
"""


def create_prompt(instruction: str, df: pd.DataFrame) -> str:
    """
    Creates a dynamic, rich prompt for the fine-tuned/agent model.
    """
    context = generate_system_context(df)

    return f"""
You are an expert Data Scientist and Python Programmer.
Your task is to write Python code to analyze a dataset based on the user's instruction.

{context}

Instruction: {instruction}

Guidelines:
1. Use pandas, numpy, matplotlib, seaborn as needed.
2. If the user asks for a plot, assume 'plt.show()' might not work and just creating the figure is enough (or verify standard output).
3. If the user asks for a value, print it so it can be captured.
4. Handle edge cases (missing values) if obvious.
5. Return ONLY the python code block, or the code itself.
6. The dataframe is named 'df'.

Response:
"""


def create_planning_prompt(instruction: str, df: pd.DataFrame) -> str:
    """
    Creates a prompt for the planning phase (Reasoning).
    """
    context = generate_system_context(df)

    return f"""
You are a Senior Data Scientist.
Your goal is to PLAN an analysis based on the user's request.
Do NOT write code yet. Just describe the steps you would take.

{context}

Instruction: {instruction}

Guidelines:
1. Think about statistical assumptions (normality, missing values).
2. Propose specific steps (e.g., "1. Check for missing values in column X. 2. Impute if necessary. 3. Calculate correlation.").
3. Be concise.

Plan:
"""
