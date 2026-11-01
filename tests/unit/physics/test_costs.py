"""Costs that scale with a size."""

from gemini.physics import costs
from tests.fixtures.equivalence import assert_function_matches


def test_scaled_is_the_unit_cost_times_the_size():
    """0.67 per W for 10 MW, and 2 % a year of 1000."""
    assert costs.scaled(0.67, 1e7) == 0.67e7
    assert costs.scaled(0.02, 1000.0) == 20.0
    assert_function_matches(costs.scaled, [(0.67, 1e7), (0.0, 5.0)])
