"""``gm.study.sensitivity`` on plant and case values, with the run replaced by a known cost."""

import pytest

import gemini as gm
from tests.fixtures.errors import raises
from tests.unit.study.conftest import shallow_case, shallow_plant

PRICE = "case.assumptions.finance.opex.electricity"
SPREADS = {
    "depth": {
        "low": gm.units.Quantity(1400, "m"),
        "high": gm.units.Quantity(1900, "m"),
    },
    PRICE: {
        "low": gm.units.Quantity(100, "EUR/MWh"),
        "high": gm.units.Quantity(300, "EUR/MWh"),
    },
}


@pytest.fixture
def tornado(runs):
    """Return the sensitivity of the cost to the depth and the price."""
    return gm.study.sensitivity(shallow_plant(), shallow_case(), SPREADS, ["lcts"])


def test_the_rows_are_sorted_by_effect(tornado, runs):
    """Depth 1400 to 1900 changes the cost by 0.15, the price 100 to 300 by 0.2: the price first."""
    assert [row["parameter"] for row in tornado] == [PRICE, "depth"]
    assert tornado[0]["effect"].value == pytest.approx(0.2)
    assert tornado[1]["effect"].value == pytest.approx(0.15)
    assert len(runs) == 4


def test_each_row_has_the_metric_at_both_ends(tornado):
    """Quantities in SI, and the metric as a value."""
    row = tornado[0]
    assert row["low"].unit == "currency/J" and row["high"].si > row["low"].si
    assert row["at_high"].value > row["at_low"].value
    assert row["effect"].unit == "currency/J"


def test_the_table_has_a_row_per_parameter_and_metric(runs):
    """Grouped by metric, in the order given."""
    found = gm.study.sensitivity(shallow_plant(), shallow_case(), SPREADS, ["co2", "lcts"])
    frame = found.to_frame()
    assert list(frame["metric"]) == ["co2", "co2", "lcts", "lcts"]
    assert (
        list(frame["parameter"][:2]) == ["depth", PRICE] or frame["effect"][0] >= frame["effect"][1]
    )
    assert set(frame.columns) >= {"parameter", "metric", "low", "high", "effect", "unit"}


def test_a_failed_run_gives_an_effect_with_a_reason_and_goes_last(runs):
    """A price below zero breaks the bounds of the case."""
    spreads = SPREADS | {
        PRICE: {"low": gm.units.Quantity(-5, "EUR/MWh"), "high": gm.units.Quantity(5, "EUR/MWh")}
    }
    found = gm.study.sensitivity(shallow_plant(), shallow_case(), spreads, ["lcts"])
    assert found[-1]["parameter"] == PRICE
    assert found[-1]["effect"].value is None and found[-1]["effect"].reason


@pytest.mark.parametrize(
    ("parameters", "code"),
    [
        ({}, "invalid_value"),
        (["depth"], "invalid_value"),
        ({"depth": {"low": 1}}, "invalid_value"),
        ({"deph": SPREADS["depth"]}, "unknown_name"),
    ],
)
def test_a_sensitivity_that_does_not_fit_is_refused(parameters, code, runs):
    """Before any run."""
    with raises(gm.errors.ValidationError, code):
        gm.study.sensitivity(shallow_plant(), shallow_case(), parameters, ["lcts"])
    assert runs == []
