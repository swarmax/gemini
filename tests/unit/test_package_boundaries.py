"""``gemini._utils`` and ``gemini.errors`` are leaf packages that import nothing else from GEMINI.

Two files of ``gemini/_utils`` may import ``gemini.errors``, itself a leaf: ``paths.py``, because a
missing ``inputs/`` folder raises ``inputs_missing``, and ``registry.py``, which refuses a name.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
RAISES_ERRORS = ("paths.py", "registry.py")
"""The topic files that raise a ``gm.errors`` class: they may import ``gemini.errors``."""


def imported_modules(path):
    """Return the absolute module names one file imports."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module)
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
    return names


@pytest.mark.parametrize("package", ["_utils", "errors"])
def test_leaf_package_imports_only_itself(package):
    """Every import is the standard library, a dependency, or the package itself."""
    offending = {}
    for path in sorted((ROOT / "gemini" / package).rglob("*.py")):
        names = imported_modules(path) - (
            {"gemini.errors"} if path.name in RAISES_ERRORS else set()
        )
        bad = {
            name
            for name in names
            if name.startswith(".")
            or (name.split(".")[0] == "gemini" and not name.startswith(f"gemini.{package}"))
        }
        if bad:
            offending[path.name] = sorted(bad)
    assert offending == {}


def test_a_dataset_knows_no_modules_or_engine():
    """``gemini/run/dataset.py`` is in-memory data, with nothing of a run."""
    names = imported_modules(ROOT / "gemini/run/dataset.py")
    assert [name for name in names if name.startswith(("gemini.modules", "gemini.engine"))] == []
