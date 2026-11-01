"""A plant says what it still needs: each missing path with its quantity, units and meaning."""

import json

import pytest

import gemini as gm
from tests.fixtures.errors import raises


def test_a_bare_plant_lists_every_missing_path_with_a_description():
    """``missing_parameters`` is JSON and every entry says what the value means."""
    plant = gm.plants.HeatingPlant()
    missing = plant.missing_parameters()
    paths = [item["path"] for item in missing]
    assert {"d0.esp.stage_count", "peak_boiler.capacity", "heat_exchanger.thermal_conductance"} <= (
        set(paths)
    )
    assert all(item["description"] for item in missing)
    assert json.loads(json.dumps(missing)) == missing
    stages = missing[paths.index("d0.esp.stage_count")]
    assert stages["quantity"] == "count" and stages["minimum"] == 0
    capacity = missing[paths.index("peak_boiler.capacity")]
    assert capacity["unit"] == "W" and "kW" in capacity["units"] and capacity["minimum"] == 0
    assert all(isinstance(unit, str) for item in missing for unit in item["units"])


def test_a_missing_value_error_lists_every_path_at_once():
    """Reading one unset value names all of them, each with its meaning."""
    plant = gm.plants.HeatingPlant()
    paths = [item["path"] for item in plant.missing_parameters()]
    with pytest.raises(gm.errors.ValidationError) as caught:
        plant.d0.esp.power_function(0.01, 50)
    error = caught.value
    assert error.code == "missing_value"
    assert [item["path"] for item in error.problems] == paths
    assert "Number of stages of the pump" in str(error)


def test_a_set_value_leaves_the_list():
    """A parameter that has a value is no longer missing."""
    plant = gm.plants.Doublet()
    plant.esp.stage_count = 10
    assert "esp.stage_count" not in [item["path"] for item in plant.missing_parameters()]
    with raises(gm.errors.ValidationError, "missing_value", match="uninitialized"):
        plant.esp.power_function(0.01, 50)


REMOVED_DEFAULTS = {
    "degasser.nominal_pressure_drop": "Pressure drop across the vessel at the nominal flow",
    "degasser.separation_efficiency": (
        "Share of the inlet free gas that leaves through the gas outlet"
    ),
    "filters.hot.nominal_mass_flow": "Mass flow at which the clean-filter pressure drop holds",
    "heat_exchanger.arrangement": "Flow arrangement of the two streams",
    "heating_return_pipe.roughness": "Absolute roughness of the inner pipe wall",
    "gas_grid.composition": "Mole or mass fractions of the gas components by name",
    "flare.combustion_efficiency": "Share of the flared gas burned completely",
    "d0.drainage_radius": "Radius of the drainage area around each well",
    "d0.well.heat_transfer_coefficient": (
        "Overall heat transfer coefficient from the fluid to the soil"
    ),
    "d0.reservoir.skin": "Dimensionless skin factor of the near-well zone",
}


def test_a_value_the_modules_no_longer_default_is_missing_with_its_description():
    """A design value left out is listed and named in the error, never filled in silently."""
    plant = gm.plants.HeatingPlant()
    described = {item["path"]: item["description"] for item in plant.missing_parameters()}
    for path, description in REMOVED_DEFAULTS.items():
        assert described[path] == description
    with raises(gm.errors.ValidationError, "missing_value") as caught:
        plant.degasser.nominal_pressure_drop
    named = {item["path"] for item in caught.value.problems}
    assert set(REMOVED_DEFAULTS) <= named


def test_a_switch_is_empty_and_means_off_until_it_is_set():
    """A threshold has no value, not a number: no alarm, and no missing parameter."""
    plant = gm.plants.HeatingPlant()
    paths = {item["path"] for item in plant.missing_parameters()}
    assert plant.heat_exchanger.fouling_threshold is None
    assert plant.filters.hot.clogging_pressure_drop is None
    assert plant.d0.reservoir.decline_threshold is None
    assert not {"heat_exchanger.fouling_threshold", "d0.reservoir.decline_threshold"} & paths


def test_the_start_of_a_design_state_is_a_parameter_that_can_be_missing():
    """A tank starts at the temperature its plant states; without it a run raises."""
    tank = gm.modules.ThermalStorage()
    with raises(gm.errors.ValidationError, "missing_value", match="initial_temperature"):
        tank.initial_state()
    tank.set_params("", {"initial_temperature": 300.0})
    assert tank.initial_state() == {"temperature": 300.0}
