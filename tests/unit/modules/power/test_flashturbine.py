"""Flash turbine power, steam-enthalpy closure, condensate and a single-flash plant."""

import pytest

import gemini as gm
from gemini.errors import PhysicsError
from gemini.modules import Module, mass_balance
from gemini.modules.declarations import Inlet, Outlet
from gemini.modules.power import FlashTurbine, Separator, _physics
from gemini.types import STEAM, WATER, Stream
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.reading import reading

STEAM_FEED = Stream(m_dot=20, T=431.98, p=6e5, fluid=STEAM)


def turbine():
    """Return a turbine exhausting to a 0.1 bar condenser through a 98 % generator."""
    return with_values(FlashTurbine()).set_params(
        "", {"condenser_pressure": {"value": 0.1, "unit": "bar"}, "generator_efficiency": 0.98}
    )


def test_power_matches_dipippo_hand_calculation():
    """6 bar to 0.1 bar: x_s = 0.8146, A = 0.425 * 615 kJ/kg, x_out = 0.868, w = 488 kJ/kg.

    Steam-table values: h_g(6 bar) = 2756.1, h_f(0.1 bar) = 191.8, h_fg = 2392.8 kJ/kg.
    """
    out = reading(turbine()(fluid_in=STEAM_FEED))
    assert out.exhaust_quality == pytest.approx(0.868, abs=1e-3)
    assert out.gross_power / 20 == pytest.approx(2756.1e3 - (191.8e3 + 0.8677 * 2392.8e3), rel=2e-3)
    assert out.electricity_generated == pytest.approx(0.98 * out.gross_power, rel=1e-12)


def test_closed_in_steam_enthalpies_and_condensate():
    """Closure: m h_g(p_in) = electricity + heat_loss + m h_f(p_cond); condensate is saturated."""
    module = turbine()
    result = module(fluid_in=STEAM_FEED)
    out, outlet = reading(result), result.outlets.fluid_out
    condenser = _physics.saturation_properties(1e4)
    incoming = 20 * _physics.saturation_properties(6e5).vapour_enthalpy
    outgoing = out.electricity_generated + out.heat_loss + 20 * condenser.liquid_enthalpy
    assert outgoing == pytest.approx(incoming, rel=1e-12)
    assert out.heat_loss == pytest.approx(out.condenser_duty + 0.02 * out.gross_power)
    assert outlet.fluid == WATER and outlet.p == 1e4 and outlet.T == condenser.temperature
    assert mass_balance(module, result)["residual"] == 0


def test_zero_flow_and_invalid_inlets():
    """Zero steam gives zero power; liquid, reverse flow or a low inlet pressure raise."""
    out = reading(turbine()(fluid_in=STEAM_FEED.with_(m_dot=0)))
    assert out.gross_power == out.electricity_generated == out.heat_loss == 0
    for inlet in (
        STEAM_FEED.with_(fluid=WATER),
        STEAM_FEED.with_(m_dot=-1),
        STEAM_FEED.with_(p=1e4),
    ):
        with pytest.raises(gm.errors.PhysicsError):
            turbine()(fluid_in=inlet)


class SingleFlash(Module):
    """Separator feeding a condensing turbine."""

    def __init__(self):
        """Declare the test plant."""
        super().__init__()

        # Modules
        self.separator = Separator()
        self.turbine = turbine()

        # Inlets
        self.geofluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)
        self.condensate_out = Outlet(Stream)

    def forward(self, inlets):
        """Separate, then expand the steam."""

        # Modules
        separated = self.separator(inlets.geofluid_in, pressure_setpoint=6e5)
        expanded = self.turbine(separated.outlets.gas_out)

        # Outlets
        fluid_out = separated.outlets.liquid_out
        condensate_out = expanded.outlets.fluid_out

        outlets = dict(fluid_out=fluid_out, condensate_out=condensate_out)
        return outlets


def test_single_flash_plant_closure():
    """A 250 degC, 100 kg/s feed yields about 9.5 MW; the plant closes in IF97 enthalpies."""
    plant = SingleFlash()
    feed = Stream(m_dot=100, T=523.15, p=40e5)
    result = plant(geofluid_in=feed)
    brine, condensate = result.outlets.fluid_out, result.outlets.condensate_out
    net_power = result.children["turbine"].outlets.power_out
    assert net_power == pytest.approx(9.53e6, rel=2e-3)
    assert brine.m_dot + condensate.m_dot == pytest.approx(100, rel=1e-15)
    incoming = 100 * _physics.liquid_enthalpy(feed.p, feed.T)
    outgoing = (
        net_power
        + reading(result.children["turbine"]).heat_loss
        + brine.m_dot * _physics.saturation_properties(6e5).liquid_enthalpy
        + condensate.m_dot * _physics.saturation_properties(1e4).liquid_enthalpy
    )
    assert outgoing == pytest.approx(incoming, rel=1e-12)


def test_traced_call_matches_one_call_per_row():
    """Several flows and inlet pressures trace and equal one call per row."""
    rows = [
        dict(fluid_in=Stream(m_dot=m_dot, T=420.0, p=p, fluid=STEAM))
        for m_dot, p in [(20.0, 6e5), (0.0, 6e5), (5.0, 2e6), (12.0, 2e5)]
    ]
    assert_module_matches(turbine(), rows)


def test_a_bad_expansion_rejects_the_call_without_outputs_too():
    """``forward`` uses no number of the expansion, but its error still fails the call."""
    module = turbine().set_params("", {"condenser_pressure": {"value": 7, "unit": "bar"}})
    with pytest.raises(PhysicsError) as with_outputs:
        module(fluid_in=STEAM_FEED)
    with gm.modules.no_outputs():
        with pytest.raises(PhysicsError) as without_outputs:
            module(fluid_in=STEAM_FEED)
    assert str(without_outputs.value) == str(with_outputs.value)
