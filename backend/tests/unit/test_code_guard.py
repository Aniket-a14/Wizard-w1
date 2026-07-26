"""Unit + negative tests for the static code guard.

The guard is the only thing standing between model output and an interpreter on
the paths where Docker is unavailable, so both directions matter: it must block
escapes, and it must not block ordinary analysis code.
"""

from __future__ import annotations

import pytest

from src.core.security.code_guard import (
    ALLOWED_PATH_ROOTS,
    CodeGuard,
    _is_path_allowed,
    is_safe_identifier,
)


# --------------------------------------------------------------------------- #
# Positive: legitimate analysis code must pass
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "code",
    [
        "print(df.head())",
        "import pandas as pd\nprint(pd.DataFrame({'a': [1, 2]}).mean())",
        "import matplotlib.pyplot as plt\nplt.plot([1, 2], [3, 4])",
        "import numpy as np\nprint(np.mean(df['A']))",
        "result = df.groupby('B')['A'].mean()\nprint(result)",
        "with open('/workspace/out.csv', 'w') as handle:\n    handle.write('a,b')",
        "df.to_csv('/workspace/result.csv', index=False)",
        "df.to_csv('nested/result.csv')",
        "import plotly.express as px\nfig = px.bar(df, x='B', y='A')\nfig.write_html('/workspace/plot.html')",
        "from scipy import stats\nprint(stats.ttest_1samp(df['A'], 0))",
        "import seaborn as sns\nsns.heatmap(df.corr(numeric_only=True))",
        # A column literally named "os" must not trip the guard; the previous
        # regex denylist matched the bare word anywhere in the source.
        "print(df['os'].value_counts())",
        "requests_per_day = df['A'].sum()\nprint(requests_per_day)",
    ],
)
def test_allows_legitimate_analysis(code: str) -> None:
    verdict = CodeGuard.scan(code)
    assert verdict.ok, f"unexpectedly blocked: {verdict.reason}"


# --------------------------------------------------------------------------- #
# Negative: escapes must be blocked
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "code",
    [
        "import os\nos.system('id')",
        "import subprocess\nsubprocess.run(['ls'])",
        "from os import system\nsystem('id')",
        "__import__('os').system('id')",
        "eval('1 + 1')",
        "exec('import os')",
        "compile('x=1', '<s>', 'exec')",
        "import socket\nsocket.socket()",
        "import requests\nrequests.get('http://example.com')",
        "import urllib.request\nurllib.request.urlopen('http://x')",
        "import importlib\nimportlib.import_module('os')",
        "import ctypes",
        "import pickle\npickle.loads(b'')",
        "import shutil\nshutil.rmtree('/')",
        "import multiprocessing",
        # Interpreter-internals walks used to reach os from a benign object.
        "print(().__class__.__bases__[0].__subclasses__())",
        "print((lambda: 0).__globals__)",
        "print(open.__self__.__dict__)",
        "x = globals()",
        "import sys\nsys.exit(1)",
    ],
)
def test_blocks_escape_attempts(code: str) -> None:
    verdict = CodeGuard.scan(code)
    assert not verdict.ok
    assert not verdict.syntax_error, "an escape must be a policy violation, not a syntax error"
    assert verdict.reason


@pytest.mark.parametrize(
    "code",
    [
        "getattr(__builtins__, 'ev' + 'al')('1')",
        "getattr(obj, name)()",
        "setattr(obj, key, value)",
        "getattr(df, '__class__')",
        "print(__builtins__)",
        "x = __loader__",
    ],
)
def test_blocks_reflection_used_to_rebuild_banned_calls(code: str) -> None:
    """A computed attribute name defeats every name-based check, so reflection
    is only permitted with a literal, non-restricted attribute."""
    assert not CodeGuard.scan(code).ok


@pytest.mark.parametrize(
    "code",
    [
        "print(getattr(df, 'shape'))",
        "value = getattr(row, 'name', None)",
        "hasattr(df, 'columns')",
    ],
)
def test_allows_reflection_with_literal_safe_attributes(code: str) -> None:
    assert CodeGuard.scan(code).ok


