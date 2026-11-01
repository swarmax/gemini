"""Ranking and the Pareto front of several reports."""

import pytest

import gemini as gm
from gemini.types.shapes import measure
from tests.fixtures.errors import raises


def reports():
    """Return four designs by cost and emissions; the third is beaten by the first."""
    figures = [(10.0, 5.0), (8.0, 9.0), (12.0, 6.0), (20.0, 1.0)]
    return [{"lcts": measure(cost, "currency/J"), "co2": co2} for cost, co2 in figures]


def test_one_metric_ranks_the_reports_and_its_best_is_the_front():
    """The smaller cost is rank 1; with one metric the front is its best."""
    found = gm.evaluate.compare(reports(), "lcts")
    assert [entry["ranks"]["lcts"] for entry in found] == [2, 1, 3, 4]
    assert [entry["pareto"] for entry in found] == [False, True, False, False]


def test_two_metrics_mark_the_pareto_front():
    """Design 2 (12, 6) is beaten by design 0 (10, 5); the others trade cost for emissions."""
    found = gm.evaluate.compare(reports(), ["lcts", "co2"])
    assert [entry["pareto"] for entry in found] == [True, True, False, True]
    assert [entry["ranks"] for entry in found][2] == {"lcts": 3, "co2": 3}
    assert found[0]["values"] == {"lcts": 10.0, "co2": 5.0}


def test_a_metric_can_be_preferred_larger():
    """With the cost to minimise and the emissions to maximise, the front changes."""
    found = gm.evaluate.compare(reports(), {"lcts": "min", "co2": "max"})
    assert [entry["pareto"] for entry in found] == [False, True, False, False]


def test_equal_values_share_a_rank_and_both_stay_on_the_front():
    """Two identical designs do not dominate each other."""
    twins = [{"x": 1.0, "y": 2.0}, {"x": 1.0, "y": 2.0}, {"x": 2.0, "y": 3.0}]
    found = gm.evaluate.compare(twins, ["x", "y"])
    assert [entry["ranks"]["x"] for entry in found] == [1, 1, 3]
    assert [entry["pareto"] for entry in found] == [True, True, False]


def test_a_report_without_a_value_ranks_last_and_is_off_the_front():
    """A cost the case could not give."""
    mixed = reports() + [{"lcts": measure(None, "currency/J", "no cost"), "co2": 0.0}]
    found = gm.evaluate.compare(mixed, ["lcts", "co2"])
    assert found[4]["ranks"]["lcts"] == 5 and found[4]["values"]["lcts"] is None
    assert found[4]["pareto"] is False


def test_to_frame_has_a_row_per_report():
    """The metrics, their ranks and the front."""
    frame = gm.evaluate.compare(reports(), ["lcts", "co2"]).to_frame()
    assert list(frame.columns) == [
        "lcts [EUR/MWh]",
        "co2 [kt]",
        "rank_lcts",
        "rank_co2",
        "pareto",
        "feasible",
    ]
    assert frame.loc[1, "lcts [EUR/MWh]"] == pytest.approx(8.0 * 3.6e9)
    assert frame.loc[1, "co2 [kt]"] == pytest.approx(9e-6) and bool(frame.loc[3, "pareto"])


def test_to_frame_takes_the_units_given_and_keeps_a_metric_without_a_unit_in_si():
    """A unit replaces the display unit; the column carries it."""
    found = gm.evaluate.compare(reports() + [{"lcts": 1.0, "co2": 0.0, "n": 3.0}], ["lcts", "n"])
    frame = found.to_frame({"lcts": "EUR/kWh"})
    assert frame.loc[1, "lcts [EUR/kWh]"] == pytest.approx(8.0 * 3.6e6)
    assert "n" in frame.columns


