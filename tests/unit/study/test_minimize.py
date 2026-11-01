"""``gm.study.minimize`` on the shallow plant, with the run replaced by a known cost."""

import json

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.study._utils import trial
from gemini.study._utils.best import Best
from tests.fixtures.errors import raises
from tests.unit.study.conftest import shallow_case, shallow_plant

PRICE = "case.assumptions.finance.opex.electricity"
DEPTH = [
    {
        "path": "",
        "parameter": "depth",
        "lower": gm.units.Quantity(1000, "m"),
        "upper": gm.units.Quantity(2000, "m"),
    }
]


@pytest.fixture
def found(runs):
    """Return the search over the choices of the case: 1 to 3 doublets and the depth."""
    return gm.study.minimize(shallow_plant(), shallow_case(), "lcts", evaluations=10)


def test_the_choices_of_the_case_are_the_variables(found, runs):
    """Each of the three counts is searched alone, with the budget for the depth."""
    assert found["evaluations"] == len(found["history"]) == len(runs) == 30
    counts = {item.parts["parameters"]["size.doublets"].value for item in found["history"]}
    assert counts == {1, 2, 3}


def test_the_cheapest_count_wins_with_its_plant(found):
    """The cost model makes two doublets cheapest, near 1500 m."""
    best = found["best"]
    assert best.parts["parameters"]["size.doublets"].value == 2
    assert best.parts["parameters"]["depth"].value == pytest.approx(1500, abs=150)
    assert best.value == min(item.value for item in found["history"] if item.reason is None)
    design = best["plant"]
    assert design.to_dict()["size"] == {"doublets": 2}
    assert design.depth == best.parts["parameters"]["depth"].value


def test_the_result_is_plain_json_with_the_plant_as_its_dict(found):
    """``to_plain`` gives the JSON form, the best plant as its plant dict."""
    text = json.dumps(to_plain(found), allow_nan=False)
    assert "peak_boiler" in text


def test_best_round_trips_through_json_without_an_encoder(runs):
    """``to_dict`` dumps as it is, quantities as ``{value, unit}``; ``from_dict`` reads it back."""
    result = gm.study.minimize(shallow_plant(), shallow_case(), "lcts", DEPTH, evaluations=5)
    best = result["best"]
    plain = json.loads(json.dumps(best.to_dict(), allow_nan=False))
    assert plain["plant"] == best["plant"].to_dict()
    assert plain["parameters"]["depth"].keys() == {"value", "unit"}
    again = Best.from_dict(plain)
    assert again.value == best.value and again.unit == best.unit
    assert again.parts["parameters"] == best.parts["parameters"]
    assert again["plant"].to_dict() == best["plant"].to_dict()
    assert again.to_dict() == best.to_dict()


def test_a_best_without_a_trial_has_no_plant_in_its_json():
    """With no trial that ran, ``plant`` is ``None`` and the round trip keeps the reason."""
    empty = Best(None, "-", "every trial failed", {"parameters": None}, None)
    plain = json.loads(json.dumps(empty.to_dict()))
    assert plain["plant"] is None and plain["reason"] == "every trial failed"
    again = Best.from_dict(plain)
    assert again.value is None and again.plant is None and again.reason == "every trial failed"


def test_the_search_leaves_the_plant_and_the_case_alone(runs):
    """Every trial runs a copy."""
    plant, case = shallow_plant(), shallow_case()
    before = plant.to_dict()
    gm.study.minimize(plant, case, "lcts", DEPTH, evaluations=5)
    assert plant.to_dict() == before and case == shallow_case()
    assert all(copy is not plant for copy, _, _ in runs)


def test_the_same_call_gives_the_same_trials(runs):
    """A fixed seed."""
    one, other = (
        gm.study.minimize(shallow_plant(), shallow_case(), "lcts", DEPTH, evaluations=5)
        for _ in "ab"
    )
    assert one["history"] == other["history"]


def test_a_value_of_the_case_is_a_variable(runs):
    """It is named case.<path>; the lowest price wins, in SI."""
    variables = [
        {
            "path": "case.assumptions.finance.opex",
            "parameter": "electricity",
            "lower": gm.units.Quantity(50, "EUR/MWh"),
            "upper": gm.units.Quantity(200, "EUR/MWh"),
        }
    ]
    result = gm.study.minimize(shallow_plant(), shallow_case(), "lcts", variables, evaluations=10)
    best = result["best"].parts["parameters"][PRICE]
    assert best.unit == "currency/J" and 50 / 3.6e9 <= best.si < 100 / 3.6e9
    assert all(given.assumptions.finance.opex.electricity <= 200 / 3.6e9 for _, given, _ in runs)


