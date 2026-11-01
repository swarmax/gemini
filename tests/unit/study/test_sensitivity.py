"""``gm.study.sensitivity`` on the uncertainty declared in the case, with a known cost model."""

import json

import pytest

import gemini as gm
from tests.fixtures.errors import raises
from tests.unit.study.conftest import shallow_case, shallow_plant

PRICE = "case.assumptions.finance.opex.electricity"
GAS = "case.assumptions.finance.opex.gas"
DECLARED = {
    "assumptions.finance.opex.electricity": {"kind": "uniform", "min": 100, "max": 300},
    "assumptions.finance.opex.gas": {"kind": "normal", "std": 5},
}


@pytest.fixture
def tornado(runs):
    """Return the sensitivity of the cost to the two declared prices."""
    return gm.study.sensitivity(shallow_plant(), shallow_case(uncertain=DECLARED), ["lcts"])


def test_the_declared_bounds_are_the_ends(tornado, runs):
    """A uniform runs at min and max; a normal without bounds at value -/+ std; one pair each."""
    ends = {row["parameter"]: (row["low"].si, row["high"].si) for row in tornado}
    assert ends[PRICE] == pytest.approx((100 / 3.6e9, 300 / 3.6e9))
    assert ends[GAS] == pytest.approx((50 / 3.6e9, 60 / 3.6e9))
    assert len(runs) == 4


def test_the_rows_are_sorted_by_effect(tornado):
    """The electricity price moves the cost 0.2, so it comes first."""
    assert [row["parameter"] for row in tornado] == [PRICE, GAS]
    assert tornado[0]["effect"].value == pytest.approx(0.2)


def test_each_row_has_the_metric_at_both_ends(tornado):
    """Quantities in SI, and the metric as a value."""
    row = tornado[0]
    assert row["low"].unit == "currency/J" and row["high"].si > row["low"].si
    assert row["at_high"].value > row["at_low"].value
    assert row["effect"].unit == "currency/J"


def test_only_declared_values_are_moved_and_the_case_is_unchanged(runs):
    """The depth of the plant is not a row; the case keeps its values."""
    case = shallow_case(uncertain=DECLARED)
    before = case.to_dict()
    found = gm.study.sensitivity(shallow_plant(), case, ["co2", "lcts"], plan=None)
    assert {row["parameter"] for row in found} == {PRICE, GAS}
    assert case.to_dict() == before


def test_the_table_has_a_row_per_parameter_and_metric(runs):
    """Grouped by metric, in the order given."""
    case = shallow_case(uncertain=DECLARED)
    frame = gm.study.sensitivity(shallow_plant(), case, ["co2", "lcts"]).to_frame()
    assert list(frame["metric"]) == ["co2", "co2", "lcts", "lcts"]
    assert set(frame.columns) >= {"parameter", "metric", "low", "high", "effect", "unit"}


def test_a_failed_run_gives_an_effect_with_a_reason_and_goes_last(runs):
    """A normal reaching below zero breaks the bounds of the price."""
    declared = {
        "assumptions.finance.opex.electricity": {"kind": "normal", "std": 150},
        "assumptions.finance.opex.gas": DECLARED["assumptions.finance.opex.gas"],
    }
    found = gm.study.sensitivity(shallow_plant(), shallow_case(uncertain=declared), ["lcts"])
    assert found[-1]["parameter"] == PRICE
    assert found[-1]["effect"].value is None and found[-1]["effect"].reason


def test_a_case_without_uncertainty_is_refused(runs):
    """There is nothing to move."""
    with raises(gm.errors.ValidationError, "missing_value", match="uncertainty"):
        gm.study.sensitivity(shallow_plant(), shallow_case(), ["lcts"])
    assert runs == []


def test_a_metric_that_does_not_exist_is_refused(runs):
    """Before any run."""
    with raises(gm.errors.ValidationError, "unknown_name"):
        gm.study.sensitivity(shallow_plant(), shallow_case(uncertain=DECLARED), ["lcox"])
    assert runs == []


def test_the_table_shows_a_metric_in_its_display_unit_or_the_unit_given(runs):
    """The cost is 0.2 currency/J for the price, shown in EUR/MWh; the CO2 in kt."""
    case = shallow_case(uncertain=DECLARED)
    found = gm.study.sensitivity(shallow_plant(), case, ["co2", "lcts"])
    frame = found.to_frame()
    price = frame[(frame["metric"] == "lcts") & (frame["parameter"] == PRICE)].iloc[0]
    assert price["unit"] == "EUR/MWh" and price["effect"] == pytest.approx(0.2 * 3.6e9)
    kilo = found.to_frame({"lcts": "EUR/kWh"})
    assert kilo[kilo["metric"] == "lcts"]["unit"].eq("EUR/kWh").all()


def test_the_table_refuses_a_unit_that_does_not_fit(runs):
    """A metric that is not in the rows, and a unit of another dimension."""
    case = shallow_case(uncertain=DECLARED)
    found = gm.study.sensitivity(shallow_plant(), case, ["lcts"])
    with raises(gm.errors.ValidationError, "invalid_value", match="units.co2"):
        found.to_frame({"co2": "kt"})
    with raises(gm.errors.ValidationError, "invalid_unit"):
        found.to_frame({"lcts": "kt"})


def test_the_result_round_trips_through_json(tornado):
    """to_dict is plain JSON and from_dict gives an equal Tornado."""
    text = json.dumps(tornado.to_dict(), allow_nan=False)
    again = gm.study.Tornado.from_dict(json.loads(text))
    assert isinstance(again, gm.study.Tornado) and len(again) == len(tornado)
    for new, old in zip(again, tornado):
        assert new["parameter"] == old["parameter"]
        assert new["low"].si == pytest.approx(old["low"].si)
        assert new["effect"].si == pytest.approx(old["effect"].si)


def test_the_bounds_are_shown_in_readable_units_but_kept_in_si(runs):
    """The table and the JSON show EUR/MWh and mD; the rows hold SI quantities."""
    rock = {"kind": "uniform", "min": 100, "max": 600}
    declared = DECLARED | {"environment.reservoir.permeability": rock}
    found = gm.study.sensitivity(shallow_plant(), shallow_case(uncertain=declared), ["lcts"])
    row = next(row for row in found if row["parameter"].endswith("permeability"))
    assert row["low"].unit == "m2" and row["low"].si == pytest.approx(100 * 9.869233e-16)
    frame = found.to_frame().set_index("parameter")
    assert frame.loc[PRICE, ["low", "high"]].tolist() == pytest.approx([100, 300])
    assert frame.loc[PRICE, "value_unit"] == "EUR/MWh"
    assert frame.loc[PRICE, "unit"] == "EUR/MWh"
    permeability = frame.loc["case.environment.reservoir.permeability"]
    assert [permeability["low"], permeability["high"]] == pytest.approx([100, 600])
    assert permeability["value_unit"] == "mD"
    shown = next(r for r in found.to_dict()["rows"] if r["parameter"] == PRICE)
    assert shown["low"] == {"value": pytest.approx(100), "unit": "EUR/MWh"}
    assert shown["effect"]["unit"] == "EUR/MWh"
