"""The declared output limits against synthetic columns and the example plant."""

import math

import gemini as gm
from gemini._utils.jsonable import to_plain
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.result_tables import make_results


def test_values_inside_the_declared_limits_pass():
    """A return temperature above 0 K is inside the Temperature limit; NaN is a missing tick."""
    results = make_results({"heat": {"return_out.temperature": [300.0, math.nan, 310.0]}})
    assert to_plain(gm.evaluate.bounds(heating_plant(), None, results)) == {
        "name": "bounds",
        "passed": True,
        "value": {"value": 0, "unit": "-"},
        "limit": {"value": 0, "unit": "-"},
    }


def test_values_outside_the_limits_are_counted():
    """Two of three temperatures are not above 0 K."""
    results = make_results({"heat": {"return_out.temperature": [300.0, -1.0, 0.0]}})
    result = gm.evaluate.bounds(heating_plant(), None, results)
    assert result["passed"] is False and result["value"].value == 2


def test_nothing_with_a_limit_is_undecided():
    """An output without a limit gives ``passed`` None and says so."""
    results = make_results({"heat": {"unmet_demand": [1.0]}})
    result = gm.evaluate.bounds(heating_plant(), None, results)
    assert result["passed"] is None
    assert result["value"].reason == "no recorded output has a declared limit"


def test_a_path_the_plant_lacks_is_refused():
    """Results of another plant raise with the path."""
    results = make_results({"elsewhere": {"return_out.temperature": [300.0]}})
    try:
        gm.evaluate.bounds(heating_plant(), None, results)
    except gm.errors.ValidationError as error:
        assert "elsewhere" in str(error)
    else:
        raise AssertionError("expected ValidationError")


def test_the_example_plant_run_stays_inside_its_limits(fresh_plant, fast_dataset):
    """A six-hour replay records no output outside a declared limit."""
    replay = gm.replay(fresh_plant, fast_dataset.window(None, "2024-07-01T06:00:00Z"))
    result = gm.evaluate.bounds(fresh_plant, None, replay)
    assert result["passed"] is True and result["value"].value == 0
