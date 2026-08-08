"""Phase 1.1 reference-answer key, as data.

Computed independently against the real `workspace/dataset.csv` (307 rows x 16
columns) and `workspace/housing.csv` (5 rows) with plain pandas -- no LLM call.
See docs/benchmark-methodology-spec.md 1.1 for the full narrative, including why
A1 and C1's "correct" answers are not what the original report assumed
(`ethnicgroup` is 100% null in the real data).

Each entry's `expected_numbers` is the set of values that MUST appear (within
check_grounding's own rounding tolerance) in real execution output for the turn
to be graded correct. `must_mention` is free text the answer must contain
(case-insensitive substring), used for the qualitative checks 1.1 identifies
(e.g. A1 must name `ethnicgroup` as unusable, not silently produce a table).
`forbidden_if_present` catches a specific, previously-observed fabrication
pattern for a test (e.g. an englishgrade figure above the column's real max).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReferenceCase:
    id: str
    category: str
    name: str
    prompt: str
    dataset: str
    expected_numbers: tuple[float, ...] = ()
    must_mention: tuple[str, ...] = ()
    forbidden_if_present: tuple[str, ...] = ()
    notes: str = ""


REFERENCE_CASES: list[ReferenceCase] = [
    ReferenceCase(
        id="A1",
        category="Tabular User Story",
        name="Grouping & Multi-Index Aggregation",
        prompt="Calculate the mean mathgrade and sciencesgrade grouped by gender and ethnicgroup.",
        dataset="dataset.csv",
        must_mention=("ethnicgroup",),
        notes=(
            "ethnicgroup is 100% null (307/307). Correct behavior states this and does not "
            "present a populated group-by table -- any numeric table for this grouping is fabricated."
        ),
    ),
    ReferenceCase(
        id="A2",
        category="Tabular User Story",
        name="Percentile Ranking",
        prompt="Identify students who score in the top 10th percentile for englishgrade.",
        dataset="dataset.csv",
        expected_numbers=(3.9, 67),
        notes="90th-percentile threshold = 3.9; 67 students meet or exceed it.",
    ),
    ReferenceCase(
        id="A3",
        category="Tabular User Story",
        name="Feature Engineering",
        prompt="Create a new composite score column as the average of mathgrade and sciencesgrade, and display the top 5 rows.",
        dataset="dataset.csv",
        expected_numbers=(4.0, 3.95),
        notes="Top result: id 286 at composite 4.00. Next four all at 3.95 (ties).",
    ),
    ReferenceCase(
        id="B1",
        category="Statistical Analysis",
        name="Pearson Correlation Matrix",
        prompt="Compute the Pearson correlation matrix for age, englishgrade, mathgrade, sciencesgrade, and languagegrade.",
        dataset="dataset.csv",
        expected_numbers=(-0.097, 0.018, -0.002),
        must_mention=("weak",),
        forbidden_if_present=("moderate", "strong"),
        notes="Every off-diagonal value is weak; the largest magnitude is -0.097 (age vs sciencesgrade).",
    ),
    ReferenceCase(
        id="B2",
        category="Statistical Analysis",
        name="Summary Statistics & Variance",
        prompt="Calculate the variance, standard deviation, and interquartile range for mathgrade.",
        dataset="dataset.csv",
        expected_numbers=(0.2274, 0.4768, 0.70),
    ),
    ReferenceCase(
        id="C1",
        category="Data Quality & Ingestion",
        name="Missing Values & Profiling",
        prompt="Check if there are missing values in any column and report completeness percentage.",
        dataset="dataset.csv",
        expected_numbers=(93.75,),
        must_mention=("ethnicgroup",),
        forbidden_if_present=("100.00%", "100%", "no missing values"),
        notes="Real overall completeness is 93.75%, not 100% -- ethnicgroup is entirely null.",
    ),
    ReferenceCase(
        id="C2",
        category="Data Quality & Edge Cases",
        name="Edge Dataset Size (5 rows)",
        prompt="Summarize the dataset and compute average price.",
        dataset="housing.csv",
        expected_numbers=(374000,),
    ),
    ReferenceCase(
        id="C3",
        category="Data Quality & Edge Cases",
        name="Non-Existent Column Handling",
        prompt="Calculate the average salary of students.",
        dataset="dataset.csv",
        must_mention=("salary", "not"),
        notes="No `salary` column in either dataset. Must name the missing column, not substitute a different one silently.",
    ),
    ReferenceCase(
        id="D1",
        category="Visualization User Story",
        name="Histogram Distribution Plot",
        prompt="Create a histogram showing the distribution of mathgrade and save the plot.",
        dataset="dataset.csv",
        notes="No single numeric answer. Graded on: code executes without error, no invented statistics in the answer.",
    ),
    ReferenceCase(
        id="D2",
        category="Visualization User Story",
        name="Scatter Plot with Trendline",
        prompt="Plot a scatter plot comparing age versus englishgrade.",
        dataset="dataset.csv",
        forbidden_if_present=("strong correlation", "moderate correlation"),
        notes="Real age-vs-englishgrade correlation is -0.002 (essentially none) -- claiming a visible trend is a fail.",
    ),
    ReferenceCase(
        id="cloud_single_turn",
        category="Cloud single-turn",
        name="Top-5 englishgrade students, mean age",
        prompt="Identify top 5 highest scoring students in englishgrade and calculate their mean age.",
        dataset="dataset.csv",
        expected_numbers=(20.6, 20.60),
    ),
    ReferenceCase(
        id="hybrid_single_turn",
        category="Hybrid single-turn",
        name="Avg mathgrade + count by gender",
        prompt="Calculate average mathgrade and count of students grouped by gender.",
        dataset="dataset.csv",
        expected_numbers=(3.394079, 3.435099, 152, 151, 4),
    ),
    ReferenceCase(
        id="model_speed_comparison",
        category="Model speed comparison",
        name="Mean/median age & englishgrade",
        prompt="Calculate mean and median for age and englishgrade.",
        dataset="dataset.csv",
        expected_numbers=(21.964, 22.0, 3.370, 3.5),
        forbidden_if_present=(),
        notes=(
            "englishgrade never exceeds ~4.0 in this dataset -- any reported englishgrade figure "
            "above 5 (the original 1.5B run reported 85) is an automatic, no-further-checking fail."
        ),
    ),
]


def by_id(case_id: str) -> ReferenceCase | None:
    return next((c for c in REFERENCE_CASES if c.id == case_id), None)
