"""Static analysis gate for model-generated Python.

This is the single authority on whether generated code may run. It replaces the
previous split between a regex denylist and an inline AST walk in the agent,
which disagreed with each other (``open()`` was excluded from one because the
other handled it) and could only be applied on one of the two execution paths.

Design notes
------------
* AST-based, not regex-based. Regex matching on source text produced false
  positives on ordinary analysis code -- a column literally named ``"os"`` or a
  DataFrame column ``requests.`` inside a string tripped the old denylist.
* The sandbox container is the security boundary; this layer is defence in depth
  that also catches the *un*sandboxed paths (semantic cleaning, Docker-less
  fallback) which previously had no checks at all.
* Syntax errors are reported as a distinct verdict so the caller can route them
  into the self-correction loop instead of treating them as an attack.
"""

from __future__ import annotations

import ast
import posixpath
from dataclasses import dataclass, field


# Modules that give direct process, filesystem or network control.
BANNED_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "ctypes",
        "importlib",
        "imp",
        "pty",
        "signal",
        "multiprocessing",
        "threading",
        "asyncio",
        "pickle",
        "marshal",
        "shelve",
        "dill",
        "requests",
        "urllib",
        "urllib2",
        "urllib3",
        "http",
        "ftplib",
        "telnetlib",
        "smtplib",
        "paramiko",
        "webbrowser",
        "resource",
        "pwd",
        "grp",
        "tempfile",
    }
)

# Builtins that turn data into executable code or reach around the sandbox.
BANNED_CALLS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "memoryview",
        "exit",
        "quit",
    }
)

# Bare names that expose the interpreter regardless of how they are used.
BANNED_NAMES = frozenset({"__builtins__", "__loader__", "__spec__", "__debug__"})

# Reflection helpers. Safe with a literal attribute name, dangerous with a
# computed one: `getattr(__builtins__, 'ev' + 'al')` reconstructs a banned call
# out of fragments that individually look harmless.
REFLECTION_CALLS = frozenset({"getattr", "setattr", "delattr", "hasattr"})

# Attribute names used to walk from a harmless object to the interpreter internals.
BANNED_ATTRIBUTES = frozenset(
    {
        "__subclasses__",
        "__bases__",
        "__base__",
        "__mro__",
        "__globals__",
        "__code__",
        "__closure__",
        "__builtins__",
        "__loader__",
        "__reduce__",
        "__reduce_ex__",
        # `open.__self__` reaches the builtins module, and `__dict__` walks an
        # object's namespace; both are standard first hops out of a sandbox.
        "__self__",
        "__dict__",
        "__func__",
        "__wrapped__",
        "__getattribute__",
        "__init_subclass__",
        "system",
        "popen",
        "spawn",
        "fork",
        "execv",
        "execve",
        "kill",
    }
)

# Roots the generated code may read from / write to inside the sandbox.
ALLOWED_PATH_ROOTS = ("/workspace", "/tmp/wizard")

# Functions whose first positional argument is a filesystem path we must check.
PATH_ARG_FUNCTIONS = frozenset({"open", "read_csv", "read_parquet", "read_feather", "read_json", "read_excel"})
PATH_ARG_METHODS = frozenset(
    {
        "to_csv",
        "to_parquet",
        "to_feather",
        "to_json",
        "to_excel",
        "to_pickle",
        "savefig",
        "write_html",
        "write_image",
        "write_json",
    }
)


@dataclass
class GuardVerdict:
    """Outcome of a scan.

    ``ok`` means the code may execute. ``syntax_error`` distinguishes malformed
    output (retryable, feed the message back to the model) from a policy
    violation (not retryable, surface to the user).
    """

    ok: bool
    reason: str = ""
    syntax_error: bool = False
    violations: list[str] = field(default_factory=list)

    @property
    def retryable(self) -> bool:
        return self.syntax_error


def _is_path_allowed(raw_path: str) -> bool:
    """True when ``raw_path`` resolves inside an allowed sandbox root.

    Relative paths are resolved against ``/workspace`` because that is the
    sandbox working directory. ``posixpath`` is used explicitly so the decision
    does not change when the backend itself runs on Windows.
    """
    if not raw_path:
        return False
    # Reject URL-ish targets outright (file://, http://, \\host\share).
    if "://" in raw_path or raw_path.startswith("\\\\"):
        return False

    candidate = raw_path if posixpath.isabs(raw_path) else posixpath.join("/workspace", raw_path)
    normalised = posixpath.normpath(candidate)
    return any(normalised == root or normalised.startswith(root + "/") for root in ALLOWED_PATH_ROOTS)


