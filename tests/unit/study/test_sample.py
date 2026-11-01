"""``gm.study.sample`` on plant and case values, with the run replaced by a known cost."""

import json

import numpy as np
import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from tests.fixtures.errors import raises
from tests.unit.study.conftest import shallow_case, shallow_plant

PRICE = "case.assumptions.finance.opex.electricity"
UNCERTAIN = {
    "depth": {
        "kind": "uniform",
        "lower": gm.units.Quantity(1000, "m"),
        "upper": gm.units.Quantity(2000, "m"),
    },
    PRICE: {
        "kind": "normal",
        "mean": gm.units.Quantity(120, "EUR/MWh"),
        "std": gm.units.Quantity(10, "EUR/MWh"),
    },
}


@pytest.fixture
def sampled(runs):
    """Return two samples of one seed over a plant value and a value of the case."""
    return [
        gm.study.sample(shallow_plant(), shallow_case(), UNCERTAIN, ["lcts", "co2"], 6, seed=3)
        for _ in "ab"
    ]


def test_sample_gives_the_same_summary_with_the_same_seed(sampled):
    """The summary holds the percentiles of each metric, in plain JSON."""
    first, second = sampled
    assert first["summary"] == second["summary"] and len(first["samples"]) == 6
    spread = first["summary"]["co2"]
    assert set(spread) == {"mean", "p5", "p50", "p95"}
    numbers = [item["metrics"]["co2"].value for item in first["samples"]]
    assert spread["p50"].value == pytest.approx(np.median(numbers))
    assert spread["p5"].value <= spread["p50"].value <= spread["p95"].value
    json.dumps(to_plain(first), allow_nan=False)


def test_a_value_of_the_case_is_drawn_in_si(sampled, runs):
    """Each draw gives the price in currency per joule, and the run sees it."""
    draws = [item["parameters"][PRICE] for item in sampled[0]["samples"]]
    assert {item.unit for item in draws} == {"currency/J"}
    assert np.mean([item.value for item in draws]) == pytest.approx(120 / 3.6e9, rel=0.2)
    seen = {given.assumptions.finance.opex.electricity for _, given, _ in runs[:6]}
    assert seen == {item.value for item in draws}


def test_another_seed_gives_other_draws(runs):
    """Each depth lies inside its uniform limits."""
    other = gm.study.sample(shallow_plant(), shallow_case(), UNCERTAIN, ["co2"], 3, seed=4)
    drawn = [item["parameters"]["depth"].value for item in other["samples"]]
    assert all(1000 <= number <= 2000 for number in drawn)


def test_a_draw_out_of_the_bounds_of_the_case_fails_and_is_left_out(runs):
    """A negative price is refused by the case; the other draws count."""
    wide = {
        PRICE: {
            "kind": "uniform",
            "lower": gm.units.Quantity(-100, "EUR/MWh"),
            "upper": gm.units.Quantity(100, "EUR/MWh"),
        }
    }
    result = gm.study.sample(shallow_plant(), shallow_case(), wide, ["co2"], 8, seed=0)
    failed = [item for item in result["samples"] if "reason" in item]
    assert failed and len(failed) < 8
    assert result["summary"]["co2"]["mean"].value is not None


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"count": 0}, "invalid_value"),
        ({"metrics": ["lcox"]}, "unknown_name"),
        ({"distributions": {"deph": UNCERTAIN["depth"]}}, "unknown_name"),
        (
            {"distributions": {"case.assumptions.finance.opexx.gas": UNCERTAIN[PRICE]}},
            "unknown_name",
        ),
        ({"distributions": {"case.constraints": UNCERTAIN[PRICE]}}, "invalid_value"),
        ({"distributions": {"depth": {"kind": "beta"}}}, "unknown_name"),
        (
            {"distributions": {"depth": {"kind": "normal", "mean": gm.units.Quantity(1, "m")}}},
            "missing_value",
        ),
        ({"distributions": {PRICE: {"kind": "uniform", "lower": 1, "upper": 2}}}, "invalid_value"),
    ],
)
def test_a_sample_that_does_not_fit_is_refused(arguments, code, runs):
    """Wrong names, kinds, fields and units, before any run."""
    call = dict(distributions=UNCERTAIN, metrics=["co2"], count=2) | arguments
    with raises(gm.errors.ValidationError, code):
        gm.study.sample(shallow_plant(), shallow_case(), **call)
    assert runs == []
