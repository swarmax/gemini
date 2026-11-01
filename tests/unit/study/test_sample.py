"""``gm.study.sample`` on the uncertainty declared in the case, with the run replaced by a cost."""

import json

import numpy as np
import pytest

import gemini as gm
from tests.fixtures.errors import raises
from tests.unit.study.conftest import shallow_case, shallow_plant

PRICE = "case.assumptions.finance.opex.electricity"
PATH = "assumptions.finance.opex.electricity"
DECLARED = {
    PATH: {"kind": "normal", "std": 10, "min": 90, "max": 150},
    "assumptions.finance.opex.gas": {"kind": "triangular", "min": 40, "max": 90},
    "assumptions.finance.discount_rate": {"kind": "uniform", "min": 0.02, "max": 0.08},
}


def declared_case(**uncertain):
    """Return the shallow case with ``DECLARED`` uncertainty, or the one given."""
    return shallow_case(uncertain=uncertain or DECLARED)


@pytest.fixture
def sampled(runs):
    """Return two samples of one seed over the declared values."""
    case = declared_case()
    return [gm.study.sample(shallow_plant(), case, ["lcts", "co2"], 6, 3) for _ in "ab"]


def test_sample_gives_the_same_summary_with_the_same_seed(sampled):
    """The summary holds the percentiles of each metric."""
    first, second = sampled
    assert first["summary"] == second["summary"] and len(first["samples"]) == 6
    spread = first["summary"]["co2"]
    assert set(spread) == {"mean", "p5", "p50", "p95", "failed"}
    numbers = [item["metrics"]["co2"].value for item in first["samples"]]
    assert spread["p50"].value == pytest.approx(np.median(numbers))
    assert spread["p5"].value <= spread["p50"].value <= spread["p95"].value


def test_only_the_declared_values_are_drawn_inside_their_ranges(sampled, runs):
    """Each draw has the three declared names, in SI, inside the declared bounds."""
    draws = sampled[0]["samples"]
    assert set(draws[0]["parameters"]) == {
        PRICE,
        "case.assumptions.finance.opex.gas",
        "case.assumptions.finance.discount_rate",
    }
    prices = [item["parameters"][PRICE] for item in draws]
    assert {item.unit for item in prices} == {"currency/J"}
    assert all(90 / 3.6e9 <= item.value <= 150 / 3.6e9 for item in prices)
    rates = [item["parameters"]["case.assumptions.finance.discount_rate"].value for item in draws]
    assert all(0.02 <= number <= 0.08 for number in rates) and len(set(rates)) > 1
    seen = {given.assumptions.finance.opex.electricity for _, given, _ in runs[:6]}
    assert seen == {item.value for item in prices}


def test_the_case_and_the_plant_are_left_unchanged(runs):
    """Each draw works on a copy: the case still holds its own values."""
    case, plant = declared_case(), shallow_plant()
    before = (case.to_dict(), plant.to_dict())
    gm.study.sample(plant, case, ["co2"], 3, 0)
    assert (case.to_dict(), plant.to_dict()) == before
    assert case.assumptions.finance.opex.electricity == pytest.approx(120 / 3.6e9)
    assert all(given is not case for _, given, _ in runs)


def test_plant_parameters_are_not_drawn(sampled):
    """The depth of the plant is a design decision: it is never a parameter of a draw."""
    assert all("depth" not in item["parameters"] for item in sampled[0]["samples"])


def test_another_seed_gives_other_draws(runs):
    """The draws differ with the seed."""
    case = declared_case()
    one = gm.study.sample(shallow_plant(), case, ["co2"], 3, 1)
    two = gm.study.sample(shallow_plant(), case, ["co2"], 3, 2)
    assert [s["parameters"] for s in one["samples"]] != [s["parameters"] for s in two["samples"]]


def test_a_draw_out_of_the_bounds_of_the_field_fails_and_is_left_out(runs):
    """A normal without bounds can draw a negative price; the case refuses it, the others count."""
    case = declared_case(**{PATH: {"kind": "normal", "std": 200}})
    result = gm.study.sample(shallow_plant(), case, ["co2"], 12, 0)
    failed = [item for item in result["samples"] if "reason" in item]
    assert failed and len(failed) < 12
    assert result["summary"]["co2"]["mean"].value is not None


def test_a_case_without_uncertainty_is_refused(runs):
    """There is nothing to draw."""
    with raises(gm.errors.ValidationError, "missing_value", match="uncertainty"):
        gm.study.sample(shallow_plant(), shallow_case(), ["co2"], 2, 0)
    assert runs == []


@pytest.mark.parametrize(
    ("arguments", "code"),
    [({"count": 0}, "invalid_value"), ({"metrics": ["lcox"]}, "unknown_name")],
)
def test_a_sample_that_does_not_fit_is_refused(arguments, code, runs):
    """A wrong count or metric, before any run."""
    call = dict(metrics=["co2"], count=2, seed=0) | arguments
    with raises(gm.errors.ValidationError, code):
        gm.study.sample(shallow_plant(), declared_case(), **call)
    assert runs == []


def test_the_seed_is_required(runs):
    """A seed is a reproducibility choice: no default."""
    with pytest.raises(TypeError):
        gm.study.sample(shallow_plant(), declared_case(), ["co2"], 2)


def test_the_result_round_trips_through_json(sampled):
    """to_dict is plain JSON and from_dict gives an equal result."""
    first = sampled[0]
    text = json.dumps(first.to_dict(), allow_nan=False)
    again = gm.study.Sample.from_dict(json.loads(text))
    assert isinstance(again, gm.study.Sample)
    assert again["summary"] == first["summary"]
    assert again["samples"] == first["samples"]
    assert json.loads(text)["samples"][0]["parameters"][PRICE]["unit"] == "currency/J"


def test_a_draw_with_failed_steps_gives_no_value_and_is_counted(failing_runs):
    """Its metrics are None with the count and the top failure; the summary leaves it out."""
    case = declared_case(**{PATH: {"kind": "uniform", "min": 100, "max": 300}})
    found = gm.study.sample(shallow_plant(), case, ["lcts"], 8, 1)
    bad = [item for item in found["samples"] if "reason" in item]
    good = [item for item in found["samples"] if "reason" not in item]
    assert bad and good
    for item in bad:
        metric = item["metrics"]["lcts"]
        assert metric.value is None and metric.reason == item["reason"]
        assert "2 steps failed" in metric.reason and "d0.esp out_of_range (2 rows)" in metric.reason
    spread = found["summary"]["lcts"]
    assert spread["failed"].value == len(bad)
    assert spread["mean"].value == pytest.approx(
        np.mean([i["metrics"]["lcts"].value for i in good])
    )
    again = gm.study.Sample.from_dict(json.loads(json.dumps(found.to_dict())))
    assert again["summary"]["lcts"]["failed"].value == len(bad)
