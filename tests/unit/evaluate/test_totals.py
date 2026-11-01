"""The totals and the plant KPIs, against hand-computed energies."""

import json
import math

import pandas as pd
import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.evaluate._utils.flows import Flows
from gemini.evaluate.totals import KPI_NAMES
from tests.fixtures.result_tables import cold_ports, heat_ports, make_results


@pytest.fixture(scope="module")
def plant():
    """Return a plant with one heat and one cooling consumer."""
    plant = gm.Plant("Demo")
    plant.add("HeatingGrid", "heat")
    plant.add("CoolingGrid", "cool")
    plant.add("ElectricityGrid", "grid")
    return plant


@pytest.fixture(scope="module")
def results():
    """Return three hourly ticks: heat 300 of 500 Wh demanded, cold 60 of 80, 150 Wh electricity."""
    return make_results(
        {
            "heat": heat_ports([100, 200, 0]) | {"unmet_demand": [0, 100, 100]},
            "cool": cold_ports([10, 20, 30])
            | {"unmet_sensible": [0, 0, 10], "unmet_latent": [0, 0, 10]},
            "grid": {"power_out": [50, 50, 50]},
        }
    )


def test_names_are_fixed():
    """The five required names come in the documented order."""
    assert KPI_NAMES == ("heating_coverage", "cooling_coverage", "cop", "peak_heat", "peak_cold")


def test_values_equal_the_hand_computed_ratios(plant, results):
    """Heating 300/500, cooling 60/80, COP 300/150 and the two peaks."""
    kpis = gm.evaluate.totals(plant, None, results)
    assert to_plain(kpis["heating_coverage"]) == {"value": 0.6, "unit": "-"}
    assert kpis["cooling_coverage"].value == 0.75
    assert kpis["cop"].value == 2.0
    assert to_plain(kpis["peak_heat"]) == {"value": 200.0, "unit": "W"}
    assert kpis["peak_cold"].value == 30.0


def test_a_plant_without_consumers_gives_none_with_a_reason(fresh_plant, fast_dataset):
    """The doublet heat plant has no consumer leaf: every KPI is null and says why."""
    window = fast_dataset.window(None, "2024-07-01T01:00:00Z")
    replay = gm.replay(fresh_plant, window)
    kpis = gm.evaluate.totals(fresh_plant, None, replay)
    assert all(kpis[name].value is None and kpis[name].reason for name in KPI_NAMES)
    json.dumps(to_plain(kpis), allow_nan=False)


def test_zero_demand_and_zero_electricity_have_reasons(plant):
    """A run with nothing demanded or consumed does not divide by zero."""
    idle = make_results(
        {
            "heat": heat_ports([0.0, 0.0]) | {"unmet_demand": [0.0, 0.0]},
            "grid": {"power_out": [0.0, 0.0]},
        }
    )
    kpis = gm.evaluate.totals(plant, None, idle)
    assert kpis["heating_coverage"].reason == "the demand is zero over the window"
    assert kpis["cop"].reason == "no electricity is consumed over the window"
    assert kpis["cooling_coverage"].reason == "the plant has no CoolingGrid"


def test_skipped_ticks_leave_the_ratios_alone(plant):
    """A tick with no value adds to neither the delivered nor the demanded energy."""
    gap = make_results(
        {
            "heat": heat_ports([100, math.nan]) | {"unmet_demand": [100, math.nan]},
            "grid": {"power_out": [50, 50]},
        }
    )
    assert gm.evaluate.totals(plant, None, gap)["heating_coverage"].value == 0.5


def test_totals_integrate_the_ports_of_the_edge_modules(plant, results):
    """Each total is the hand sum of one edge column; a module the plant lacks says so."""
    totals = gm.evaluate.totals(plant, None, results)
    assert to_plain(totals["heat_delivered"]) == {"value": 300 * 3600.0, "unit": "J"}
    assert totals["cold_delivered"].value == 60 * 3600.0
    assert totals["gas_bought"].value is None and totals["gas_bought"].reason
    json.dumps(to_plain(totals), allow_nan=False)


def test_totals_of_a_run_with_every_edge_module():
    """Bought, sold, released, wasted and lost come from their own module."""
    plant = gm.Plant("Edges")
    for module, name in (
        ("ElectricityGrid", "grid"),
        ("GasGrid", "gas"),
        ("Atmosphere", "air"),
        ("WasteGrid", "waste"),
        ("ChemicalGrid", "chemicals"),
    ):
        plant.add(module, name)
    run = make_results(
        {
            "grid": {"net_import": [10.0], "net_export": [1.0]},
            "gas": {"gas_out.chemical_flow": [20.0]},
            "air": {"co2_emission": [2.0], "methane_emission": [0.5], "heat_in": [7.0]},
            "waste": {"waste_in.mass_flow": [3.0]},
            "chemicals": {"chemical_out.mass_flow": [4.0]},
        }
    )
    totals = {name: item.value for name, item in gm.evaluate.totals(plant, None, run).items()}
    assert {name: number for name, number in totals.items() if name not in KPI_NAMES} == {
        "heat_delivered": None,
        "heat_useful": None,
        "heat_surplus": None,
        "cold_delivered": None,
        "cold_useful": None,
        "cold_surplus": None,
        "electricity_bought": 36000.0,
        "electricity_sold": 3600.0,
        "gas_bought": 72000.0,
        "co2_emitted": 7200.0,
        "methane_emitted": 1800.0,
        "waste": 10800.0,
        "chemicals": 14400.0,
        "losses": 25200.0,
    }


def overflowing():
    """Return a boiler plant and two days of a flow that brings twice the demand."""
    plant = gm.Plant("Boiler")
    plant.add("GasGrid", name="grid")
    plant.add(
        "Boiler", name="boiler", params={"capacity": {"value": 20, "unit": "MW"}, "efficiency": 0.9}
    )
    plant.add(
        "HeatingGrid",
        name="users",
        params={
            "return_temperature": {"value": 60, "unit": "degC"},
            "return_pressure": {"value": 6, "unit": "bar"},
        },
    )
    plant.connect("grid.gas_out", "boiler.fuel_in")
    plant.connect("users.return_out", "boiler.fluid_in")
    plant.connect("boiler.fluid_out", "users.supply_in")
    plant.connect("boiler.flue_out", "flue")
    plant.connect("boiler.loss_out", "loss")
    plant.users.fluid = gm.WATER
    index = pd.date_range("2027-01-01", periods=2, freq="D", tz="UTC", name="time")
    columns = {
        "users.heat_demand": 1e6,
        "users.flow": 2e6 / (4217.4 * 40),
        "boiler.temperature_setpoint": 373.15,
    }
    return plant, gm.simulate(plant, plan=pd.DataFrame(columns, index=index))


def test_totals_tell_the_useful_heat_from_the_surplus():
    """The water gives 2 MW to a demand of 1 MW: half is useful."""
    plant, results = overflowing()
    totals = gm.evaluate.totals(plant, None, results)
    days = 2 * 86400
    assert totals["heat_delivered"].value == pytest.approx(2e6 * days)
    assert totals["heat_useful"].value == pytest.approx(1e6 * days)
    assert totals["heat_surplus"].value == pytest.approx(1e6 * days)
    assert totals["cold_useful"].value is None


def test_the_kpis_and_the_levelised_cost_read_the_useful_heat():
    """A surplus covers nothing and earns nothing."""
    plant, results = overflowing()
    assert gm.evaluate.totals(plant, None, results)["peak_heat"].value == pytest.approx(1e6)
    assert Flows(plant, results).energy("heat") == pytest.approx(1e6 * 365.25 * 86400)
