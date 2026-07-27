"""Prompt construction.

The previous ``generate_system_context`` unconditionally serialised ``df.info()``,
``df.describe()``, every categorical column's unique values and every registered
workspace schema into every prompt. On a wide frame that alone can overflow the
context window, which is what makes a small local model start inventing column
names. Context is now budgeted: columns are selected by relevance to the actual
question, and per-section output is capped.
"""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Any

import pandas as pd

from src.config import settings
from src.core.rag.retriever import context_retriever


MAX_CATEGORICAL_COLUMNS = 12
MAX_UNIQUE_VALUES_SHOWN = 8
MAX_WARNINGS = 8


def _describe_columns(df: pd.DataFrame, columns: list[str]) -> str:
    """Compact per-column schema table (dtype, null %, sample) for the chosen columns."""
    rows = []
    total = len(df)
    for column in columns:
        series = df[column]
        null_pct = (series.isna().sum() / total * 100) if total else 0.0
        try:
            sample = series.dropna().iloc[0]
            sample_text = str(sample)[:40]
        except (IndexError, KeyError):
            sample_text = ""
        rows.append(f"| {column} | {series.dtype} | {null_pct:.1f}% | {sample_text} |")

    header = "| column | dtype | null % | example |\n| --- | --- | --- | --- |"
    return header + "\n" + "\n".join(rows)


def _categorical_insights(df: pd.DataFrame, columns: list[str]) -> str:
    candidates = [
        c
        for c in columns
        if c in df.columns and (df[c].dtype == object or isinstance(df[c].dtype, pd.CategoricalDtype))
    ]
    if not candidates:
        return "*No categorical columns in scope.*"

    lines = []
    for column in candidates[:MAX_CATEGORICAL_COLUMNS]:
        try:
            uniques = df[column].dropna().unique()
        except (TypeError, ValueError):
            continue
        if len(uniques) <= MAX_UNIQUE_VALUES_SHOWN:
            values = ", ".join(f"`{v}`" for v in uniques)
            lines.append(f"- **{column}**: {values}")
        else:
            preview = ", ".join(f"`{v}`" for v in uniques[:MAX_UNIQUE_VALUES_SHOWN])
            lines.append(f"- **{column}**: {len(uniques)} distinct values (e.g. {preview}, ...)")
    return "\n".join(lines) if lines else "*No categorical columns in scope.*"


def _quality_warnings(df: pd.DataFrame, columns: list[str]) -> str:
    warnings: list[str] = []

    for column in columns:
        if column not in df.columns:
            continue
        series = df[column]
        null_rate = series.isna().mean()
        if null_rate > 0.1:
            warnings.append(f"- `{column}` is {null_rate:.0%} missing. Handle nulls before aggregating or plotting.")
        if len(warnings) >= MAX_WARNINGS:
            break

    if len(warnings) < MAX_WARNINGS:
        for column in columns:
            if column not in df.columns:
                continue
            series = df[column]
            if pd.api.types.is_object_dtype(series):
                try:
                    sample = series.dropna().head(5)
                    if not sample.empty and pd.to_datetime(sample, errors="coerce", format="mixed").notna().all():
                        warnings.append(
                            f"- `{column}` looks like dates stored as text. Convert with `pd.to_datetime()` first."
                        )
                except (ValueError, TypeError):
                    continue
            if len(warnings) >= MAX_WARNINGS:
                break

    if not warnings:
        return ""
    return "\n<data_quality_warnings>\n" + "\n".join(warnings) + "\n</data_quality_warnings>\n"


def _related_tables(query: str, session_id: str | None, active_columns: list[str]) -> str:
    """Only surfaces other workspace tables that plausibly relate to this question."""
    schemas = context_retriever.retrieve_related_schemas(query, session_id, active_columns)
    if not schemas:
        return ""

    lines = ["\n<other_workspace_tables>"]
    for schema in schemas:
        columns = ", ".join(str(c) for c in schema.get("columns", [])[:25])
        lines.append(f"- `{schema['filename']}` ({schema.get('row_count', 0)} rows): {columns}")
        shared = sorted({str(c).lower() for c in schema.get("columns", [])} & {str(c).lower() for c in active_columns})
        if shared:
            lines.append(f"  Possible join keys: {', '.join(shared[:5])}")
    lines.append("Load these with `pd.read_csv('/workspace/<filename>')` only if the request needs them.")
    lines.append("</other_workspace_tables>\n")
    return "\n".join(lines)


