from typing import List
import pandas as pd
import io


def generate_system_context(df: pd.DataFrame, catalog: dict = None) -> str:
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

    # Semantic Insight from Catalog
    semantic_insight = ""
    if catalog:
        semantic_insight = "\nSemantic Column Analysis:\n"
        for col, meta in catalog.get("columns", {}).items():
            sem_type = meta.get("semantic_type", "unknown")
            missing = meta.get("quality", {}).get("missing_percentage", 0)
            semantic_insight += f"- {col}: {sem_type} ({missing}% missing)\n"

    context = f"""
Dataset Overview:
{info_str}

First 3 rows:
{head_str}

Statistical Summary (Numeric):
{description}

Categorical Columns:
{cat_summary}
{semantic_insight}
"""
    return context


def create_cleaning_prompt(df: pd.DataFrame, catalog: dict) -> str:
    """
    Creates a prompt asking the agent to CLEAN the dataset based on catalog findings.
    """
    context = generate_system_context(df, catalog)
    
    return f"""
You are a Senior Data Engineer. Your task is to CLEAN the following dataset.

{context}

Issues to fix:
1. Handle missing values (impute with median/mean or drop if appropriate).
2. Fix data types (e.g., convert strings to dates/numbers if they look like them).
3. Sanitize strings (remove whitespaces, handle casing).

Write Python code that modifies the dataframe 'df' in-place or reassigns it.
Return ONLY the python code block.

Response:
"""


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


def create_prompt(instruction: str, df: pd.DataFrame, previous_error: str = None, catalog: dict = None) -> str:
    """
    Creates a dynamic, rich prompt for the fine-tuned/agent model.
    """
    context = generate_system_context(df, catalog=catalog)
    
    error_context = ""
    if previous_error:
        error_context = f"\nPREVIOUS EXECUTION ERROR:\n{previous_error}\n\nPlease analyze the error above and provide a corrected version of the code.\n"

    return f"""
You are an expert Data Scientist and Python Programmer.
Your task is to write Python code to analyze a dataset based on the user's instruction.

{context}
{error_context}
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


def create_planning_prompt(instruction: str, df: pd.DataFrame, catalog: dict = None, memory_context: str = "") -> str:
    """
    Creates a prompt for the planning phase (Reasoning).
    """
    context = generate_system_context(df, catalog=catalog)

    return f"""
You are a Senior Data Scientist.
Your goal is to PLAN an analysis based on the user's request.

{context}

{memory_context}

Instruction: {instruction}

Guidelines:
1. Provide your reasoning in a <thought> block (e.g., <thought>Analysis of variables X and Y is needed because...</thought>).
2. After the thought block, provide a concise numbered list for the "Approved Plan".
3. Think about statistical assumptions (normality, missing values).

Plan:
"""