def test_explicit_variables_replace_the_choices(runs):
    """Only the depth: the number of doublets stays."""
    result = gm.study.minimize(shallow_plant(), shallow_case(), "lcts", DEPTH, evaluations=5)
    assert result["evaluations"] == 5
    assert result["best"]["plant"].to_dict()["size"] == {"doublets": 1}


def test_a_constraint_rejects_trials(runs):
    """A rejected trial keeps its reason and is never best."""
    constraints = [{"metric": "co2", "maximum": gm.units.Quantity(1.4, "kg")}]
    result = gm.study.minimize(
        shallow_plant(), shallow_case(), "lcts", DEPTH, constraints, evaluations=10
    )
    rejected = [item for item in result["history"] if item.reason]
    assert rejected and all("co2" in item.reason for item in rejected)
    assert result["best"].parts["parameters"]["depth"].value <= 1400


def test_a_leading_minus_maximises(runs):
    """The value keeps the sign of the metric."""
    result = gm.study.minimize(shallow_plant(), shallow_case(), "-co2", DEPTH, evaluations=5)
    assert result["best"].value == max(item.value for item in result["history"])


def test_every_trial_failing_leaves_no_best(monkeypatch, runs):
    """No value and no plant, with the reason."""

    def failing(plant, case, plan=None):
        raise gm.errors.ValidationError("no run", code="invalid_value")

    monkeypatch.setattr(trial, "simulate", failing)
    result = gm.study.minimize(shallow_plant(), shallow_case(), "lcts", DEPTH, evaluations=5)
    assert result["best"].value is None and result["best"].plant is None
    assert "every trial" in result["best"].reason


def test_a_plant_with_no_structural_size_cannot_search_only_its_doublets(runs):
    """Nothing else to search: refused before any run."""
    plant = gm.plants.get("DoubletHeatPlant")
    variables = [{"path": "size", "parameter": "doublets", "lower": 1, "upper": 3}]
    with raises(gm.errors.ValidationError, "invalid_design", match="doublets") as refused:
        gm.study.minimize(plant, shallow_case(), "lcts", variables, evaluations=5)
    assert refused.value.path == "size.doublets" and runs == []


def test_a_case_without_choices_needs_variables(runs):
    """Nothing to search: ``missing_value`` naming ``choices``."""
    case = shallow_case()
    case = case.model_copy(update={"choices": None})
    with raises(gm.errors.ValidationError, "missing_value") as refused:
        gm.study.minimize(shallow_plant(), case, "lcts")
    assert refused.value.path == "choices"


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"objective": "lcox"}, "unknown_name"),
        ({"constraints": [{"metric": "cost", "minimum": 0}]}, "unknown_name"),
        ({"variables": []}, "missing_value"),
        (
            {"variables": [{"path": "", "parameter": "depthh", "lower": 1, "upper": 2}]},
            "unknown_name",
        ),
        (
            {"variables": [{"path": "case.time", "parameter": "step", "lower": 1, "upper": 2}]},
            "invalid_value",
        ),
        ({"evaluations": 4}, "invalid_value"),
    ],
)
def test_a_search_that_does_not_fit_is_refused(arguments, code, runs):
    """Before any simulation."""
    call = {"objective": "lcts"} | arguments
    with raises(gm.errors.ValidationError, code):
        gm.study.minimize(shallow_plant(), shallow_case(), **call)
    assert runs == []


CAPACITY = {
    "path": "heat_pump",
    "parameter": "capacity",
    "lower": gm.units.Quantity(1, "MW"),
    "upper": gm.units.Quantity(2, "MW"),
}


def failing_above(limit):
    """Return a replacement of the constraints that fails when the depth is above ``limit`` m."""

    def checks(plant, case, results):
        deep = plant.depth - limit
        if deep <= 0:
            return []
        value, bound = gm.types.shapes.measure(plant.depth, "m"), gm.types.shapes.measure(
            limit, "m"
        )
        return [{"name": "d0.depth", "passed": False, "value": value, "limit": bound}]

    return checks


