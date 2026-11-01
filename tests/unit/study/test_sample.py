"""``gm.study.sample`` on a boiler and a heat user."""

import json

import numpy as np
import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.study._utils import trial
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_results
from tests.unit.study.test_minimize import boiler_plant, problem, profile, watts

UNCERTAIN = {
    "boiler.capacity": {"kind": "uniform", "lower": watts(2e5), "upper": watts(2e6)},
    "boiler.efficiency": {"kind": "triangular", "lower": 0.7, "mode": 0.8, "upper": 0.9},
    "users.return_pressure": {
        "kind": "normal",
        "mean": gm.units.Quantity(6, "bar"),
        "std": gm.units.Quantity(0.1, "bar"),
    },
}


@pytest.fixture(scope="module")
def sampled():
    """Return two samples of one seed."""
    plant = boiler_plant()
    return [
        gm.study.sample(plant, None, UNCERTAIN, ["peak_heat"], 6, seed=3, plan=profile())
        for _ in "ab"
    ]


def test_sample_gives_the_same_summary_with_the_same_seed(sampled):
    """Each draw is a simulation; the summary holds the percentiles, in plain JSON."""
    first, second = sampled
    assert first == second
    assert len(first["samples"]) == 6
    spread = first["summary"]["peak_heat"]
    assert set(spread) == {"mean", "p5", "p50", "p95"}
    assert {item.unit for item in spread.values()} == {"W"}
    numbers = [item["metrics"]["peak_heat"].value for item in first["samples"]]
    assert spread["p50"].value == pytest.approx(np.median(numbers))
    assert spread["p5"].value <= spread["p50"].value <= spread["p95"].value
    json.dumps(to_plain(first), allow_nan=False)


def test_another_seed_gives_other_draws(sampled):
    """Each draw lies inside its uniform limits."""
    other = gm.study.sample(
        boiler_plant(), None, UNCERTAIN, ["peak_heat"], 3, seed=4, plan=profile()
    )
    assert other["samples"][0]["parameters"] != sampled[0]["samples"][0]["parameters"]
    drawn = [item["parameters"]["boiler.capacity"].value for item in other["samples"]]
    assert all(2e5 <= number <= 2e6 for number in drawn)


def test_a_draw_that_fails_is_recorded_and_left_out_of_the_summary():
    """An efficiency above one is refused; the other draws count."""
    wide = {"boiler.efficiency": {"kind": "uniform", "lower": 0.6, "upper": 1.4}}
    result = gm.study.sample(boiler_plant(), None, wide, ["peak_heat"], 6, seed=0, plan=profile())
    failed = [item for item in result["samples"] if "reason" in item]
    assert failed and len(failed) < 6
    assert result["summary"]["peak_heat"]["mean"].value is not None


def test_a_metric_no_draw_gives_says_so():
    """Nothing to spread: ``None`` with the reason, and the unit of the metric."""
    result = gm.study.sample(boiler_plant(), None, UNCERTAIN, ["peak_cold"], 2, plan=profile())
    spread = result["summary"]["peak_cold"]
    assert spread["mean"].value is None and spread["p95"].value is None
    assert spread["mean"].reason and spread["mean"].unit == "W"


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"count": 0}, "invalid_value"),
        ({"metrics": ["lcox"]}, "unknown_name"),
        ({"distributions": {"boiler.capacty": UNCERTAIN["boiler.capacity"]}}, "unknown_name"),
        ({"distributions": {"boiler.capacity": {"kind": "beta"}}}, "unknown_name"),
        (
            {"distributions": {"boiler.capacity": {"kind": "normal", "mean": watts(1)}}},
            "missing_value",
        ),
        (
            {
                "distributions": {
                    "boiler.capacity": {"kind": "normal", "mean": watts(1), "std": watts(-1)}
                }
            },
            "invalid_value",
        ),
    ],
)
def test_a_sample_that_does_not_fit_is_refused(arguments, code):
    """Wrong names, kinds and fields."""
    call = dict(distributions=UNCERTAIN, metrics=["peak_heat"], count=2) | arguments
    with raises(gm.errors.ValidationError, code):
        gm.study.sample(boiler_plant(), None, plan=profile(), **call)


def test_each_draw_runs_a_copy_on_the_problem_and_the_plan(monkeypatch):
    """The problem and the plan go to every draw; the plant itself is not run."""
    calls = []

    def fake(plant, problem=None, plan=None):
        calls.append((plant, problem, plan))
        return make_results({"users": {"unmet_demand": [0.0]}})

    monkeypatch.setattr(trial, "simulate", fake)
    plant, demanded, plan = boiler_plant(), problem(), profile()
    found = gm.study.sample(plant, demanded, UNCERTAIN, ["peak_heat"], 3, plan=plan)
    assert len(found["samples"]) == len(calls) == 3
    assert all(copy is not plant and given is demanded for copy, given, _ in calls)
    assert all(given_plan is plan for _, _, given_plan in calls)


def test_no_problem_and_no_plan_are_refused():
    """Nothing is assumed: not a demand, not a plan."""
    with raises(gm.errors.ValidationError, "missing_value") as refused:
        gm.study.sample(boiler_plant(), None, UNCERTAIN, ["peak_heat"], count=2)
    assert refused.value.path == "problem"
