"""``gm.study.minimize`` on the shallow plant, with the run replaced by a known cost."""

import json

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.study._utils import trial
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


def megawatts(number):
    """Return ``number`` as a power in MW."""
    return gm.units.Quantity(number, "MW")


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


def test_the_result_is_plain_json_without_the_plant(found):
    """The plant is no part of the JSON form."""
    text = json.dumps(to_plain(found), allow_nan=False)
    assert "peak_boiler" not in text


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


def test_a_plant_with_no_structural_size_cannot_vary_its_doublets(runs):
    """The case asks for doublets and the class takes none: refused before any run."""
    plant = gm.plants.get("DoubletHeatPlant")
    with raises(gm.errors.ValidationError, "invalid_design", match="doublets") as refused:
        gm.study.minimize(plant, shallow_case(), "lcts", evaluations=5)
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