@pytest.mark.parametrize(
    "code",
    [
        "open('/etc/passwd')",
        "open('../../etc/passwd')",
        "open('/workspace/../etc/shadow')",
        "df.to_csv('/etc/cron.d/payload')",
        "open('file:///etc/passwd')",
        "open('\\\\\\\\server\\\\share\\\\file')",
    ],
)
def test_blocks_path_traversal(code: str) -> None:
    verdict = CodeGuard.scan(code)
    assert not verdict.ok
    assert "workspace" in verdict.reason.lower() or "not permitted" in verdict.reason.lower()


# --------------------------------------------------------------------------- #
# Syntax errors are retryable, not policy violations
# --------------------------------------------------------------------------- #
def test_syntax_error_is_flagged_as_retryable() -> None:
    verdict = CodeGuard.scan("def broken(:\n  pass")
    assert not verdict.ok
    assert verdict.syntax_error
    assert verdict.retryable


def test_empty_code_is_rejected() -> None:
    assert not CodeGuard.scan("").ok
    assert not CodeGuard.scan("   \n  ").ok


# --------------------------------------------------------------------------- #
# Path resolution
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path,expected",
    [
        ("/workspace/a.csv", True),
        ("/workspace/nested/deep/a.csv", True),
        ("relative.csv", True),
        ("./relative.csv", True),
        ("/workspace/../workspace/ok.csv", True),
        ("/etc/passwd", False),
        ("../escape.csv", False),
        ("/workspacefoo/a.csv", False),
        ("", False),
        ("http://example.com/a.csv", False),
    ],
)
def test_path_allowlist(path: str, expected: bool) -> None:
    assert _is_path_allowed(path) is expected


def test_allowed_roots_are_absolute_posix() -> None:
    assert all(root.startswith("/") for root in ALLOWED_PATH_ROOTS)


# --------------------------------------------------------------------------- #
# Repair
# --------------------------------------------------------------------------- #
def test_repair_strips_markdown_fences() -> None:
    parses, code = CodeGuard.repair("```python\nprint(1)\n```")
    assert parses
    assert code == "print(1)"


def test_repair_adds_missing_alias_imports() -> None:
    """A missing import is a runtime NameError, not a SyntaxError.

    Healing therefore has to run on code that already parses, which is the case
    the original implementation could never reach.
    """
    parses, code = CodeGuard.repair("result = pd.DataFrame({'a': [1]})\nprint(result)")
    assert parses
    assert code.startswith("import pandas as pd")
    assert "result = pd.DataFrame" in code


def test_repair_does_not_duplicate_existing_imports() -> None:
    original = "import pandas as pd\nprint(pd.DataFrame({'a': [1]}))"
    parses, code = CodeGuard.repair(original)
    assert parses
    assert code.count("import pandas as pd") == 1


def test_repair_heals_several_aliases_at_once() -> None:
    parses, code = CodeGuard.repair("plt.plot(np.arange(3))")
    assert parses
    assert "import numpy as np" in code
    assert "import matplotlib.pyplot as plt" in code


def test_repair_leaves_valid_code_untouched() -> None:
    original = "x = 1\nprint(x)"
    parses, code = CodeGuard.repair(original)
    assert parses
    assert code == original


def test_repair_reports_failure_for_unfixable_code() -> None:
    parses, _ = CodeGuard.repair("def f(:\n pass")
    assert not parses


# --------------------------------------------------------------------------- #
# Identifier validation (guards values interpolated into generated source)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["df", "result_2", "myVar"])
def test_accepts_plain_identifiers(name: str) -> None:
    assert is_safe_identifier(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "__builtins__",
        "a b",
        "a'; import os; x='",
        "../etc/passwd",
        "1abc",
        "x" * 200,
    ],
)
def test_rejects_unsafe_identifiers(name: str) -> None:
    assert not is_safe_identifier(name)
