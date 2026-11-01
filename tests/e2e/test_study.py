"""The study on real runs of the shallow sample, over two days: no simulation is replaced."""

import pytest

import gemini as gm
from gemini.study._utils.resize import resized
from tests.unit.study.conftest import shallow_case, shallow_plant

PRICE = "case.assumptions.finance.opex.electricity"
GAS = "case.assumptions.finance.opex.gas"
UNCERTAIN = {
    "assumptions.finance.opex.electricity": {"kind": "uniform", "min": 50, "max": 200},
    "assumptions.finance.opex.gas": {"kind": "uniform", "min": 54, "max": 56},
}
COUNTS = [
    {"path": "size", "parameter": "doublets", "lower": 1, "upper": 3},
]


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    """Return the shallow case over its first two days."""
    return shallow_case(days=2, folder=tmp_path_factory.mktemp("case"), uncertain=UNCERTAIN)


def lcts(plant, case):
    """Return the LCTS of a real run of ``plant`` on ``case``, in SI."""
    results = gm.simulate(plant, case)
    return gm.evaluate.lcts(plant, case, results).si


def test_minimize_over_the_doublets_finds_the_cheapest_of_three_runs(case):
    """Each count run alone, then the search over the counts."""
    plant = shallow_plant()
    costs = {count: lcts(resized(plant, count), case) for count in (1, 2, 3)}
    found = gm.study.minimize(plant, case, "lcts", COUNTS)
    cheapest = min(costs, key=costs.get)
    assert found["evaluations"] == 3
    assert found["best"].parts["parameters"]["size.doublets"].value == cheapest
    assert found["best"].value == pytest.approx(costs[cheapest])
    assert found["best"]["plant"].to_dict()["size"] == {"doublets": cheapest}


def test_sensitivity_orders_the_prices_by_their_effect(case):
    """A range of 150 EUR/MWh in electricity moves more than 2 EUR/MWh of gas."""
    found = gm.study.sensitivity(shallow_plant(), case, ["lcts"])
    assert [row["parameter"] for row in found] == [PRICE, GAS]
    assert found[0]["at_high"].si > found[0]["at_low"].si
    assert found[0]["effect"].si == pytest.approx(
        abs(found[0]["at_high"].si - found[0]["at_low"].si)
    )


def test_sample_gives_a_spread_of_lcts_and_co2_over_case_and_plant_values(case):
    """Three draws of the two declared prices, each a real run."""
    found = gm.study.sample(shallow_plant(), case, ["lcts", "co2"], 3, 0)
    assert all("reason" not in item for item in found["samples"])
    for metric in ("lcts", "co2"):
        spread = found["summary"][metric]
        assert spread["p5"].si <= spread["p50"].si <= spread["p95"].si
    assert found["summary"]["lcts"]["p95"].si > found["summary"]["lcts"]["p5"].si
