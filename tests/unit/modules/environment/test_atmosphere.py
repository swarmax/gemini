"""The air: the ambient conditions, what it offers and the emissions of the plant."""

import pytest

import gemini as gm
from gemini.errors import PhysicsError
from gemini.modules import Atmosphere
from gemini.physics import gas
from tests.fixtures.equivalence import assert_module_matches

FLUE = gm.Stream(
    m_dot=gm.units.Quantity(0.2, "kg/s"),
    T=gm.units.Quantity(330.0, "K"),
    p=gm.units.Quantity(1e5, "Pa"),
    fluid=gm.Fluid(kind="gas", gas_composition={"CO2": 1}),
)
RELEASED = gm.Stream(
    m_dot=gm.units.Quantity(0.1, "kg/s"),
    T=gm.units.Quantity(330.0, "K"),
    p=gm.units.Quantity(1e5, "Pa"),
    fluid=gm.Fluid(kind="gas", gas_composition={"CH4": 0.8, "CO2": 0.2}),
)


def atmosphere(**boundaries):
    """Return the air at 15 degC, or with the given boundaries."""
    air = Atmosphere()
    air.temperature = 288.15
    air._set_inputs(boundaries)
    return air


def test_the_air_is_offered_at_the_ambient_conditions_without_flow():
    """Every module that exchanges heat with the air reads the same stream."""
    offered = atmosphere()._offered()
    assert offered["air_out"].T == 288.15 and offered["air_out"].m_dot == 0
    assert offered["air_out"].p == pytest.approx(101325)


def test_a_wet_cooler_reads_the_wet_bulb():
    """``wet_air_out`` carries the wet bulb; without one it is the dry bulb."""
    assert atmosphere()._offered()["wet_air_out"].T == 288.15
    assert atmosphere(wet_bulb_temperature=280.0)._offered()["wet_air_out"].T == 280.0


def test_a_wet_bulb_above_the_dry_bulb_is_refused():
    """It is outside the model."""
    with pytest.raises(PhysicsError, match="wet_bulb_temperature = 300"):
        atmosphere(wet_bulb_temperature=300.0)._offered()


def test_the_emissions_come_from_what_arrives():
    """CO2 and methane follow the composition of each released gas."""
    out = atmosphere()(gas_in=[FLUE, RELEASED]).outputs
    composition = RELEASED.fluid.gas_composition
    assert out.co2_emission == pytest.approx(0.2 + 0.1 * gas.mass_fraction(composition, "CO2"))
    assert out.methane_emission == pytest.approx(0.1 * gas.mass_fraction(composition, "CH4"))


def test_nothing_released_emits_nothing():
    """An empty port is valid."""
    assert atmosphere()().outputs.co2_emission == 0


def test_traced_call_matches_one_call_per_row():
    """A leaf without a released gas traces."""
    assert_module_matches(atmosphere(), [{}, {}])
