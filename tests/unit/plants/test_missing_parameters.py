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
