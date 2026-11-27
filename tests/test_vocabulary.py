"""UI text follows GLOSSARY.md: no string the user can see uses a term listed under _Avoid_.

Cheap check: scans the string literals of the UI modules (docstrings excluded).
A literal counts as UI text when it has a space or starts with a capital letter,
which skips dict keys such as "pattern".
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI_MODULES = ["desktop_app.py", "check_columns.py", "money_flow_chart.py"]

# Glossary _Avoid_ terms. "Other"/"Uncategorized" are left out: each is a real
# term that the glossary only forbids in the other's meaning.
_AVOID_LINES = re.findall(r"^_Avoid_:\s*(.+)$", (ROOT / "GLOSSARY.md").read_text(encoding="utf-8"), re.M)
AVOID = sorted(
    {
        term.split("(")[0].strip()
        for line in _AVOID_LINES
        for term in line.split(",")
        if term.split("(")[0].strip() not in {"Other", "Uncategorized"}
    }
)


def _ui_strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        # Plotly placeholders such as %{source.label} are code, not text.
        (node.lineno, re.sub(r"%\{[^}]*\}", "", node.value))
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and (" " in node.value or node.value[:1].isupper())
    ]


def test_the_glossary_lists_avoid_terms():
    assert {"Inflow", "Outflow", "Net", "Label", "Plot", "Pattern", "assignment", "Settings"} <= set(AVOID)


@pytest.mark.parametrize("module", UI_MODULES)
def test_ui_text_uses_no_avoided_terms(module):
    found = [
        f"{module}:{line}: {term!r} in {text!r}"
        for line, text in _ui_strings(ROOT / "src" / "finsight" / module)
        for term in AVOID
        if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE)
    ]
    assert found == []
