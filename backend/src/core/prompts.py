import pandas as pd
import io
from typing import TYPE_CHECKING, Dict, List, Any, Optional

if TYPE_CHECKING:
    import pandas as pd


def generate_system_context(df: pd.DataFrame, catalog: Optional[Dict[str, Any]] = None) -> str:
    """
    Generates a rich, structured Markdown context description of the dataframe.
    """
    buffer = io.StringIO()
    df.info(buf=buffer)
    info_str = buffer.getvalue()

    # Get a glimpse of the data
    head_str = df.head(3).to_markdown(index=False)

    # Get statistical summary for numeric columns
    description = df.describe().to_markdown()

    # Identify categorical columns and their unique values
    cat_summary_list = []
    for col in df.select_dtypes(include=["object", "category", "string"]).columns:
        unique_vals = df[col].unique()
        if len(unique_vals) < 20:
            val_str = ", ".join([f"`{v}`" for v in unique_vals])
            cat_summary_list.append(f"- **{col}**: {val_str}")
        else:
            val_str = ", ".join([f"`{v}`" for v in unique_vals[:5]])
            cat_summary_list.append(f"- **{col}**: {len(unique_vals)} unique values (e.g., {val_str}...)")
    
    cat_summary = "\n".join(cat_summary_list) if cat_summary_list else "*No categorical columns detected.*"

    # Semantic Insight from Catalog
    semantic_insight_list = []
    if catalog is not None:
        for col, meta in catalog.get("columns", {}).items():
            sem_type = meta.get("semantic_type", "unknown")
            missing = meta.get("quality", {}).get("missing_percentage", 0)
            semantic_insight_list.append(f"- **{col}**: `{sem_type}` ({missing}% missing)")
    
    semantic_insight = "\n".join(semantic_insight_list) if semantic_insight_list else ""

    context = f"""<dataset_context>
<schema>
```text
{info_str}
```
</schema>

<data_glimpse>
{head_str}
</data_glimpse>

<statistical_summary>
{description}
</statistical_summary>

<categorical_insights>
{cat_summary}
</categorical_insights>

<semantic_analysis>
{semantic_insight if semantic_insight else "*No detailed semantic analysis available.*"}
</semantic_analysis>
</dataset_context>"""
    return context


def create_cleaning_prompt(df: pd.DataFrame, catalog: Dict[str, Any]) -> str:
    """
    Creates a prompt asking the agent to CLEAN the dataset based on catalog findings.
    """
    context = generate_system_context(df, catalog)
    
    return f"""<role>
You are an expert Senior Data Engineer. Your task is to rigorously CLEAN the provided dataset according to the highest industry standards.
</role>

{context}

<instructions>
1. Handle missing values (e.g., use `.fillna(df['col'].median())` or `.dropna()`). NEVER replace a column with the entire DataFrame (`df['col'] = df` is FORBIDDEN).
2. Fix data types (e.g., convert strings to dates/numbers if they look like them, using `pd.to_numeric` or `pd.to_datetime`).
3. Sanitize strings (remove whitespaces, handle casing).

Write Python code that modifies the dataframe `df` in-place or reassigns it.
Return ONLY the python code block.
Ensure your code is correct and safe to execute.
</instructions>"""


def create_simple_prompt(instruction: str, columns: List[str]) -> str:
    """
    Creates a simple prompt for local models (legacy/fallback).
    """
    return f"""<role>
You are an expert Python data analysis assistant.
</role>

<dataset_context>
You have a pandas dataframe `df` with the following columns: {columns}
</dataset_context>

<user_request>
{instruction}
</user_request>

<instructions>
1. Write python code to compute the result.
2. Assign the result to variables or print it.
3. If plotting, use `matplotlib.pyplot` as `plt`.
4. Do not overwrite `df`.
5. Return ONLY the python code block.
</instructions>"""


