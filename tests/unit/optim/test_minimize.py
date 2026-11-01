"""``gm.optim.minimize`` on a boiler and a heat user."""

import json

import pandas as pd
import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.optim._utils import trial
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_results

DEMAND = 1e6
"""Constant heat demand [W]."""


def watts(number):
    """Return ``number`` as a power."""
    return gm.units.Quantity(number, "W")


CAPACITY = [{"path": "boiler", "parameter": "capacity", "lower": watts(2e5), "upper": watts(3e6)}]
PEAK = "boiler.capacity"


def problem(**parts):
    """Return a problem of the same two days; the plan of ``profile`` is what the runs follow."""
    demand = gm.data.from_values([DEMAND] * 2, "W", "2027-01-01", "1 d", "heating_demand")
    return gm.Problem(demand, **parts)


def boiler_plant():
    """Return a gas boiler and its heat user, with the heat water named at 60 and 100 degC."""
    plant = gm.Plant("Boiler")
    plant.add("GasGrid", name="grid")
    plant.add(
        "Boiler", name="boiler", params={"capacity": {"value": 2, "unit": "MW"}, "efficiency": 0.9}
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
    plant.get_submodule("users").fluid = gm.WATER
    return plant


def profile():
    """Return the plan of two days of the same demand, with flow to spare."""
    index = pd.date_range("2027-01-01", periods=2, freq="D", tz="UTC")
    columns = {
        "users.heat_demand": DEMAND,
        "users.flow": 20.0,
        "boiler.temperature_setpoint": 373.15,
    }
    return pd.DataFrame(columns, index=index)


@pytest.fixture(scope="module")
def half_covered():
    """Return the search for the smallest peak that covers half the demand: half its capacity."""
    constraints = [{"metric": "heating_coverage", "minimum": 0.5}]
    return gm.optim.minimize(
        boiler_plant(), None, CAPACITY, "peak_heat", constraints, evaluations=20, plan=profile()
    )


def test_minimize_finds_the_optimum_within_the_budget(half_covered):
    """The constraint sets the optimum; the result is plain JSON and ready for ``set_params``."""
    best = half_covered["best"]
    assert best.parts["parameters"][PEAK].si == pytest.approx(DEMAND / 2, rel=0.05)
    assert best.value == pytest.approx(DEMAND / 2, rel=0.05)
    assert best.unit == "W"
    assert half_covered["evaluations"] == len(half_covered["history"]) == 20
    json.dumps(to_plain(half_covered), allow_nan=False)


def test_a_trial_that_breaks_a_constraint_is_recorded_and_never_best(half_covered):
    """Its reason stays in the history."""
    rejected = [item for item in half_covered["history"] if item.reason]
    assert rejected and all("heating_coverage" in item.reason for item in rejected)
    assert all(item.parts["parameters"][PEAK].value < 0.5 * DEMAND for item in rejected)
    assert half_covered["best"].parts["parameters"][PEAK].value >= 0.5 * DEMAND


def test_a_failed_run_is_recorded_too():
    """A bound of the parameter refuses a trial; the others carry on."""
    variables = [{"path": "boiler", "parameter": "efficiency", "lower": 0.5, "upper": 1.5}]
    result = gm.optim.minimize(
        boiler_plant(), None, variables, "peak_heat", evaluations=10, plan=profile()
    )
    failed = [item for item in result["history"] if item.reason]
    assert failed and all(
        item.parts["parameters"]["boiler.efficiency"].value > 1 for item in failed
    )
    assert all(item.value is None for item in failed)
    assert result["best"].parts["parameters"]["boiler.efficiency"].value <= 1


def test_every_trial_failing_leaves_no_best():
    """No value, with the reason."""
    variables = [{"path": "boiler", "parameter": "efficiency", "lower": 1.2, "upper": 1.5}]
    result = gm.optim.minimize(
        boiler_plant(), None, variables, "peak_heat", evaluations=5, plan=profile()
    )
    assert result["best"].value is None and result["best"].parts["parameters"] is None
    assert "every trial" in result["best"].reason


def test_a_leading_minus_maximises():
    """The value keeps the sign of the metric."""
    variables = [dict(CAPACITY[0], upper=watts(DEMAND))]
    result = gm.optim.minimize(
        boiler_plant(), None, variables, "-peak_heat", evaluations=10, plan=profile()
    )
    assert result["best"].value == pytest.approx(DEMAND, rel=0.1)
    assert result["best"].value == max(item.value for item in result["history"])


@pytest.fixture(scope="module")
def repeated():
    """Return a plant, its first state and two equal searches on it."""
    plant = boiler_plant()
    before = plant.to_dict()
    runs = [
        gm.optim.minimize(plant, None, CAPACITY, "peak_heat", evaluations=5, plan=profile())
        for _ in "ab"
    ]
    return plant, before, runs


def test_the_same_call_gives_the_same_trials_and_leaves_the_plant_alone(repeated):
    """The search has a fixed seed and works on copies."""
    plant, before, runs = repeated
    assert runs[0] == runs[1] and plant.to_dict() == before


def test_an_economic_metric_reads_the_assumptions_of_the_problem():
    """With them a value per year."""
    variables = [dict(CAPACITY[0], lower=watts(DEMAND), upper=watts(2 * DEMAND))]
    values = gm.Assumptions(
        discount_rate=0.05, lifetime_years=20, prices={"gas": {"value": 40.0, "unit": "EUR/MWh"}}
    )
    run = gm.optim.minimize(
        boiler_plant(),
        problem(assumptions=values),
        variables,
        "annualised_cost",
        evaluations=5,
        plan=profile(),
    )
    assert run["best"].unit == "currency/yr" and run["best"].reason is None


def test_an_economic_metric_without_assumptions_gives_the_reason():
    """What is missing is in the history, and no trial is best."""
    variables = [dict(CAPACITY[0], lower=watts(DEMAND), upper=watts(2 * DEMAND))]
    idle = gm.optim.minimize(
        boiler_plant(), problem(), variables, "lcts", evaluations=5, plan=profile()
    )
    assert "discount_rate" in idle["history"][0].reason and idle["best"].value is None


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"objective": "lcox"}, "unknown_name"),
        ({"constraints": [{"metric": "cost", "minimum": 0}]}, "unknown_name"),
        ({"variables": []}, "missing_value"),
        ({"variables": [dict(CAPACITY[0], lower=watts(2e6), upper=watts(1e6))]}, "invalid_value"),
        ({"variables": [dict(CAPACITY[0], parameter="capacty")]}, "unknown_name"),
        ({"evaluations": 4}, "invalid_value"),
    ],
)
def test_a_search_that_does_not_fit_is_refused(arguments, code):
    """Before any simulation."""
    call = dict(variables=CAPACITY, objective="peak_heat") | arguments
    with raises(gm.errors.ValidationError, code):
        gm.optim.minimize(boiler_plant(), None, plan=profile(), **call)


