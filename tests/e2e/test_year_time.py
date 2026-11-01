"""The time of a daily year of the sample plant, eager: a large regression fails it."""

import time

import pytest

import gemini as gm
from tests.fixtures.sample_cases import SAMPLE_PLANT, sample_case, template_plant

pytestmark = pytest.mark.e2e

EAGER_YEAR_S = 0.34
"""Median of 5 eager runs after a warm-up of ``gm.simulate`` on the daily year (365 rows) of the
sample ``HeatingCoolingPlant``, on an Intel Core i5-8257U (8 threads), at a load average of 15."""
BUDGET_S = 3 * EAGER_YEAR_S
CALLS = 3


def _year(case):
    plant = template_plant(SAMPLE_PLANT)
    started = time.perf_counter()
    gm.simulate(plant, case, compile=False)
    return time.perf_counter() - started


def test_a_daily_year_of_the_sample_plant_runs_within_three_times_its_measured_time():
    """The best of three calls stays within ``BUDGET_S``, so a load spike does not fail it."""
    case = sample_case()
    _year(case)
    best = min(_year(case) for _ in range(CALLS))
    assert best < BUDGET_S, f"{best:.2f} s against {BUDGET_S:.2f} s"
