"""Energy ledger of a run: synthetic columns and the example plant."""

import math

import gemini as gm
from gemini._utils.jsonable import to_plain
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.result_tables import make_results

PLANT = heating_plant()
ENERGY = {"power_in": [10.0, 5.0], "fuel": [1.0, 0.5], "heat_accumulation": [-3.0, 2.0]}


def test_energy_ledger_passes_and_reports_the_smallest_power():
    """Signed storage is not judged; the smallest of the other columns is 0.5 W."""
    result = gm.evaluate.energy_balance(PLANT, None, make_results({"leaf": ENERGY}))
    assert to_plain(result) == {
        "name": "energy_balance",
        "passed": True,
        "value": {"value": 0.5, "unit": "W"},
        "limit": {"value": 1e-9, "unit": "W"},
    }


def test_a_negative_nonnegative_output_fails():
    """A fuel power of -2 W breaks the sign convention."""
    result = gm.evaluate.energy_balance(PLANT, None, make_results({"leaf": {"fuel": [1.0, -2.0]}}))
    assert result["passed"] is False and result["value"].value == -2.0


def test_noise_below_the_tolerance_and_missing_values_are_accepted():
    """-1e-12 W is zero; a NaN tick is a skipped row, not a violation."""
    noisy = make_results({"leaf": {"fuel": [-1e-12, math.nan, 4.0]}})
    assert gm.evaluate.energy_balance(PLANT, None, noisy)["passed"] is True


def test_an_infinite_power_fails():
    """A divergent value is a failure even though it is not negative."""
    result = gm.evaluate.energy_balance(
        PLANT, None, make_results({"leaf": {"fuel": [1.0, math.inf]}})
    )
    assert result["passed"] is False


def test_nothing_to_judge_is_undecided_with_a_reason():
    """No energy column, or only missing values, gives ``passed`` None."""
    other = gm.evaluate.energy_balance(PLANT, None, make_results({"leaf": {"head": [1.0]}}))
    assert other["passed"] is None
    assert other["value"].reason == "results have no energy output column"
    empty = gm.evaluate.energy_balance(PLANT, None, make_results({"leaf": {"fuel": [math.nan]}}))
    assert empty["passed"] is None and empty["value"].reason == "every value is missing"


def test_the_example_plant_run_passes_the_energy_ledger(fresh_plant, fast_dataset):
    """A six-hour replay of the doublet heat plant has non-negative powers."""
    replay = gm.replay(fresh_plant, fast_dataset.window(None, "2024-07-01T06:00:00Z"))
    assert gm.evaluate.energy_balance(fresh_plant, None, replay)["passed"] is True
