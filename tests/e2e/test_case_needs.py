"""What a heating and cooling case needs of gemini: one test per need, each in general terms.

The list is in ``.claude/docs/testing.md``. The demand is a file written here, the plant dict the
design of a sample case, sized as each test needs.
"""

from copy import deepcopy

import pandas as pd
import pytest

import gemini as gm
from gemini.case._utils.kinds import EQUIPMENT_KINDS
from gemini.run._utils.apply import apply_case
from gemini.units import Quantity
from tests.fixtures.sample_cases import sample_case, template_dict

pytestmark = pytest.mark.xdist_group("case_needs")

HOURS = 12
HEAT_MW = 12.0
COLD_MW = 5.0
LIMITS = [
    {
        "on": "doublet",
        "quantity": "production_flow",
        "when": "running",
        "min": {"value": 60, "unit": "m3/h"},
        "max": {"value": 320, "unit": "m3/h"},
    },
    {
        "on": "doublet",
        "quantity": "brine_cooling",
        "when": "running",
        "max": {"value": 45, "unit": "K"},
    },
]


PLACEHOLDERS = {
    "pipe": {"value": 300, "unit": "EUR/m"},
    "cooler": {"value": 0.1, "unit": "EUR/W"},
    "adsorption_chiller": {"value": 0.3, "unit": "EUR/W"},
}
"""Factors the sample case does not hold, for kinds this plant uses: a test value, no source."""


def sized_dict(doublets):
    """Return the plant dict on ``doublets`` doublets, each with the values of ``d0``."""
    data = deepcopy(template_dict("HeatingCoolingPlant"))
    data["size"] = {"doublets": doublets}
    own = {name: item for name, item in data["params"].items() if not name.startswith(("d0", "d1"))}
    first = {name[3:]: item for name, item in data["params"].items() if name.startswith("d0.")}
    data["params"] = own | {
        f"d{index}.{name}": item for index in range(doublets) for name, item in first.items()
    }
    return data


def demand_file(folder):
    """Write an hourly demand in kW under names of its own and return its path."""
    index = pd.date_range("2031-02-03", periods=HOURS, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {"stamp": index, "heat_kw": HEAT_MW * 1000, "cold_kw": COLD_MW * 1000},
    )
    path = folder / "demand.csv"
    frame.to_csv(path, index=False)
    return path


def case_of(folder, *constraints):
    """Return the case on the demand file of ``folder``, with the site and prices of the sample."""
    data = sample_case().to_dict()
    data["time"] = {
        "start": "2031-02-03",
        "end": "2031-02-03T12:00",
        "step": {"value": 1, "unit": "h"},
    }
    heating, cooling = data["demand"]["heating"], data["demand"]["cooling"]
    data["demand"] = {
        "file": "demand.csv",
        "time_column": "stamp",
        "heating": heating | {"column": "heat_kw", "unit": "kW"},
        "cooling": cooling | {"column": "cold_kw", "unit": "kW"},
    }
    data["constraints"] = [*LIMITS, *constraints]
    finance = data["assumptions"]["finance"]
    finance["capex"] |= PLACEHOLDERS
    finance["opex"]["fixed"] = {kind: {"value": 2, "unit": "%/yr"} for kind in EQUIPMENT_KINDS}
    return gm.Case.from_dict(data, folder)


def run_on(plant, case):
    """Return the results of the case on ``plant``; a failed step fails the test."""
    return gm.simulate(plant, case)


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    """Return a folder holding the demand file written for this module."""
    folder = tmp_path_factory.mktemp("demand")
    demand_file(folder)
    return folder


@pytest.fixture(scope="module")
def case(folder):
    """Return the case of the demand file."""
    return case_of(folder)


@pytest.fixture(scope="module")
def plant():
    """Return the plant on two doublets, not changed by a test."""
    return gm.Plant.from_dict(sized_dict(2))


@pytest.fixture(scope="module")
def results(plant, case):
    """Return one run of the plant on the case, read by the constraint tests."""
    return run_on(plant, case)


def worst(plant, case, results, on, quantity, **bounds):
    """Return the check of one constraint on the run, for each unit of the role."""
    limit = gm.case.Constraint(on=on, quantity=quantity, when="running", **bounds)
    checks = gm.evaluate.constraints(
        plant, case.model_copy(update={"constraints": (limit,)}), results
    )
    return [item for item in checks if (item["role"], item["quantity"]) == (on, quantity)]


def test_heating_and_cooling_demand_come_from_a_file(case):
    """Any column names, any unit, a constant step: the demand is in W on a UTC index."""
    demand = case.demand.frame
    assert list(demand) == ["heating_demand", "cooling_demand"]
    assert demand["heating_demand"].iloc[0] == pytest.approx(HEAT_MW * 1e6)
    assert demand["cooling_demand"].iloc[0] == pytest.approx(COLD_MW * 1e6)
    assert str(demand.index.tz) == "UTC"
    assert demand.attrs["units"]["heating_demand"] == "W"