def recorded_runs(monkeypatch):
    """Replace the run of a trial by a recorder of its arguments and return the record."""
    calls = []

    def fake(plant, problem=None, plan=None):
        calls.append((plant, problem, plan))
        return make_results({"users": {"unmet_demand": [0.0]}})

    monkeypatch.setattr(trial, "simulate", fake)
    return calls


def test_each_trial_runs_a_copy_on_the_problem_and_the_plan(monkeypatch):
    """The plant itself is never run, and the problem and the plan go to every trial."""
    calls = recorded_runs(monkeypatch)
    plant, demanded, plan = boiler_plant(), problem(), profile()
    found = gm.optim.minimize(plant, demanded, CAPACITY, "peak_heat", evaluations=5, plan=plan)
    assert len(calls) == found["evaluations"] == 5
    assert all(copy is not plant and given is demanded for copy, given, _ in calls)
    assert all(given_plan is plan for _, _, given_plan in calls)
    assert {copy.params_at("boiler", None)["capacity"] for copy, _, _ in calls} != {2e6}


def test_without_a_plan_the_run_plans_the_problem(monkeypatch):
    """The plan stays ``None``: ``gm.simulate`` schedules the demand on the design of the trial."""
    calls = recorded_runs(monkeypatch)
    gm.optim.minimize(boiler_plant(), problem(), CAPACITY, "peak_heat", evaluations=5)
    assert [item[2] for item in calls] == [None] * 5


def test_no_problem_and_no_plan_are_refused():
    """Nothing is assumed: not a demand, not a plan."""
    with raises(gm.errors.ValidationError, "missing_value") as refused:
        gm.optim.minimize(boiler_plant(), None, CAPACITY, "peak_heat", evaluations=5)
    assert refused.value.path == "problem"


def test_an_economic_metric_without_a_problem_is_refused():
    """The prices are in the problem."""
    with raises(gm.errors.ValidationError, "missing_value", match="assumptions"):
        gm.optim.minimize(boiler_plant(), None, CAPACITY, "lcts", evaluations=5, plan=profile())