def test_to_frame_refuses_a_unit_that_does_not_fit():
    """An unknown metric, a unit of another dimension, an unknown unit."""
    found = gm.evaluate.compare(reports(), ["lcts", "co2"])
    with raises(gm.errors.ValidationError, "invalid_value", match="units.lct"):
        found.to_frame({"lct": "EUR/MWh"})
    with raises(gm.errors.ValidationError, "invalid_unit"):
        found.to_frame({"lcts": "kt"})
    with raises(gm.errors.ValidationError, "invalid_unit"):
        found.to_frame({"co2": "nothing"})


def served(cost, **parts):
    """Return a report of a given cost; by default it passed and delivered the heat asked for."""
    base = {
        "lcts": measure(cost, "currency/J"),
        "passed": True,
        "failed_steps": 0,
        "constraints": [],
        "services": ["heating", "cooling"],
        "heat_delivered": measure(1.0, "J"),
        "cold_delivered": measure(1.0, "J"),
    }
    return base | parts


def test_an_infeasible_report_is_never_on_the_front_and_ranks_after_the_feasible():
    """The cheapest report fails a constraint: it is not feasible, with the constraint as reason."""
    item = {"name": "heat.unmet", "passed": False}
    cheap = served(1.0, passed=False, constraints=[item])
    found = gm.evaluate.compare([cheap, served(5.0), served(9.0)], "lcts")
    assert [entry["pareto"] for entry in found] == [False, True, False]
    assert [entry["ranks"]["lcts"] for entry in found] == [3, 1, 2]
    assert found[0]["feasible"] is False and found[0]["reasons"] == [item]
    assert found[1]["feasible"] is True and "reasons" not in found[1]


def test_a_report_missing_a_service_ranks_after_all_feasible_ones():
    """The case asks for cooling and the run gave no cold."""
    missing = served(1.0, cold_delivered=measure(None, "J", "no cold"))
    found = gm.evaluate.compare([missing, served(5.0)], "lcts")
    assert found[0]["ranks"]["lcts"] == 2 and found[0]["pareto"] is False
    assert [item["name"] for item in found[0]["reasons"]] == ["cold_delivered"]


def test_a_report_without_the_service_asked_for_is_feasible_and_failed_steps_are_not():
    """A case with heating only needs no cold; a failed step makes a report infeasible."""
    heating = served(5.0, services=["heating"], cold_delivered=measure(None, "J", "none"))
    found = gm.evaluate.compare([heating, served(1.0, failed_steps=2)], "lcts")
    assert [entry["feasible"] for entry in found] == [True, False]
    assert found[1]["reasons"][0]["name"] == "failed_steps"


def test_the_infeasible_are_ordered_by_their_number_of_reasons_then_by_the_metric():
    """Two reasons rank after one, whatever the cost."""
    one = {"name": "a", "passed": False}
    many = served(1.0, passed=False, constraints=[one, one])
    few = served(9.0, passed=False, constraints=[one])
    found = gm.evaluate.compare([many, few, served(7.0)], "lcts")
    assert [entry["ranks"]["lcts"] for entry in found] == [3, 2, 1]


def test_an_unknown_metric_or_sense_is_refused():
    """The names that exist are suggested."""
    with raises(gm.errors.ValidationError, "unknown_name", match="lcts"):
        gm.evaluate.compare(reports(), ["lct"])
    with raises(gm.errors.ValidationError, "invalid_value", match="by.lcts"):
        gm.evaluate.compare(reports(), {"lcts": "smallest"})
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.evaluate.compare(reports(), [])


def test_a_report_with_nothing_to_check_is_feasible_but_unchecked_constraints_are_not():
    """No constraint items: nothing can fail. Items that are all None: nothing was checked."""
    bare = served(5.0, passed=None, constraints=[])
    unchecked = served(1.0, passed=None, constraints=[{"name": "a", "passed": None}])
    found = gm.evaluate.compare([bare, unchecked], "lcts")
    assert [entry["feasible"] for entry in found] == [True, False]
    assert found[0]["pareto"] is True
    assert found[1]["reasons"][0]["reason"] == "no constraint was checked"