def generate_system_context(
    df: pd.DataFrame,
    catalog: dict[str, Any] | None = None,
    query: str = "",
    session_id: str | None = None,
    max_columns: int | None = None,
) -> str:
    """Builds a size-bounded description of the active dataset."""
    columns, truncated = context_retriever.select_columns(query or "", df, max_columns)

    truncation_note = ""
    if truncated:
        truncation_note = (
            f"\n*Showing {len(columns)} of {len(df.columns)} columns, selected for relevance. "
            f"All {len(df.columns)} columns exist on `df` and can be referenced by name.*\n"
        )

    subset = df[columns] if columns else df

    numeric = subset.select_dtypes(include="number")
    if not numeric.empty:
        statistics = numeric.describe().T[["count", "mean", "std", "min", "max"]].round(3).to_markdown()
    else:
        statistics = "*No numeric columns in scope.*"

    try:
        glimpse = subset.head(3).to_markdown(index=False)
    except Exception:
        buffer = io.StringIO()
        subset.head(3).to_string(buf=buffer)
        glimpse = buffer.getvalue()

    semantic_lines = []
    if catalog:
        for column, meta in list(catalog.get("columns", {}).items()):
            if column not in columns:
                continue
            semantic_type = meta.get("semantic_type", "unknown")
            semantic_lines.append(f"- **{column}**: `{semantic_type}`")
    semantic_block = "\n".join(semantic_lines[:30]) if semantic_lines else "*Not profiled.*"

    return f"""<dataset_context>
Shape: {len(df):,} rows x {len(df.columns)} columns.
{truncation_note}
<schema>
{_describe_columns(subset, columns)}
</schema>

<data_glimpse>
{glimpse}
</data_glimpse>

<numeric_summary>
{statistics}
</numeric_summary>
{_quality_warnings(df, columns)}
<categorical_insights>
{_categorical_insights(df, columns)}
</categorical_insights>

<semantic_types>
{semantic_block}
</semantic_types>{_related_tables(query, session_id, columns)}
</dataset_context>"""


def create_cleaning_prompt(df: pd.DataFrame, catalog: dict[str, Any]) -> str:
    """Asks the worker to emit a cleaning script for the uploaded frame."""
    context = generate_system_context(df, catalog, query="clean missing values types")

    return f"""<role>
You are a senior data engineer. Produce a short, safe cleaning script for the dataset below.
</role>

{context}

<rules>
1. Operate on the existing DataFrame named `df`. Do not load any file.
2. Handle missing values sensibly (median for numeric, mode or a literal for categorical).
3. Convert columns whose contents are clearly numeric or date-like to the right dtype.
4. Strip surrounding whitespace from text columns.
5. NEVER assign the whole frame to a column (`df['x'] = df` is forbidden).
6. Do not drop more than 10% of rows.
7. Do not print anything. Do not create plots.
8. If the data already looks clean, emit `pass`.
</rules>

<instructions>
Return ONLY a Python code block. No prose.
</instructions>"""


def create_simple_prompt(instruction: str, columns: list[str]) -> str:
    """Minimal prompt used for trivially simple requests."""
    return f"""<role>
You are an expert Python data analyst working in a headless sandbox.
</role>

<dataset_context>
A pandas DataFrame named `df` is already loaded with columns: {columns}
</dataset_context>

<user_request>
{instruction}
</user_request>

<instructions>
1. Write Python that answers the request directly.
2. `print()` whatever the user asked to see.
3. Never reload `df` from disk and never call `input()`.
4. Return ONLY a Python code block.
</instructions>"""


