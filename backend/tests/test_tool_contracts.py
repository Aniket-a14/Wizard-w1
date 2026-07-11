import pandas as pd
import pytest
from src.core.tools.evaluator import Evaluator
from src.core.tools.search import WebSearchTool
from src.core.tools.stats import StatisticalToolkit


def test_score_execution_rewards_scientific_and_expected_content():
    result = "Mean and variance are reported. The distribution is significant."
    scored = Evaluator.score_execution(result, expected_snippet="variance")

    assert 70 <= scored["score"] <= 100
    assert scored["status"] == "PASS"
    assert isinstance(scored["deductions"], list)


def test_score_execution_penalizes_errors_and_missing_expectations():
    strong = Evaluator.score_execution(
        "Mean and variance are reported. The distribution is significant.",
        expected_snippet="variance",
    )
    weak = Evaluator.score_execution(
        "Error while running task.",
        expected_snippet="variance",
    )

    assert weak["score"] < strong["score"]
    assert weak["status"] == "FAIL"


@pytest.mark.parametrize(
    "code,is_clean",
    [
        ("import pandas as pd\ndf = pd.DataFrame({'a':[1,2]})", True),
        ("exec('print(1)')", False),
    ],
)
def test_evaluate_code_quality_contract(code, is_clean):
    report = Evaluator.evaluate_code_quality(code)

    assert report["is_clean"] is is_clean
    assert isinstance(report["warnings"], list)
    assert report["quality_rating"] in {"High", "Low"}


def test_web_search_unknown_backend_returns_empty_list():
    tool = WebSearchTool(backend="unsupported")
    assert tool.search("python", num_results=3) == []


def test_web_search_duckduckgo_delegates_to_backend_method(monkeypatch):
    tool = WebSearchTool(backend="duckduckgo")
    expected = [{"title": "A", "link": "B", "snippet": "C"}]

    def fake_backend(query, num_results):
        assert query == "agent testing"
        assert num_results == 2
        return expected

    monkeypatch.setattr(tool, "_duckduckgo_search", fake_backend)
    assert tool.search("agent testing", num_results=2) == expected


def test_mock_results_shape_is_stable():
    query = "regression testing"
    results = WebSearchTool()._get_mock_results(query)

    assert len(results) >= 1
    assert {"title", "link", "snippet"}.issubset(results[0].keys())
    assert query in results[0]["title"] or query in results[0]["snippet"]


def test_check_normality_handles_insufficient_samples():
    df = pd.DataFrame({"x": [1.0, 2.0]})
    result = StatisticalToolkit.check_normality(df, "x")

    assert result["is_normal"] is False
    assert result["p_value"] is None