class CodeGuard:
    """Scans generated Python and decides whether it is safe to execute."""

    @classmethod
    def scan(cls, code: str) -> GuardVerdict:
        if not code or not code.strip():
            return GuardVerdict(ok=False, reason="Code generation produced an empty program.")

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            line = exc.lineno if exc.lineno is not None else "?"
            return GuardVerdict(
                ok=False,
                reason=f"Syntax Error: {exc.msg} on line {line}",
                syntax_error=True,
            )

        violations: list[str] = []
        for node in ast.walk(tree):
            violations.extend(cls._inspect_node(node))

        if violations:
            return GuardVerdict(ok=False, reason=violations[0], violations=violations)
        return GuardVerdict(ok=True, reason="Safe")

    # ------------------------------------------------------------------ #
    @classmethod
    def _inspect_node(cls, node: ast.AST) -> list[str]:
        if isinstance(node, ast.Import):
            return [
                f"Import of restricted module '{alias.name}' is not permitted."
                for alias in node.names
                if alias.name.split(".")[0] in BANNED_MODULES
            ]

        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BANNED_MODULES:
                return [f"Import from restricted module '{node.module}' is not permitted."]
            return []

        if isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRIBUTES:
                return [f"Access to restricted attribute '{node.attr}' is not permitted."]
            return []

        if isinstance(node, ast.Name):
            if node.id in BANNED_NAMES:
                return [f"Reference to '{node.id}' is not permitted."]
            return []

        if isinstance(node, ast.Call):
            return cls._inspect_call(node)

        return []

    @classmethod
    def _inspect_call(cls, node: ast.Call) -> list[str]:
        violations: list[str] = []

        func = node.func
        name = ""
        if isinstance(func, ast.Name):
            name = func.id
            if name in BANNED_CALLS:
                violations.append(f"Use of '{name}()' is not permitted.")
        elif isinstance(func, ast.Attribute):
            name = func.attr
            if name in BANNED_CALLS:
                violations.append(f"Use of '{name}()' is not permitted.")

        # Reflection with a computed attribute name defeats every name-based
        # check above, so only literal attribute names are allowed.
        if name in REFLECTION_CALLS and len(node.args) >= 2:
            attribute = node.args[1]
            if not (isinstance(attribute, ast.Constant) and isinstance(attribute.value, str)):
                violations.append(f"'{name}()' with a computed attribute name is not permitted.")
            elif (
                attribute.value in BANNED_ATTRIBUTES
                or attribute.value in BANNED_CALLS
                # Reaching *any* dunder by reflection is never legitimate
                # analysis code, and enumerating them individually would always
                # lag behind the next interpreter internal someone finds.
                or (attribute.value.startswith("__") and attribute.value.endswith("__"))
            ):
                violations.append(f"'{name}()' cannot be used to reach '{attribute.value}'.")

        # Path arguments: only literal strings can be checked statically. A
        # computed path is allowed through because the container mount, not this
        # scanner, is the real boundary.
        checkable = (isinstance(func, ast.Name) and name in PATH_ARG_FUNCTIONS) or (
            isinstance(func, ast.Attribute) and name in (PATH_ARG_FUNCTIONS | PATH_ARG_METHODS)
        )
        if checkable:
            path_literal = cls._first_string_arg(node)
            if path_literal is not None and not _is_path_allowed(path_literal):
                violations.append(f"File access outside the workspace is not permitted (path: '{path_literal}').")

        return violations

    @staticmethod
    def _first_string_arg(node: ast.Call) -> str | None:
        for arg in node.args:
            if isinstance(arg, ast.Constant):
                return arg.value if isinstance(arg.value, str) else None
            return None
        for kw in node.keywords:
            if kw.arg in {"path_or_buf", "filepath_or_buffer", "fname", "file", "path"} and isinstance(
                kw.value, ast.Constant
            ):
                return kw.value.value if isinstance(kw.value.value, str) else None
        return None

    # ------------------------------------------------------------------ #
    @staticmethod
    def strip_markdown_fences(code: str) -> str:
        """Removes ```python fences an LLM sometimes leaves in the payload."""
        cleaned = code.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        return cleaned.strip()

    #: Aliases small models routinely use without importing.
    COMMON_IMPORTS = {
        "pd": "import pandas as pd",
        "np": "import numpy as np",
        "plt": "import matplotlib.pyplot as plt",
        "sns": "import seaborn as sns",
        "px": "import plotly.express as px",
        "go": "import plotly.graph_objects as go",
    }

    @staticmethod
    def missing_alias_imports(code: str) -> list[str]:
        """Import statements for aliases the code uses but never imports."""
        return [
            statement
            for alias, statement in CodeGuard.COMMON_IMPORTS.items()
            if f"{alias}." in code and f"import {alias}" not in code and f"as {alias}" not in code
        ]

    @staticmethod
    def repair(code: str) -> tuple[bool, str]:
        """Best-effort deterministic repair of generated code.

        Returns ``(parses_cleanly, code)``. Two safe transformations are applied:
        fence stripping, and prepending imports for aliases the code uses but
        never imports.

        Import healing runs unconditionally rather than only after a parse
        failure. A missing import raises ``NameError`` at *runtime* and parses
        perfectly well, so gating the fix on a ``SyntaxError`` — as the original
        implementation did — meant it could never actually fire.
        """
        cleaned = CodeGuard.strip_markdown_fences(code)

        missing = CodeGuard.missing_alias_imports(cleaned)
        candidate = "\n".join(missing) + "\n" + cleaned if missing else cleaned

        try:
            ast.parse(candidate)
            return True, candidate
        except SyntaxError:
            # Prepending imports cannot introduce a syntax error, so the fault is
            # in the generated code itself. Hand back the un-prefixed source so
            # the error the model sees points at its own line numbers.
            return False, cleaned


def is_safe_identifier(name: str) -> bool:
    """Guards values that get interpolated into generated source (e.g. variable export)."""
    return bool(name) and name.isidentifier() and not name.startswith("__") and len(name) <= 128