#: What the execution environment can actually do, grouped by the kind of
#: question it answers. Each entry carries the import names it depends on, so
#: the block can be filtered to what is genuinely importable.
#:
#: The worker prompt used to declare only `pd`, `np`, `plt` and `sns`, so the
#: model had no idea it could fit a model, run a hypothesis test or query with
#: SQL -- and duly wrote hand-rolled loops for things scikit-learn and statsmodels
#: were sitting right there to do. Anything added to `backend/docker/Dockerfile`
#: belongs here too, or it may as well not be installed.
TOOLKIT: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Dataframes & numerics", "pandas (`pd`), numpy (`np`), pyarrow", ("pandas", "numpy")),
    (
        "SQL over dataframes",
        "duckdb — `duckdb.sql('SELECT ... FROM df').df()`, joins and window functions included",
        ("duckdb",),
    ),
    (
        "Statistics & inference",
        "scipy.stats, statsmodels (OLS/GLM, ANOVA, ARIMA/SARIMAX, seasonal decomposition)",
        ("scipy", "statsmodels"),
    ),
    ("Machine learning", "scikit-learn, xgboost, lightgbm", ("sklearn",)),
    ("Survival & duration", "lifelines (Kaplan-Meier, Cox proportional hazards)", ("lifelines",)),
    ("Graphs & networks", "networkx (centrality, communities, shortest paths)", ("networkx",)),
    ("Geospatial", "geopandas, shapely", ("geopandas",)),
    ("Charts", "plotly (`px`, `go`), matplotlib (`plt`), seaborn (`sns`)", ("matplotlib",)),
    (
        "File output",
        "openpyxl and xlsxwriter for .xlsx, pyarrow for parquet, all under `/workspace/`",
        ("openpyxl",),
    ),
)


@lru_cache(maxsize=1)
def _importable() -> frozenset[str]:
    """Modules importable in *this* process.

    Only consulted on the Docker-less path. Advertising duckdb to a model that
    is about to run in the API process, where it is not installed, produces a
    confident ImportError and burns a correction retry -- the prompt has to
    describe the environment the code will actually meet.
    """
    from importlib.util import find_spec

    available = set()
    for _, _, modules in TOOLKIT:
        for module in modules:
            try:
                if find_spec(module) is not None:
                    available.add(module)
            except (ImportError, ValueError):
                continue
    return frozenset(available)


def _toolkit_block() -> str:
    from src.core.tools.sandbox import sandbox_pool

    # The container is built from `docker/Dockerfile` and has the full set; the
    # local fallback has only whatever the backend itself installed.
    entries = TOOLKIT
    if not sandbox_pool.available:
        importable = _importable()
        entries = tuple(entry for entry in TOOLKIT if all(module in importable for module in entry[2]))

    lines = [f"- **{area}**: {libraries}" for area, libraries, _ in entries]
    if not sandbox_pool.available:
        lines.append("- *Nothing else is installed. Do not import a library that is not listed above.*")
    return "\n".join(lines)


def _visualization_rules() -> str:
    if settings.PLOT_FORMAT == "html":
        return (
            "6. Visualizations: use Plotly (`import plotly.express as px`). Save the primary figure with "
            "`fig.write_html('/workspace/plot.html', include_plotlyjs='cdn')`. Do not print raw HTML and "
            "do not call `fig.show()`."
        )
    return (
        "6. Visualizations: use `matplotlib.pyplot` (`plt`) or `seaborn` (`sns`). The active figure is captured "
        "automatically -- do not save it and do not call `plt.show()`."
    )