def create_prompt(
    instruction: str, 
    df: pd.DataFrame, 
    plan: Optional[str] = None, 
    previous_error: Optional[str] = None, 
    catalog: Optional[Dict[str, Any]] = None
) -> str:
    """
    Enterprise Prompt for the Worker (Qwen): The Sandboxed Execution Engine.
    """
    context = generate_system_context(df, catalog=catalog)
    
    plan_context = ""
    if plan:
        plan_context = f"\n<approved_plan>\n{plan}\n</approved_plan>\n"

    error_context = ""
    if previous_error:
        error_context = f"\n<previous_error>\n{previous_error}\n</previous_error>\n\n<error_handling_instruction>\nThe previous execution failed. Do NOT apologize. meticulously analyze the Python traceback above line-by-line, identify the exact variable or dataframe syntax causing the crash, and write corrected code that fulfills the original plan.\n</error_handling_instruction>\n"

    return f"""<role>
You are an expert Python Code Generator operating inside a secure, headless Data Science sandbox.
Your sole purpose is to TRANSLATE the `approved_plan` into flawless, executable Python code.
</role>

<environment_constraints>
1. You are running in a non-interactive, headless environment.
2. NEVER use `input()` or request user interaction.
3. The dataset is ALREADY loaded into memory as a pandas DataFrame named `df`. DO NOT reload it from disk.
4. Output must be captured via standard output. If you compute a value, `print()` it.
5. Do NOT print entire dataframes. ALWAYS use `.head()`, `.tail()`, or `.info()` to prevent token overflow.
6. For Visualizations: You may use `matplotlib.pyplot` (as `plt`) or `seaborn` (as `sns`). The host environment will automatically capture the active figure. You do NOT need to save the figure to a file unless explicitly requested. Just create the plot.
</environment_constraints>

{context}
{plan_context}{error_context}
<user_request>
{instruction}
</user_request>

<instructions>
Write the Python code to implement the approved plan.
Follow the environment constraints strictly.
Return ONLY valid Python code inside a ```python ``` block. 
Do not include markdown explanations outside the code block.
</instructions>"""


def create_planning_prompt(instruction: str, df: pd.DataFrame, catalog: Optional[Dict[str, Any]] = None, mode: str = "standard", memory_context: str = "") -> str:
    """
    Enterprise Prompt for the Manager (DeepSeek): The Staff Data Scientist.
    """
    context = generate_system_context(df, catalog=catalog)

    if mode == "fast":
        return f"""<role>
You are a high-speed Data Analysis Planner. Your task is to provide a BRUTALLY CONCISE, step-by-step analysis plan.
Skip deep reasoning. Skip web search. Focus purely on the Python implementation steps.
</role>

{context}

<user_request>
{instruction}
</user_request>

<instructions>
1. Output ONLY a concise, numbered list under the heading "Approved Plan". 
2. Ensure the plan can be executed by a single Python script.
</instructions>"""

    return f"""<role>
You are Wizard w1, the Principal Data Scientist for an elite analytics team.
Your responsibility is to architecture a robust, statistically sound analysis plan based on the user's request.
You do NOT write code. You dictate the strategy for a subordinate coding engine.
</role>

{context}

<analytical_workflow>
When formulating your plan, you MUST adhere to the following workflow:
1. INSPECT: Verify data types, identify missing values, and handle anomalous entries.
2. PREPARE: Outline necessary data cleaning, conversions, or feature engineering.
3. ANALYZE: Specify the statistical test, machine learning model, or aggregation logic to use. Check assumptions (e.g., normality) if applicable.
4. CONCLUDE: Define how the results should be presented (printed summary, specific visualization).
</analytical_workflow>

<tools>
<tool>
<name>Web Search</name>
<description>
If the user's request involves a library, algorithm, or domain concept you are unsure about, you may pause planning and use the Web Search tool.
</description>
<usage>
To use the tool, output EXACTLY this format and nothing else:
SEARCH: "your search query here"
</usage>
</tool>
</tools>

<user_request>
{instruction}
</user_request>

<instructions>
1. Provide your strategic reasoning and step-by-step logic inside a <thought>...</thought> block.
2. If you need to search the web, output the SEARCH string OUTSIDE the thought block.
3. If you have enough information, output a concise, numbered list under the heading "Approved Plan". This plan will be directly fed to a Python Code Generator.
</instructions>"""


def create_replan_prompt(instruction: str, search_results: List[Dict[str, Any]], original_thought: str) -> str:
    """
    Enterprise Prompt for Manager re-planning after a search.
    """
    results_str = ""
    for r in search_results:
        results_str += f"- [{r['title']}]({r['link']}): {r['snippet']}\n"

    return f"""<role>
You are Wizard w1, the Principal Data Scientist. You paused your planning to perform a web search regarding the user's request.
</role>

<user_request>
{instruction}
</user_request>

<previous_reasoning>
{original_thought}
</previous_reasoning>

<web_search_results>
{results_str}
</web_search_results>

<instructions>
1. Synthesize the web search results with your previous reasoning.
2. Output a concise, numbered list under the heading "Approved Plan". This plan will be directly fed to a Python Code Generator.
3. Ensure the plan adheres to the Analytical Workflow (Inspect, Prepare, Analyze, Conclude).
</instructions>"""
