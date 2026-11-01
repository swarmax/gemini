"""The inputs of a plant: set by path, stored in both dict forms, read by the schedule."""

import pytest

import gemini as gm
from gemini.errors import ValidationError
from gemini.plants._utils.schema import schema
from tests.fixtures.errors import raises
from tests.fixtures.heating_cooling import days_case
from tests.fixtures.json_schema import check as check_schema

SETPOINT = {"pump_heater.temperature_setpoint": {"value": 100, "unit": "degC"}}


def boiler_plant():
    """Return a small plant with a setpoint: a return port, a boiler and its heat users."""
    plant = gm.Plant("Heater")
    plant.add("GasGrid", name="grid")
    plant.add(
        "Boiler",
        name="pump_heater",
        params={"capacity": {"value": 2, "unit": "MW"}, "efficiency": 0.9},
    )
    plant.add(
        "HeatingGrid",
        name="users",
        params={
            "return_pressure": {"value": 6, "unit": "bar"},
        },
    )
    plant.connect("grid.gas_out", "pump_heater.fuel_in")
    plant.connect("users.return_out", "pump_heater.fluid_in")
    plant.connect("pump_heater.fluid_out", "users.supply_in")
    plant.connect("pump_heater.flue_out", "flue")
    plant.connect("pump_heater.loss_out", "loss")
    plant.users.fluid = gm.WATER
    return plant


def test_set_inputs_validates_and_persists_a_setpoint():
    """A unit string reaches the module in SI, and ``input_value`` reads it through the plant."""
    plant = boiler_plant().set_inputs(SETPOINT)
    assert plant.pump_heater.temperature_setpoint == pytest.approx(373.15)
    assert plant.input_value("pump_heater.temperature_setpoint") == pytest.approx(373.15)


def test_an_input_without_a_value_reads_none():
    """A declared input nobody set has no value, and a set one on the module is read too."""
    plant = boiler_plant()
    assert plant.input_value("pump_heater.temperature_setpoint") is None
    plant.pump_heater.temperature_setpoint = 350.0
    assert plant.input_value("pump_heater.temperature_setpoint") == 350.0


@pytest.mark.parametrize("structure", [False, True])
def test_inputs_round_trip_in_both_dict_forms(structure):
    """The stated value stays as written, and ``from_dict`` applies it."""
    plant = gm.plants.get("HeatingPlant")
    path = "peak_boiler.temperature_setpoint"
    plant.set_inputs({path: {"value": 100, "unit": "degC"}})
    data = plant.to_dict(structure=structure)
    assert data["inputs"] == {path: {"value": 100, "unit": "degC"}}
    built = gm.Plant.from_dict(data)
    assert built.get_submodule("peak_boiler").temperature_setpoint == pytest.approx(373.15)
    assert built.to_dict(structure=structure) == data


def test_a_plant_without_inputs_has_no_key():
    """Stored plants that set nothing keep the dict they had."""
    assert "inputs" not in gm.plants.get("HeatingPlant").to_dict()


def test_a_run_does_not_become_a_stored_input():
    """A value only the engine persisted is the last tick of a run, not part of the design."""
    plant = boiler_plant()
    plant._set_inputs({"pump_heater.temperature_setpoint": 350.0})
    assert "inputs" not in plant.to_dict()


def test_a_plant_inlet_field_is_an_input():
    """``port.field`` holds what ``root_inputs`` held: it feeds the root stream of a run."""
    plant = gm.plants.get("Doublet")
    plant.set_inputs(
        {
            "return_in.T": {"value": 40, "unit": "degC"},
            "return_in.m_dot": 30,
            "return_in.p": {"value": 20, "unit": "bar"},
        }
    )
    assert plant._root_inputs() == {"return_in": {"T": 313.15, "m_dot": 30.0, "p": 20e5}}
    assert plant.input_value("return_in.T") == pytest.approx(313.15)


def test_from_dict_then_schedule_needs_no_extra_call():
    """A stored design with a setpoint schedules and runs as it is read."""
    plant = boiler_plant().set_inputs(SETPOINT)
    built = gm.Plant.from_dict(plant.to_dict())
    case = days_case([1e5, 2e5], start="2027-01-01")
    plan = gm.schedule(built, case)
    assert plan["pump_heater.temperature_setpoint"].iloc[0] == pytest.approx(373.15)
    results = gm.simulate(built, case, plan=plan)
    assert results.get("pump_heater", "fluid_out.temperature")["value"][0] == pytest.approx(373.15)


def test_a_bad_path_gives_unknown_name_with_suggestions():
    """``from_dict`` says where the path is in the dict and what was meant."""
    data = boiler_plant().to_dict()
    data["inputs"] = {"pump_heater.temperature_setpoin": {"value": 100, "unit": "degC"}}
    with raises(ValidationError, "unknown_name") as caught:
        gm.Plant.from_dict(data)
    found = caught.value.problems[0]
    assert found["path"] == "inputs.pump_heater.temperature_setpoin"
    assert found["suggestions"] == ["pump_heater.temperature_setpoint"]


@pytest.mark.parametrize(
    ("inputs", "code"),
    [
        ({"pump_heater.temperature_setpoint": {"value": 100, "unit": "bar"}}, "invalid_unit"),
        ({"pump_heater.capacity": {"value": 1, "unit": "MW"}}, "unknown_name"),
        ({"nothing.T": 300}, "unknown_name"),
    ],
    ids=["wrong unit", "a parameter", "no such port"],
)
def test_validate_reports_what_does_not_fit(inputs, code):
    """A wrong unit, a path that is no input and an unknown one are problems on the dict."""
    data = boiler_plant().to_dict() | {"inputs": inputs}
    found = gm.plants.validate(data, on_error="record")
    assert [item["code"] for item in found if item["path"].startswith("inputs.")] == [code]


def test_a_parameter_path_says_so():
    """The message of a parameter path names the call that sets it."""
    with raises(ValidationError, "unknown_name", match="set_params"):
        boiler_plant().set_inputs({"pump_heater.capacity": {"value": 1, "unit": "MW"}})


def test_set_inputs_changes_nothing_when_one_path_fails():
    """All or nothing: a bad path keeps the values of the others off the plant."""
    plant = boiler_plant()
    with pytest.raises(ValidationError):
        plant.set_inputs(SETPOINT | {"wrong.path": 1})
    assert plant.input_value("pump_heater.temperature_setpoint") is None


def test_the_schema_knows_the_key():
    """Both forms of the plant dict take ``inputs`` in the schema."""
    document = gm.plants.get("HeatingPlant").set_inputs(
        {"peak_boiler.temperature_setpoint": {"value": 100, "unit": "degC"}}
    )
    for structure in (False, True):
        assert check_schema(document.to_dict(structure=structure), schema(), schema()) == []


def test_a_unit_string_is_refused_as_an_input_and_as_a_parameter():
    """Values are numbers in SI or quantities; text with a unit is no value."""
    plant = gm.plants.Doublet()
    with raises(gm.errors.ValidationError, "invalid_value"):
        plant.set_inputs({"esp.frequency": "50 Hz"})
    with raises(gm.errors.ValidationError, "invalid_value"):
        plant.set_params("", {"nominal_flow": "100 m3/h"})
