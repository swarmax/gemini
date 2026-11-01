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
    assert list(frame.columns) == ["lcts", "co2", "rank_lcts", "rank_co2", "pareto"]
    assert frame.loc[1, "lcts"] == pytest.approx(8.0) and bool(frame.loc[3, "pareto"])


def test_an_unknown_metric_or_sense_is_refused():
    """The names that exist are suggested."""
    with raises(gm.errors.ValidationError, "unknown_name", match="lcts"):
        gm.evaluate.compare(reports(), ["lct"])
    with raises(gm.errors.ValidationError, "invalid_value", match="by.lcts"):
        gm.evaluate.compare(reports(), {"lcts": "smallest"})
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.evaluate.compare(reports(), [])