def create_prompt(
    instruction: str,
    df: pd.DataFrame,
    plan: str | None = None,
    previous_error: str | None = None,
    catalog: dict[str, Any] | None = None,
    few_shot_examples: list[dict[str, str]] | None = None,
    previous_code: str | None = None,
    session_id: str | None = None,
    negative_example: str | None = None,
) -> str:
    """Worker prompt: turn an approved plan into executable Python."""
    context = generate_system_context(df, catalog=catalog, query=instruction, session_id=session_id)

    plan_block = f"\n<approved_plan>\n{plan}\n</approved_plan>\n" if plan else ""

    error_block = ""
    if previous_error:
        error_block = (
            f"\n<previous_error>\n{previous_error}\n</previous_error>\n"
            "<error_handling>\nThe previous attempt failed. Read the traceback line by line, identify the exact "
            "variable or column that caused it, and write corrected code that still fulfils the plan. "
            "Do not apologise and do not explain -- just fix it.\n</error_handling>\n"
        )

    revision_block = ""
    if previous_code:
        revision_block = (
            f"\n<previous_code>\n{previous_code}\n</previous_code>\n"
            "<revision_instruction>\nThe user wants to refine the output above. Keep the data logic and change "
            "only what they asked for.\n</revision_instruction>\n"
        )

    examples_block = ""
    if few_shot_examples:
        parts = ["\n<worked_examples>"]
        for index, example in enumerate(few_shot_examples, start=1):
            parts.append(f"Example {index} - {example.get('task')}:\n```python\n{example.get('code')}\n```")
        parts.append("</worked_examples>\n")
        examples_block = "\n".join(parts)

    negative_block = f"\n<avoid_this>\n{negative_example}\n</avoid_this>\n" if negative_example else ""

    return f"""<role>
You are an expert Python code generator inside a secure, headless data science sandbox.
Translate the request into flawless, executable Python.
</role>
{examples_block}
<environment>
1. Headless and non-interactive. Never call `input()`.
2. The active dataset is ALREADY loaded as a pandas DataFrame named `df`. Never reload it from disk.
3. Every other table in this session is loaded too, in the dict `tables` keyed by name. Join
   across them directly -- `tables['orders'].merge(tables['customers'], on='customer_id')`.
4. `pd`, `np`, `plt`, `sns`, `px` and `go` are already imported. Everything else must be imported.
5. Print anything the user should see. Results that are not printed are invisible.
6. Never print a whole DataFrame -- use `.head()`, `.describe()` or an aggregation.
{_visualization_rules()}
8. File writes are permitted only under `/workspace/`.
9. The `os`, `sys`, `subprocess` and networking modules are unavailable.
</environment>

<available_libraries>
{_toolkit_block()}

Use the right tool for the job. Write vectorised pandas or a duckdb query rather than a Python
loop over rows, and use the library that already implements a method rather than reimplementing it.
</available_libraries>

{context}
{plan_block}{error_block}{revision_block}{negative_block}
<user_request>
{instruction}
</user_request>

<instructions>
Write the Python that fulfils the request. Return ONLY one ```python code block, no commentary.
</instructions>"""


def create_planning_prompt(
    instruction: str,
    df: pd.DataFrame,
    catalog: dict[str, Any] | None = None,
    mode: str = "standard",
    memory_context: str = "",
    previous_code: str | None = None,
    session_id: str | None = None,
    history: str = "",
) -> str:
    """Manager prompt: produce a plan, not code."""
    context = generate_system_context(df, catalog=catalog, query=instruction, session_id=session_id)

    revision_block = ""
    if previous_code:
        revision_block = (
            f"\n<previous_code>\n{previous_code}\n</previous_code>\n"
            "<revision_instruction>\nPlan only the visual/formatting changes the user asked for; the data logic "
            "already works.\n</revision_instruction>\n"
        )

    if mode == "fast":
        return f"""<role>
You are a fast data analysis planner. Produce a terse, numbered implementation plan. No deep reasoning.
</role>

{context}
{history}{revision_block}
<user_request>
{instruction}
</user_request>

<instructions>
Output ONLY a numbered list of 2-5 concrete steps a single Python script can execute.
</instructions>"""

    return f"""<role>
You are the principal data scientist for an analytics team. You design the analysis; a separate
coding engine implements it. You never write code yourself.
</role>

{context}
{memory_context}{history}{revision_block}
<user_request>
{instruction}
</user_request>

<instructions>
1. Open with a `<thought>...</thought>` block containing your private reasoning: what the user is really
   asking, which columns matter, what could go wrong with this specific data.
2. Then output a numbered plan of 2-6 concrete, executable steps.
3. Reference real column names from the schema above. Never invent a column.
4. State any statistical assumption you are relying on (normality, independence, sample size).
5. If and only if the request depends on facts outside this dataset, emit a single line
   `SEARCH: "your query"` and stop.
6. Do not write Python.
</instructions>"""


