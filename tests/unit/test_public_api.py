"""Curated user API and plant ownership contracts."""

import inspect
import json
import tomllib
from pathlib import Path

import gemini as gm
from tests.fixtures.capture_public_api import SNAPSHOT, capture, fingerprint

SNAPSHOTS = {
    "0.1.0": "f19ae90f18bb5a5a85e1b1f730276c9a50fdba0d46108c4bcd56488b48178a8b",
    "0.2.0": "c6fa73afe75606e51ef711040413b35894a4fa9b066bf936aea6798963fd1cb1",
}
"""Hash of the snapshot per ``gm.__version__``: a released entry never changes."""


EXPECTED = {
    "Module",
    "Plant",
    "Parameter",
    "Inlet",
    "Outlet",
    "Output",
    "Stream",
    "Fluid",
    "BRINE",
    "WATER",
    "Case",
    "Problem",
    "Constraint",
    "Assumptions",
    "schedule",
    "simulate",
    "replay",
    "live",
    "resume",
    "call",
    "Results",
    "Dataset",
    "Engine",
    "modules",
    "plants",
    "case",
    "physics",
    "ops",
    "runtime",
    "units",
    "errors",
    "data",
    "study",
    "evaluate",
    "analysis",
    "compiler",
}
"""The names of the top level, exactly."""


def test_public_names_and_docs():
    """Interactive completion exposes exactly the documented, individually documented names."""
    assert set(dir(gm)) == EXPECTED == set(gm.__all__)
    assert all(getattr(gm, name).__doc__ for name in EXPECTED)
    assert all(getattr(gm.modules, name).__doc__ for name in gm.modules.__all__)
    assert "Doublet" in gm.plants.names()


def test_readable_tree():
    """Printing a loaded plant displays nested equipment and scalar human-unit parameters."""
    plant = gm.plants.example("DoubletHeatPlant")
    with gm.runtime.settings(display_units="field"):
        rendered = repr(plant)
    assert "DoubletHeatPlant(" in rendered and "(doublet): Doublet(" in rendered
    assert "ESP(" in rendered and "bar" in rendered and "°C" in rendered


def test_version_matches_the_package_metadata():
    """The version literal in ``gemini/__init__.py`` is the one in ``pyproject.toml``."""
    project = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    assert gm.__version__ == project["project"]["version"]


def test_the_public_api_equals_the_stored_snapshot():
    """Every name, its parameter names and the schema files are as frozen."""
    assert capture() == json.loads(SNAPSHOT.read_text())


def test_the_snapshot_changes_only_with_the_version():
    """A stored snapshot belongs to one version; changing it means raising the version."""
    stored = json.loads(SNAPSHOT.read_text())
    assert stored["version"] == gm.__version__
    assert fingerprint(stored) == SNAPSHOTS[gm.__version__]


def test_the_change_log_lists_the_version():
    """Each version has a line in the change log of the API page."""
    page = (Path(__file__).parents[2] / ".claude/docs/api.md").read_text()
    assert f"| {gm.__version__} |" in page.split("## Change log")[1]


def test_the_package_has_one_version():
    """``gm.API_VERSION`` is gone; ``gm.__version__`` is the one version."""
    assert not hasattr(gm, "API_VERSION")
    assert gm.__version__ == "0.2.0"


def test_every_economics_function_takes_the_plant_the_problem_and_the_results():
    """``capex`` alone has no results; every function starts with the plant and the problem."""
    for name in ("opex", "lcoh", "lcoc", "lcts", "annualised_cost", "co2", "npv", "payback"):
        arguments = list(inspect.signature(getattr(gm.evaluate, name)).parameters)
        assert arguments[:3] == ["plant", "problem", "results"], name
    assert list(inspect.signature(gm.evaluate.capex).parameters)[:2] == ["plant", "problem"]


def test_call_stays_beside_the_run_functions():
    """A call at one point is a run at one point; ``gm.modules.check`` is for developers."""
    assert "call" in gm.__all__ and "check" in gm.modules.__all__


def test_utils_stays_private():
    """Helpers are not part of the public API."""
    assert "_utils" not in gm.__all__


def test_the_old_project_import_is_public_only_through_from_legacy():
    """``gm.legacy`` is gone; ``gm.Plant.from_legacy`` is the one public entry."""
    assert not hasattr(gm, "legacy") and callable(gm.Plant.from_legacy)