@pytest.mark.parametrize("doublets", [1, 2, 3])
def test_a_plant_runs_on_one_to_three_doublets(case, doublets):
    """Every step runs, and the first doublet carries flow."""
    plant = gm.Plant.from_dict(sized_dict(doublets))
    results = run_on(plant, case)
    assert results.errors() == []
    assert max(results.get("d0.reservoir", "liquid_flow")["value"]) > 0


def test_a_chosen_depth_sets_the_reservoir(case):
    """The plant's ``depth`` reaches each doublet, whose geotherm gives its temperature."""
    shallow, deep = sized_dict(2), sized_dict(2)
    shallow["params"]["depth"], deep["params"]["depth"] = {"value": 2000, "unit": "m"}, {
        "value": 3000,
        "unit": "m",
    }
    gradient = gm.units.convert(1, "K/km", "K/m") * 30
    applied = [apply_case(gm.Plant.from_dict(data), case) for data in (deep, shallow)]
    lift = applied[0].d1.reservoir.temperature - applied[1].d1.reservoir.temperature
    assert lift == pytest.approx(gradient * 1000, rel=1e-9)


def test_co_produced_gas_goes_to_the_boiler_before_the_grid(plant, case, results):
    """The gas of the brine reaches the fuel of the boiler and burns or leaves by the flare."""
    produced = results.get("degasser", "gas_out.chemical_flow")["value"]
    assert min(produced) > 0
    fuel = gm.evaluate.totals(plant, case, results)
    assert fuel["gas_bought"].value == pytest.approx(0.0, abs=1e-6)
    assert max(results.get("gas_grid", "gas_out.chemical_flow")["value"]) < max(produced)


def test_a_limit_on_the_flow_range_of_each_doublet(plant, case, results):
    """One check per doublet; a range the run leaves fails."""
    bounds = {"min": Quantity(60, "m3/h"), "max": Quantity(320, "m3/h")}
    checks = worst(plant, case, results, "doublet", "production_flow", **bounds)
    assert [item["passed"] for item in checks] == [True, True]
    tight = worst(plant, case, results, "doublet", "production_flow", max=Quantity(10, "m3/h"))
    assert not all(item["passed"] for item in tight)


def test_a_limit_on_the_brine_cooling(plant, case, results):
    """The cooling of the brine from producer to injector, each doublet."""
    checks = worst(plant, case, results, "doublet", "brine_cooling", max=Quantity(45, "K"))
    assert [item["passed"] for item in checks] == [True, True]


def test_a_limit_on_a_parameter(plant, case, results):
    """A limit may name a parameter of a design, judged without the run's outputs."""
    checks = worst(plant, case, results, "doublet", "pump_efficiency", min=0.6, max=0.8)
    assert [item["passed"] for item in checks] == [True, True]
    assert not worst(plant, case, results, "doublet", "pump_efficiency", min=0.9)[0]["passed"]


def test_a_limit_on_the_volume_balance(plant, case, results):
    """What a doublet produces it injects again."""
    bounds = {"min": Quantity(-1e-6, "m3/s"), "max": Quantity(1e-6, "m3/s")}
    checks = worst(plant, case, results, "doublet", "volume_imbalance", **bounds)
    assert [item["passed"] for item in checks] == [True, True]


def test_limits_on_the_supply_temperatures(plant, case, results):
    """The supply at the heat users and at the cold users."""
    heat = worst(plant, case, results, "heating_supply", "temperature", min=Quantity(95, "degC"))
    cold = worst(plant, case, results, "cooling_supply", "temperature", max=Quantity(21, "degC"))
    assert heat[0]["passed"] and cold[0]["passed"]


def duration(**bound):
    """Return a constraint on the time each doublet carries flow."""
    return {
        "on": "doublet",
        "quantity": "production_flow",
        "over": "duration",
        "when": "running",
    } | bound


def test_a_limit_on_the_operating_time(folder):
    """Each doublet runs the time of the rule, with its outages at whole steps."""
    plant = gm.Plant.from_dict(sized_dict(2))
    results = run_on(plant, case_of(folder, duration(max={"value": 11, "unit": "h"})))
    for hours, passes in ((11, True), (5, False)):
        bound = gm.case.Constraint(**duration(equals=Quantity(hours, "h")))
        case = case_of(folder).model_copy(update={"constraints": (bound,)})
        checks = gm.evaluate.constraints(plant, case, results)
        assert all(item["passed"] for item in checks) is passes


def test_a_levelised_cost_of_heat_and_cold_together(plant, case, results):
    """LCTS of the run on stated prices."""
    assert gm.evaluate.lcts(plant, case, results).value > 0
