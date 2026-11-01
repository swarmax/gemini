"""Health-scoring relations."""

import pytest

from gemini.physics import diagnostics
from tests.fixtures.equivalence import assert_function_matches


def test_relative_drift_by_hand_and_with_a_zero_prediction():
    """A measurement 10 % above its prediction drifts 0.1; a zero prediction stays finite."""
    assert diagnostics.relative_drift(110.0, 100.0) == pytest.approx(0.1)
    assert diagnostics.relative_drift(90.0, -100.0) == pytest.approx(1.9)
    assert diagnostics.relative_drift(1.0, 0.0) == pytest.approx(1.0 / diagnostics.DRIFT_FLOOR)
    rows = [(110.0, 100.0), (90.0, -100.0), (1.0, 0.0), (0.0, 0.0)]
    assert_function_matches(diagnostics.relative_drift, rows)


def test_score_margin_and_limit_cross_every_branch():
    """The score clips to [0, 1]; the margin to [0, 1]; the limit is a strict comparison."""
    assert diagnostics.bounded_score(1.5) == 1
    assert diagnostics.bounded_score(-0.5) == 0
    assert diagnostics.bounded_score(0.4) == 0.4
    assert diagnostics.remaining_margin(0.25) == 0.75
    assert diagnostics.remaining_margin(2.0) == 0
    assert diagnostics.below_limit(0.8, 0.15)
    assert not diagnostics.below_limit(0.85, 0.15)
    ratios = [(1.5,), (-0.5,), (0.4,), (0.0,), (1.0,)]
    assert_function_matches(diagnostics.bounded_score, ratios)
    assert_function_matches(diagnostics.remaining_margin, ratios)
    assert_function_matches(diagnostics.below_limit, [(0.8, 0.15), (0.9, 0.15), (0.5, 0.5)])