def create_replan_prompt(instruction: str, search_results: list[dict[str, Any]], original_thought: str) -> str:
    """Revises a plan after an approved web search."""
    formatted = (
        "\n".join(f"- {item.get('title', 'Untitled')}: {item.get('snippet', '')}" for item in search_results[:5])
        or "- No usable results were returned."
    )

    return f"""<role>
You are the principal data scientist. You paused to search the web; the results are below.
</role>

<original_reasoning>
{original_thought}
</original_reasoning>

<search_results>
{formatted}
</search_results>

<user_request>
{instruction}
</user_request>

<instructions>
Produce the final numbered plan, incorporating anything useful from the search results.
Do not emit another SEARCH line. Do not write Python.
</instructions>"""


def create_decision_prompt(
    instruction: str,
    plan: str,
    transcript: str,
    iteration: int,
    remaining: int,
    allowed: list[str],
    findings: list[str] | None = None,
) -> str:
    """Manager prompt: choose the next action from what has actually happened.

    This is the heart of the loop. It is written to be answerable by a small
    model: a fixed two-line output format, an explicit menu, and a stated budget
    so the model can see it is running out of room rather than being cut off.
    """
    menu = {
        "inspect": "inspect  — look at the data (schema, distributions, nulls, sample rows). Costs nothing.",
        "code": "code     — write and run Python for one concrete sub-task.",
        "consult": "consult  — search the attached reference documents for a definition or rule.",
        "reflect": "reflect  — revise the plan because what you found changed the problem.",
        "answer": "answer   — you have enough to answer the question. Stop and write it.",
    }
    options = "\n".join(menu[name] for name in allowed if name in menu)

    findings_block = ""
    if findings:
        joined = "\n".join(f"- {item}" for item in findings)
        findings_block = f"\n<established_so_far>\n{joined}\n</established_so_far>\n"

    urgency = ""
    if remaining <= 1:
        urgency = (
            "\nThis is your LAST iteration. Choose `answer` and work with what you have, "
            "stating clearly what remains unknown.\n"
        )
    elif remaining <= 2:
        urgency = f"\nOnly {remaining} iterations remain. Start converging.\n"

    return f"""<role>
You are directing a data analysis. You do not write code yourself -- you decide the next move,
and a coding engine carries it out. You have already seen the results below; use them.
</role>

<question>
{instruction}
</question>

<working_plan>
{plan}
</working_plan>
{findings_block}
<what_has_happened>
{transcript}
</what_has_happened>

<budget>
Iteration {iteration}. {remaining} remaining.
</budget>
{urgency}
<options>
{options}
</options>

<instructions>
Decide the single next action. Answer in EXACTLY this format and nothing else:

ACTION: <one word from the options above>
GOAL: <one sentence describing precisely what that action should achieve>

Rules:
- Choose `answer` as soon as the question is genuinely answered. Do not keep exploring.
- Do not repeat an action that has already produced the result you need.
- If a previous step failed, the goal should address why it failed.
- The goal must be one concrete sub-task, not a restatement of the whole question.
</instructions>"""


def create_reflection_prompt(instruction: str, plan: str, transcript: str) -> str:
    """Manager prompt: rewrite the plan in light of what execution revealed."""
    return f"""<role>
You are the principal data scientist. Your plan met the real data, and now you are revising it.
</role>

<question>
{instruction}
</question>

<previous_plan>
{plan}
</previous_plan>

<what_the_data_showed>
{transcript}
</what_the_data_showed>

<instructions>
1. State in one line what you learned that the previous plan did not anticipate.
2. Then output the revised numbered plan: only the steps that still need doing.
3. Reference real column names and real values seen above. Never invent one.
4. If the previous plan is still correct, say so in one line and repeat it unchanged.
5. Do not write Python.
</instructions>"""


