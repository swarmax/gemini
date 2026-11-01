"""Degasser free-gas separation, pressure loss and conservation."""

import pytest

from gemini.modules._utils.balance import energy_balance, mass_balance
from gemini.modules.treatment import Degasser
from gemini.types import Fluid
from gemini.types.flows import Stream
from gemini.units import Quantity
from tests.fixtures import si
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.reading import reading

GASSY = Fluid(gas_mass_fraction=0.02)


def test_equipment_forward():
    """Equipment preserves mass and valid pressure/temperature."""
    c = with_values(Degasser()).set_params(
        "", {"heat_transfer_coefficient": Quantity(100000, "W/K")}
    )
    result = c(
        fluid_in=Stream(m_dot=Quantity(1, "kg/s"), T=Quantity(300, "K"), p=Quantity(1e6, "Pa"))
    )
    assert sum(s.m_dot for s in result.outlets.values() if isinstance(s, Stream)) == 1
    assert result.outlets["liquid_out"].T == 300
    assert result.outlets["liquid_out"].p >= 0


def test_default_reproduces_the_liquid_only_model_for_any_fluid():
    """Zero default efficiency: no gas, liquid unchanged except the 0.149 bar loss."""
    inlet = Stream(
        m_dot=Quantity(40, "kg/s"), T=Quantity(350, "K"), p=Quantity(1e6, "Pa"), fluid=GASSY
    )
    result = with_values(Degasser())(fluid_in=inlet)
    assert result.outlets.liquid_out == inlet.with_(p=1e6 - 14900)
    assert result.outlets.gas_out == inlet.with_(p=1e6 - 14900, m_dot=0)
    assert reading(result).gas_mass_flow == 0
    assert result.outputs.pressure_drop == 14900


def test_separation_conserves_gas_mass_and_energy():
    """The separated share of the free gas leaves through gas; the rest stays in the liquid."""
    degasser = with_values(Degasser()).set_params(
        "", {"separation_efficiency": 0.75, "outlet_pressure": Quantity(2e5, "Pa")}
    )
    inlet = Stream(
        m_dot=Quantity(10, "kg/s"), T=Quantity(350, "K"), p=Quantity(1e6, "Pa"), fluid=GASSY
    )
    result = degasser(fluid_in=inlet)
    liquid, gas = result.outlets.liquid_out, result.outlets.gas_out
    assert gas.m_dot == pytest.approx(0.75 * 0.02 * 10)
    assert liquid.m_dot == pytest.approx(10 - 0.15)
    assert liquid.fluid.gas_mass_fraction == pytest.approx(0.005 / 0.985)
    assert liquid.m_dot * liquid.fluid.gas_mass_fraction == pytest.approx(0.25 * 0.02 * 10)
    assert liquid.p == gas.p == 2e5 and liquid.T == gas.T == 350
    assert reading(result).gas_mass_flow == gas.m_dot
    assert result.outputs.pressure_drop == 8e5
    assert mass_balance(degasser, result)["residual"] == 0
    assert energy_balance(degasser, result)["relative_residual"] < 1e-12


def test_full_efficiency_and_zero_flow():
    """Perfect separation leaves a gas-free liquid; zero flow separates nothing."""
    degasser = with_values(Degasser()).set_params("", {"separation_efficiency": 1})
    result = degasser(
        fluid_in=Stream(
            m_dot=Quantity(5, "kg/s"), T=Quantity(350, "K"), p=Quantity(1e6, "Pa"), fluid=GASSY
        )
    )
    assert result.outlets.liquid_out.fluid.gas_mass_fraction == 0
    assert result.outlets.gas_out.m_dot == pytest.approx(0.1)
    stopped = degasser(
        fluid_in=Stream(
            m_dot=Quantity(0, "kg/s"), T=Quantity(350, "K"), p=Quantity(1e6, "Pa"), fluid=GASSY
        )
    )
    assert stopped.outlets.gas_out.m_dot == 0 and stopped.outlets.liquid_out.m_dot == 0


def test_degasser_matches_traced():
    """The split traces for a gassy fluid, a gas-free fluid and a set vessel pressure."""
    for fluid in (GASSY, Fluid()):
        for settings in (dict(separation_efficiency=0.75), dict(outlet_pressure=2e5)):
            module = si.set_params(with_values(Degasser()), "", settings)
            rows = [
                dict(
                    fluid_in=Stream(
                        m_dot=Quantity(m_dot, "kg/s"),
                        T=Quantity(350, "K"),
                        p=Quantity(1e6, "Pa"),
                        fluid=fluid,
                    )
                )
                for m_dot in (0, 1, 10)
            ]
            assert_module_matches(module, rows)
