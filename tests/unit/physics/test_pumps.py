"""TNO pump polynomials on the historical US basis."""

import pytest

from gemini.physics import pumps
from tests.fixtures.equivalence import assert_function_matches


def test_centrifugal_curve_and_parabolic_efficiency():
    """At half speed the head curve drops to c0/4 at zero flow; efficiency peaks at the bep."""
    assert pumps.centrifugal_head(0.0, 0.5, [100.0, 0.0, -1.0]) == pytest.approx(25)
    assert pumps.centrifugal_head(2.0, 1.0, [100.0, -3.0, -1.0]) == pytest.approx(90)
    load = pumps.best_efficiency_ratio(0.03, 0.5, 0.06)
    assert load == pytest.approx(1)
    assert pumps.parabolic_efficiency(0.8, load) == pytest.approx(0.8)
    assert pumps.parabolic_efficiency(0.8, 0.5) == pytest.approx(0.6)


def test_gas_volume_fraction_of_the_intake_follows_the_densities():
    """No gas gives zero; 5 % gas by mass of 1 kg/m3 gas in 1000 kg/m3 liquid is nearly all gas."""
    assert pumps.intake_gas_volume_fraction(1000.0, 1.0, 0.0) == 0
    assert pumps.intake_gas_volume_fraction(1000.0, 1.0, 0.05) == pytest.approx(
        (0.05 / 1.0) / (0.05 / 1.0 + 0.95 / 1000.0)
    )
    assert pumps.intake_gas_volume_fraction(1000.0, 0.0, 0.01) == 1


def test_gas_volume_fraction_matches_traced():
    """The traced function equals one call per row, including a gas of no density."""
    rows = [(1000.0, 1.0, 0.0), (1030.0, 20.0, 0.001), (1030.0, 0.5, 0.01), (1000.0, 0.0, 0.01)]
    assert_function_matches(pumps.intake_gas_volume_fraction, rows)
