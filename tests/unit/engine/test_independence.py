"""The run needs no compiler: nothing but the compiler imports it, and a run works without it."""

import ast
import subprocess
import sys

import pytest

from tests.fixtures import ROOT

PACKAGES = (
    "modules",
    "plants",
    "physics",
    "ops",
    "runtime",
    "engine",
    "run",
    "types",
    "units",
    "errors",
    "_utils",
)
"""The folders of ``gemini/`` that must not import ``gemini.compiler``."""

SCRIPT = """
import importlib.abc
import sys

import pytest
import types

import numpy as np
import pandas as pd

package = types.ModuleType("gemini")
package.__path__ = [sys.argv[1]]
sys.modules["gemini"] = package


class Blocked(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "gemini.compiler" or name.startswith("gemini.compiler."):
            raise ImportError(f"{name} is blocked")


sys.meta_path.insert(0, Blocked())
try:
    import gemini.compiler
except ImportError:
    pass
else:
    raise SystemExit("the compiler was importable")

from gemini import modules, plants, run
from gemini.engine import engine as engine_module
from gemini.modules.declarations import Control, Output
from gemini.types.bindings import Binding, ModuleBindings


class Gain(modules.Module):
    def __init__(self):
        super().__init__()
        self.level = Control(float)
        self.double = Output(float)

    def forward(self, inlets):
        self.double = 2.0 * self.level
        return {}


plant = Gain()
plant.bindings = {"": ModuleBindings(controls={"level": Binding(column="level", unit="-")})}
index = pd.date_range("2024-01-01", periods=3, freq="15min", tz="UTC")
frame = pd.DataFrame({"level": [1.0, 2.0, 3.0]}, index=index)
engine = engine_module.Engine(plant)
results = engine.simulate(frame)
print(type(engine._executor).__name__, results.to_frame()["double"].tolist())
"""


def _imports(path):
    """Return the module names a file imports, at any depth, relative ones as written."""
    text = path.read_text()
    names = []
    if "compiler" not in text:
        return names
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            names += [base] + [f"{base}.{alias.name}" for alias in node.names]
    return names


def _compiler_imports(names):
    return [
        name
        for name in names
        if name.lstrip(".").startswith(("compiler", "gemini.compiler"))
        or name.endswith(".compiler")
    ]


def test_no_run_package_imports_the_compiler():
    """Not at the top of a file and not inside a function."""
    found = {
        str(path.relative_to(ROOT)): _compiler_imports(_imports(path))
        for package in PACKAGES
        for path in (ROOT / "gemini" / package).rglob("*.py")
    }
    assert {path: names for path, names in found.items() if names} == {}


def test_the_scan_finds_a_compiler_import(tmp_path):
    """The scan reads imports of every form."""
    source = tmp_path / "late.py"
    source.write_text(
        "from gemini.compiler.graph import evaluate\n"
        "def f():\n    from gemini import compiler\n    import gemini.compiler\n"
    )
    assert _compiler_imports(_imports(source)) == [
        "gemini.compiler.graph",
        "gemini.compiler.graph.evaluate",
        "gemini.compiler",
        "gemini.compiler",
    ]


@pytest.mark.slow
def test_a_plant_runs_with_the_compiler_blocked():
    """The run packages simulate a plant eagerly while ``gemini.compiler`` cannot load.

    Slow: the property needs a fresh interpreter that imports gemini (about 1.5 s of child CPU,
    which the budget counts), so it runs in the release profile.
    """
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(ROOT / "gemini")],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT)},
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["EagerExecutor", "[2.0,", "4.0,", "6.0]"]
