"""The flare burns its inlet and reports what its composition gives."""

import pytest

import gemini as gm
from gemini.errors import PhysicsError
from gemini.modules import Flare, energy_balance
from gemini.physics import combustion, gas
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches

COMPOSITION = {"CH4": 0.8, "CO2": 0.2}
FLUID = gm.Fluid(kind="gas", gas_composition=COMPOSITION)


def stream(flow):
    """Return a gas stream of ``flow`` [kg/s]."""
    return gm.Stream(m_dot=flow, T=330, p=2e5, fluid=FLUID)


def test_emissions_come_from_the_composition():
    """Carried CO2 plus 98 % of the formed CO2, and 2 % of the methane unburnt."""
    result = with_values(Flare())(gas_in=stream(0.1))
    out, flue = result.outputs, result.outlets.flue_out
    efficiency = combustion.FLARE_EFFICIENCY
    carried, formed = gas.mass_fraction(COMPOSITION, "CO2"), gas.combustion_co2(COMPOSITION)
    composition = flue.fluid.gas_composition
    co2 = gas.species_flow(flue.m_dot, composition, "CO2")
    assert co2 == pytest.approx(0.1 * (carried + efficiency * formed))
    assert gas.species_flow(flue.m_dot, composition, "CH4") == pytest.approx(
        0.1 * gas.mass_fraction(COMPOSITION, "CH4") * (1 - efficiency)
    )
    assert out.burned_mass_flow == 0.1


def test_a_stream_without_a_composition_emits_nothing():
    """Nothing is known about the gas, so nothing is reported."""
    assert (
        with_values(Flare())(gas_in=gm.Stream(m_dot=0.1, T=330, p=2e5)).outlets.flue_out.m_dot == 0
    )


def test_reverse_flow_is_refused():
    """A flare only burns."""
    with pytest.raises(PhysicsError):
        with_values(Flare())(gas_in=stream(-0.1))


def test_traced_call_matches_one_call_per_row():
    """No gas and some gas equal one call per row."""
    assert_module_matches(
        with_values(Flare()), [dict(gas_in=stream(flow)) for flow in (0.0, 0.1, 1.0)]
    )


def test_the_heat_of_burning_leaves_through_a_loss_port():
    """The chemical power burned is ``fuel``; it leaves through ``loss_out``; the audit closes."""
    fluid = gm.Fluid(kind="gas", gas_composition={"CH4": 1.0})
    flare = with_values(Flare())
    result = flare(gas_in=gm.Stream(m_dot=0.1, T=300, p=2e5, fluid=fluid))
    burned = 0.1 * fluid.heating_value() * flare.combustion_efficiency
    assert result.outlets.loss_out == pytest.approx(burned)
    assert result.outputs.fuel == pytest.approx(burned)
    assert energy_balance(flare, result)["relative_residual"] < 1e-12
