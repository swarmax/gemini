"""Blowdown bleed split, conservation and limits."""

import pytest

import gemini as gm
from gemini.modules._utils.balance import energy_balance, mass_balance
from gemini.modules.treatment import Blowdown
from gemini.types.flows import Stream
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

FEED = Stream(
    m_dot=gm.units.Quantity(8, "kg/s"),
    T=gm.units.Quantity(330, "K"),
    p=gm.units.Quantity(3e5, "Pa"),
)


def test_bleed_split_conserves_mass_and_energy():
    """The commanded share drains at the feed state; the rest is retained."""
    blowdown = Blowdown()
    result = blowdown(fluid_in=FEED, blowdown_fraction=0.25)
    retained, drained = result.outlets.fluid_out, result.outlets.waste_out
    assert drained == FEED.with_(m_dot=2) and retained == FEED.with_(m_dot=6)
    assert reading(result).blowdown_mass_flow == 2
    assert "modelled" not in result.outputs and "heat_loss" not in reading(result)
    assert mass_balance(blowdown, result)["residual"] == 0
    assert energy_balance(blowdown, result)["relative_residual"] < 1e-12


def test_limits():
    """Closed and fully open bleeds, zero flow, reverse flow and a missing command."""
    blowdown = Blowdown()
    assert blowdown(fluid_in=FEED, blowdown_fraction=0).outlets.waste_out.m_dot == 0
    assert blowdown(fluid_in=FEED, blowdown_fraction=1).outlets.fluid_out.m_dot == 0
    stopped = blowdown(fluid_in=FEED.with_(m_dot=0), blowdown_fraction=0.1)
    assert reading(stopped).blowdown_mass_flow == 0
    with pytest.raises(gm.errors.PhysicsError, match="fluid_in.m_dot"):
        blowdown(fluid_in=FEED.with_(m_dot=-1), blowdown_fraction=0.1)
    with raises(gm.errors.ValidationError, "missing_value"):
        blowdown(fluid_in=FEED)


def test_blowdown_matches_traced():
    """The split traces and equals one call per row."""
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m_dot, "kg/s"),
                T=gm.units.Quantity(310, "K"),
                p=gm.units.Quantity(2e5, "Pa"),
            ),
            blowdown_fraction=fraction,
        )
        for m_dot, fraction in [(0, 0.1), (10, 0), (30, 0.05), (30, 1)]
    ]
    assert_module_matches(Blowdown(), rows)
