"""End-to-end old/new bridge round trips."""

import pytest

import gemini as gm
from gemini._utils import paths
from gemini.data import legacy
from tests.fixtures import OLD_PROJECT as OLD

pytestmark = pytest.mark.e2e


def test_legacy_bridge(tmp_path):
    """Convert old assets, replay, write old outputs and preserve raw project values."""
    project = legacy.GeminiProject.from_folder(OLD)
    plant = legacy.to_plant(project, gm.plants.get("DoubletHeatPlant"))
    data = legacy.to_dataset(project, legacy.from_csv(OLD / "doublet_2024_old.csv"))
    assert legacy.check_wiring(plant, project) == []
    plant.to_json(tmp_path / "plant.json")
    frame = data.to_frame()
    frame.index.name = "time"
    frame.reset_index().to_csv(
        tmp_path / "doublet_2024_15min.csv", index=False, float_format="%.17g"
    )
    gm.plants.example("DoubletHeatPlant").to_json(tmp_path / "example.json")
    assert (tmp_path / "plant.json").read_bytes() == (tmp_path / "example.json").read_bytes()
    assert (tmp_path / "doublet_2024_15min.csv").read_bytes() == (
        paths.doublet_heat("doublet_2024_15min.csv")
    ).read_bytes()
    results = gm.replay(plant, data.window(end=data.start))
    old_results = legacy.to_frame(results, project)
    legacy.to_csv(old_results, tmp_path / "results.csv")
    assert len(legacy.from_csv(tmp_path / "results.csv")) == 1
    converted = legacy.from_plant(plant, project)
    converted.to_folder(tmp_path / "project")
    reread = legacy.GeminiProject.from_folder(tmp_path / "project")
    assert reread.params == project.params
    plant.heat_exchanger.thermal_conductance = 123456.0
    updated = legacy.from_plant(plant, project)
    updated.to_folder(tmp_path / "updated")
    reread = legacy.GeminiProject.from_folder(tmp_path / "updated")
    hx_id = next(
        node_id for node_id, node in project.nodes.items() if node.type == "heat_exchanger"
    )
    assert reread.params[hx_id]["heat_transfer_coeff"].values == [123456.0]
