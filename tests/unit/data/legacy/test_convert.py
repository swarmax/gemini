"""Conversion between a parsed old project and the new plant, dataset and results objects."""

import shutil

import pytest

import gemini as gm
from gemini.data import legacy
from gemini.errors import ValidationError
from tests.fixtures import OLD_PROJECT
from tests.fixtures.errors import raises


@pytest.fixture(scope="module")
def project():
    """Parse the example old project once; tests copy it before editing."""
    return legacy.GeminiProject.from_folder(OLD_PROJECT)


@pytest.fixture(scope="module")
def converted(project):
    """Convert the example project once into a plant that tests must not mutate."""
    return legacy.to_plant(project, gm.plants.get("DoubletHeatPlant"))


def _node_id(project, kind):
    return next(node_id for node_id, node in project.nodes.items() if node.type == kind)


def _node_id_named(project, name):
    return next(node_id for node_id, node in project.nodes.items() if node.name == name)


def test_to_plant_uses_the_in_memory_project(project):
    """Edits to a parsed project reach the plant instead of a re-read of its folder."""
    edited = project.model_copy(deep=True)
    edited.params[_node_id(edited, "heat_exchanger")]["heat_transfer_coeff"].values = [1.0]
    plant = legacy.to_plant(edited, gm.plants.get("DoubletHeatPlant"))
    assert plant.heat_exchanger.thermal_conductance == 1.0
    assert plant.heat_exchanger._param_history[-1].params["thermal_conductance"] == 1.0


def test_to_plant_fills_parameters_bindings_and_boundary(converted):
    """The converted plant carries SI values, dated histories, bindings and assumptions."""
    assert converted.doublet.reservoir.pressure == 220e5
    assert converted.doublet.esp.minimum_flow == pytest.approx(82 / 3600)
    assert converted.doublet.well.segment == "below_esp"
    assert converted.doublet.riser.segment == "above_esp"
    assert converted.injection_pump.efficiency == 0.8
    assert str(converted.heat_exchanger._param_history[0].valid_from) == "2020-01-01 00:00:00+00:00"
    assert converted.bindings["doublet.reservoir"].controls["production_rate"].column == (
        "doublet.reservoir.production_rate"
    )
    assert converted.bindings[""].inlets["return_in"]["T"].unit == "K"
    assert converted.input_value("return_in.m_dot") == 40
    assert converted.fluid.density == 1068
    assert not hasattr(converted, "legacy_info")


def test_to_plant_rejects_an_ambiguous_data_csv(tmp_path):
    """A second data CSV raises instead of silently dropping every dataset supplement."""
    folder = tmp_path / "old"
    shutil.copytree(OLD_PROJECT, folder)
    (folder / "extra.csv").write_text("Timestamp;x\n", encoding="utf-8")
    with raises(ValidationError, "invalid_format", match="exactly one"):
        legacy.to_plant(legacy.GeminiProject.from_folder(folder), gm.plants.get("DoubletHeatPlant"))


def test_to_dataset_converts_and_reports_missing_columns(project):
    """Old columns are renamed and converted to SI; absent bound columns are listed."""
    frame = legacy.from_csv(OLD_PROJECT / "doublet_2024_old.csv").head(2)
    data = legacy.to_dataset(project, frame)
    values = data.to_frame()
    assert values["doublet.esp.suction.p"].iloc[0] == pytest.approx(59.491e5)
    assert values["doublet.reservoir.production_rate"].iloc[0] == pytest.approx(149.191 / 3600)
    assert data.columns["heat_exchanger.hot_out_T"].unit == "K"
    assert values["production_wellhead_pressure"].iloc[0] == pytest.approx(10e5)
    assert values["esp_status"].iloc[0] == "Normal"
    with raises(ValidationError, "invalid_format", match="ESP_freq"):
        legacy.to_dataset(project, frame.drop(columns=["ESP_freq"]))


def test_to_frame_uses_old_columns_and_units(project, converted, fast_dataset):
    """Predicted measured outputs return as old tag columns in old units."""
    plant = legacy.to_plant(project, gm.plants.get("DoubletHeatPlant"))
    results = gm.replay(plant, fast_dataset.window(end=fast_dataset.start))
    frame = legacy.to_frame(results, project)
    assert list(frame.columns[:2]) == ["Timestamp", "ESP_Head"]
    predicted = results.to_frame()["doublet.esp.head"].iloc[0]
    assert frame["ESP_Head"].iloc[0] == pytest.approx(predicted / 1e5)
    assert frame["Timestamp"].dt.tz is None


def test_from_plant_writes_changed_values_and_keeps_the_rest(project):
    """Changed parameters are exported in old units; unchanged raw values are kept."""
    plant = legacy.to_plant(project, gm.plants.get("DoubletHeatPlant"))
    plant.doublet.reservoir.pressure = 2.3e7
    exported = legacy.from_plant(plant, project)
    production = _node_id_named(project, "reservoir_c1b5")
    assert exported.params[production]["reservoir_pressure"].values == [230.0]
    assert exported.params[production]["reservoir_temperature"].values == [80]
    esp = _node_id(project, "esp")
    assert exported.params[esp] == project.params[esp]


def test_check_wiring_leaves_the_plant_unchanged(project):
    """Tracing runs on a copy: the caller's controls and call results stay untouched."""
    plant = legacy.to_plant(project, gm.plants.get("DoubletHeatPlant"))
    assert "frequency" not in plant.doublet.esp._input_values
    assert legacy.check_wiring(plant, project) == []
    assert "frequency" not in plant.doublet.esp._input_values
    assert getattr(plant, "last_result", None) is None


def test_check_wiring_reports_mismatches_and_raises_on_errors(project, converted):
    """Diagram differences are reported; a plant that cannot be traced raises."""
    edited = project.model_copy(deep=True)
    edited.links = edited.links[1:]
    errors = legacy.check_wiring(converted, edited)
    assert len(errors) == 1 and errors[0].startswith("Unexpected connection")
    with raises(ValidationError, "invalid_format", match="plant inlet stream"):
        legacy.check_wiring(gm.plants.get("DoubletHeatPlant"), project)


def test_round_trip_through_from_plant_converts_the_edited_project(project):
    """A project exported by from_plant converts from memory, not from its source folder."""
    plant = legacy.to_plant(project, gm.plants.get("DoubletHeatPlant"))
    plant.heat_exchanger.thermal_conductance = 123456.0
    reconverted = legacy.to_plant(
        legacy.from_plant(plant, project), gm.plants.get("DoubletHeatPlant")
    )
    assert reconverted.heat_exchanger.thermal_conductance == 123456.0
    assert reconverted.state_dict() == plant.state_dict()
