"""The helpers of a gas burner: the fuel of a stream and its split."""

import pytest

from gemini.modules.heating import _burner
from gemini.physics import gas
from gemini.types.flows import Stream
from gemini.types.fluid import Fluid
from gemini.units import Quantity

FLUID = Fluid(kind="gas", gas_composition={"CH4": 1.0})
FUEL = Stream(m_dot=Quantity(0.1, "kg/s"), T=Quantity(300, "K"), p=Quantity(2e5, "Pa"), fluid=FLUID)


def test_the_fuel_of_a_stream_is_its_mass_times_its_heating_value():
    """A stream without a composition holds no fuel."""
    assert _burner.available_fuel(FUEL) == pytest.approx(0.1 * FLUID.heating_value())
    assert (
        _burner.available_fuel(
            Stream(m_dot=Quantity(0.1, "kg/s"), T=Quantity(300, "K"), p=Quantity(2e5, "Pa"))
        )
        == 0
    )


def test_the_mark_says_whether_the_grid_may_be_drawn():
    """A mark is the grid composition on the fluid."""
    assert not _burner.has_grid(FUEL)
    assert _burner.has_grid(FUEL.with_(fluid=FLUID.with_grid(gas.GRID_COMPOSITION)))


def test_the_split_and_the_gas_left():
    """A need below the stream burns part of it and leaves the rest."""
    need = _burner.available_fuel(FUEL) / 4
    coproduced, purchased, burnt = _burner.fuel_split(need, FUEL)
    assert coproduced == pytest.approx(need) and purchased == 0
    assert burnt == pytest.approx(0.025)
    assert _burner.burned_stream(need, FUEL).m_dot == pytest.approx(0.025)
    assert _burner.flue_stream(need, FUEL).m_dot == pytest.approx(need * FLUID.emission_factor())
