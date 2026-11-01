"""Design capacity, peak use and share of the equipment of a small plant."""

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from tests.fixtures.cases import make_case
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.result_tables import make_results


def boiler_plant():
    """Return a plant with a boiler of 10 kW and a pipe of 120 m, and a heat consumer."""
    plant = heating_plant(costed=False)
    plant.add("Boiler", name="boiler", params={"capacity": {"value": 10, "unit": "kW"}})
    plant.add("Pipe", name="pipe", params={"length": {"value": 120, "unit": "m"}})
    return plant


def boiler_run(duty=(1e3, 4e3, 2e3)):
    """Return a run whose boiler heats its water by ``duty`` [W] in each step."""
    return make_results(
        {
            "boiler": {
                "fluid_in.enthalpy_flow": [1e6] * len(duty),
                "fluid_out.enthalpy_flow": [1e6 + item for item in duty],
            }
        }
    )


def test_the_capacity_the_peak_and_the_share_of_a_boiler():
    """Rated 10 kW, it gave at most 4 kW: a share of 0.4."""
    found = gm.evaluate.capacities(boiler_plant(), make_case(count=3), boiler_run([1e3, 4e3, 2e3]))
    assert to_plain(found["boiler"]) == {
        "kind": "boiler",
        "capacity": {"value": 1e4, "unit": "W"},
        "peak": {"value": 4e3, "unit": "W"},
        "share": {"value": pytest.approx(0.4), "unit": "-"},
    }


def test_a_module_whose_use_the_run_does_not_show_has_a_capacity_only():
    """The pipe has a length; no peak is read from the run."""
    found = gm.evaluate.capacities(boiler_plant(), make_case(count=3), boiler_run([1.0] * 3))
    pipe = found["pipe"]
    assert pipe["capacity"].value == 120.0 and pipe["capacity"].unit == "m"
    assert pipe["peak"].value is None and pipe["share"].value is None
    assert pipe["peak"].reason == "the run shows no use of this module"


def test_the_grids_and_a_fixed_item_are_not_listed():
    """A consumer is not equipment, and a degasser has no capacity."""
    plant = heating_plant()
    found = gm.evaluate.capacities(plant, make_case(count=3), boiler_run([1.0] * 3))
    assert found == {}


def test_a_heat_pump_is_read_on_the_side_its_mode_makes_useful():
    """A heat pump in heating mode gives its sink circuit heat."""
    plant = gm.Plant("One")
    plant.add(
        "HeatPump", name="pump", params={"mode": "heating", "capacity": {"value": 5, "unit": "kW"}}
    )
    run = make_results(
        {
            "pump": {
                "sink_in.enthalpy_flow": [1e6, 1e6],
                "sink_out.enthalpy_flow": [1e6 + 2e3, 1e6 + 3e3],
            }
        }
    )
    found = gm.evaluate.capacities(plant, make_case(count=2), run)["pump"]
    assert found["kind"] == "heat_pump" and found["share"].value == pytest.approx(0.6)