def test_the_cheapest_trial_that_breaks_a_constraint_is_not_best(monkeypatch, runs):
    """The cost falls with a shallower depth in this model only above 1500 m: a limit decides."""
    monkeypatch.setattr(trial, "constraints", failing_above(1200))
    result = gm.study.minimize(shallow_plant(), shallow_case(), "lcts", DEPTH, evaluations=5)
    assert result["feasible"] is True
    assert result["best"].parts["parameters"]["depth"].value <= 1200
    broken = [item for item in result["history"] if item.reason]
    assert broken and all(item.reason["name"] == "d0.depth" for item in broken)
    assert all(item.parts["violation"] > 0 for item in broken)


def test_without_a_feasible_trial_the_least_violating_one_is_best(monkeypatch, runs):
    """``feasible`` is false and the best trial is the shallowest, the nearest to the limit."""
    monkeypatch.setattr(trial, "constraints", failing_above(900))
    result = gm.study.minimize(shallow_plant(), shallow_case(), "lcts", DEPTH, evaluations=5)
    assert result["feasible"] is False and result["best"].reason["name"] == "d0.depth"
    violations = [item.parts["violation"] for item in result["history"]]
    assert result["best"].parts["violation"] == min(violations)
    assert result["best"]["plant"].depth == result["best"].parts["parameters"]["depth"].value


def test_a_trial_that_raises_is_infeasible_and_the_search_goes_on(monkeypatch, runs):
    """A physics error at some depth costs the trial, not the search."""
    cost = trial.metric

    def deep_fails(plant, case, results, name):
        if plant.depth > 1700:
            raise gm.errors.ValidationError("negative head", code="invalid_value")
        return cost(plant, case, results, name)

    monkeypatch.setattr(trial, "metric", deep_fails)
    result = gm.study.minimize(shallow_plant(), shallow_case(), "lcts", DEPTH, evaluations=5)
    failed = [item for item in result["history"] if item.value is None]
    assert failed and all(item.parts["violation"] == trial.LARGEST_VIOLATION for item in failed)
    assert result["feasible"] and result["best"].parts["parameters"]["depth"].value <= 1700


def test_a_plant_without_doublets_is_searched_over_depth(runs):
    """The count goes to ``fixed`` with the reason, and the depth of the doublet is searched."""
    plant = gm.plants.get("DoubletHeatPlant")
    result = gm.study.minimize(plant, shallow_case(), "lcts", evaluations=5)
    assert [item["name"] for item in result["fixed"]] == ["size.doublets"]
    assert result["fixed"][0]["value"].value == 1 and "takes no" in result["fixed"][0]["reason"]
    assert result["evaluations"] == 5
    assert "depth" in result["history"][0].parts["parameters"]


def test_a_role_variable_reaches_every_unit_of_the_role(runs):
    """The capacity goes to the heat pump of every trial plant."""
    result = gm.study.minimize(shallow_plant(), shallow_case(), "lcts", [CAPACITY], evaluations=5)
    assert result["fixed"] == []
    assert all(
        1e6 <= item.parts["parameters"]["heat_pump.capacity"].value <= 2e6
        for item in result["history"]
    )
    assert result["best"]["plant"].get_submodule("heat_pump").capacity == pytest.approx(
        result["best"].parts["parameters"]["heat_pump.capacity"].value
    )
    assert all(copy.get_submodule("heat_pump").capacity <= 2e6 for copy, _, _ in runs)


def test_a_role_the_plant_lacks_is_fixed(runs):
    """It is not searched and the result says why."""
    other = {**CAPACITY, "path": "chp"}
    result = gm.study.minimize(
        shallow_plant(), shallow_case(), "lcts", [other, *DEPTH], evaluations=5
    )
    assert result["fixed"] == [
        {"name": "chp.capacity", "value": None, "reason": "the plant has no unit of the role 'chp'"}
    ]
    assert result["evaluations"] == 5


def test_the_plant_as_given_is_one_of_the_trials(runs):
    """The search starts from the plant, so its depth is tried and the best is never worse."""
    plant = shallow_plant()
    plant.depth = 1234.0
    found = gm.study.minimize(plant, shallow_case(), "lcts", DEPTH, evaluations=5)
    depths = [item.parts["parameters"]["depth"].value for item in found["history"]]
    assert 1234.0 in depths
    start = next(
        item for item in found["history"] if item.parts["parameters"]["depth"].value == 1234.0
    )
    assert found["best"].value <= start.value
