"""Splitter mass division, unchanged stream states and limits."""

import pytest

import gemini as gm
from gemini.modules import energy_balance, mass_balance
from gemini.modules.piping import Splitter
from gemini.types import WATER, Stream
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises

FEED = Stream(
    m_dot=gm.units.Quantity(10, "kg/s"),
    T=gm.units.Quantity(353.15, "K"),
    p=gm.units.Quantity(5e5, "Pa"),
    fluid=WATER,
)


def test_split_divides_mass_and_keeps_the_state():
    """The second branch takes the split fraction; both keep T, p and fluid."""
    result = Splitter()(fluid_in=FEED, split_fraction=0.25)
    first, second = result.outlets.branch1_out, result.outlets.branch2_out
    assert (first.m_dot, second.m_dot) == (7.5, 2.5)
    for branch in (first, second):
        assert (branch.T, branch.p, branch.fluid) == (FEED.T, FEED.p, WATER)
    assert mass_balance(Splitter(), result)["residual"] == 0
    assert energy_balance(Splitter(), result)["relative_residual"] < 1e-12


def test_limits_of_the_split():
    """Fractions 0 and 1 send everything to one branch; zero feed gives two stopped branches."""
    assert Splitter()(fluid_in=FEED, split_fraction=0).outlets.branch2_out.m_dot == 0
    assert Splitter()(fluid_in=FEED, split_fraction=1).outlets.branch1_out.m_dot == 0
    stopped = Splitter()(fluid_in=FEED.with_(m_dot=0), split_fraction=0.5).outlets
    assert stopped.branch1_out.m_dot == stopped.branch2_out.m_dot == 0
    odd = Splitter()(fluid_in=FEED.with_(m_dot=0.7), split_fraction=0.3)
    assert mass_balance(Splitter(), odd)["relative_residual"] < 1e-15


def test_invalid_inputs_raise():
    """Reverse feed, a fraction outside [0, 1] and a missing command are rejected."""
    with pytest.raises(gm.errors.PhysicsError, match="splitter: fluid_in.m_dot = -1"):
        Splitter()(fluid_in=FEED.with_(m_dot=-1), split_fraction=0.5)
    with pytest.raises(gm.errors.ValidationError):
        Splitter()(fluid_in=FEED, split_fraction=1.2)
    with raises(gm.errors.ValidationError, "missing_value"):
        Splitter()(fluid_in=FEED)


def test_splitter_matches_traced():
    """Split fractions from zero to one and a stopped feed trace correctly."""
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m_dot, "kg/s"),
                T=gm.units.Quantity(353.15, "K"),
                p=gm.units.Quantity(5e5, "Pa"),
                fluid=WATER,
            ),
            split_fraction=fraction,
        )
        for m_dot, fraction in [(10, 0.25), (10, 0), (10, 1), (0, 0.5), (0.7, 0.3)]
    ]
    assert_module_matches(Splitter(), rows)