def create_verification_prompt(instruction: str, code: str, output: str) -> str:
    """Worker prompt: re-derive the headline result by a different route.

    An independent recomputation catches the errors a self-review never does --
    a wrong join grain, a filter applied in the wrong order, a mean over the
    wrong denominator all produce confident, plausible, wrong numbers.
    """
    trimmed = output if len(output) <= 2000 else output[:2000] + "\n... (truncated)"
    return f"""<role>
You are verifying someone else's analysis. Assume it may be wrong.
</role>

<question>
{instruction}
</question>

<analysis_that_ran>
```python
{code}
```
</analysis_that_ran>

<result_it_produced>
{trimmed}
</result_it_produced>

<instructions>
Write Python that recomputes the SAME headline number by a DIFFERENT route -- a different
aggregation path, a reconciliation against row counts or totals, or a bounds check.

1. Do not copy the approach above. If it used groupby, use a pivot or a duckdb query.
2. Print a line starting `VERIFIED:` when your number matches, or `MISMATCH:` when it does not,
   followed by both values.
3. Also print any sanity violation you find (negative counts, percentages over 100,
   totals exceeding the population).
4. Keep it short. Return ONLY one ```python code block.
</instructions>"""


def create_answer_prompt(
    instruction: str,
    code: str,
    output: str,
    plan: str = "",
    findings: list[str] | None = None,
    assumptions: list[str] | None = None,
    verification: str = "",
) -> str:
    """Turns a completed investigation into a written answer.

    Without this the UI showed unformatted stdout, which is why the frontend had
    accumulated regexes that stripped tracebacks and numeric rows out of the
    response -- deleting real analytical output in the process.

    The output budget is generous and the truncation is *middle-out*: a tail-cut
    threw away exactly the summary lines an analysis prints last, which is where
    the answer usually lives.
    """
    trimmed = _middle_out(output, 12000)

    plan_block = f"\n<plan_followed>\n{plan}\n</plan_followed>\n" if plan else ""

    findings_block = ""
    if findings:
        joined = "\n".join(f"- {item}" for item in findings)
        findings_block = f"\n<findings>\n{joined}\n</findings>\n"

    assumptions_block = ""
    if assumptions:
        joined = "\n".join(f"- {item}" for item in assumptions)
        assumptions_block = (
            f"\n<assumptions_made>\n{joined}\n</assumptions_made>\n"
            "<assumption_handling>\nThese are reported to the user separately. Mention one only "
            "when it materially changes how the headline number should be read.\n</assumption_handling>\n"
        )

    verification_block = f"\n<verification_result>\n{verification}\n</verification_result>\n" if verification else ""

    return f"""<role>
You are a data analyst explaining a finished result to the person who asked for it.
</role>

<user_request>
{instruction}
</user_request>
{plan_block}{findings_block}
<code_executed>
```python
{code}
```
</code_executed>

<execution_output>
{trimmed}
</execution_output>
{verification_block}{assumptions_block}
<instructions>
1. Answer the question directly in the first sentence, using the actual numbers from the output.
2. Add 2-4 sentences of interpretation: what the numbers mean, notable patterns, what they imply.
3. Preserve any table in the output as a markdown table.
4. EVERY number you write must appear in the execution output above. Do not round into a figure
   that is not there, do not compute a new one, do not estimate. If you need a number that was
   not computed, say it was not computed.
5. If verification reported a mismatch, lead with that -- the result is not trustworthy.
6. If the output is an error, explain the cause in plain language and suggest the fix.
7. Do not repeat the code. Do not describe what you are about to do.
</instructions>"""


def _middle_out(text: str, limit: int) -> str:
    """Trims from the middle, keeping both ends.

    Analysis output puts context first and conclusions last; cutting the tail
    removes the answer, and cutting the head removes what it is an answer about.
    """
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n\n... [{omitted:,} characters of output omitted] ...\n\n{text[-tail:]}"
