"""Flash separator split, IF97 enthalpy closure, subcooled inlet and domain limits."""

import pytest

import gemini as gm
from gemini.modules import mass_balance
from gemini.modules.power import Separator, _physics
from gemini.types import STEAM, Stream
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.reading import reading

GEOFLUID = Stream(
    m_dot=gm.units.Quantity(100, "kg/s"),
    T=gm.units.Quantity(523.15, "K"),
    p=gm.units.Quantity(40e5, "Pa"),
)
"""Liquid at 250 degC and 40 bar, a typical liquid-dominated wellhead feed."""


def test_flash_split_matches_steam_tables():
    """250 degC liquid flashed to 6 bar: x = (1085.8 - 670.4) / 2085.9 = 0.199 (steam tables)."""
    result = Separator()(fluid_in=GEOFLUID, pressure_setpoint={"value": 6, "unit": "bar"})
    out, liquid, gas = reading(result), result.outlets.liquid_out, result.outlets.gas_out
    assert out.steam_fraction == pytest.approx((1085.8 - 670.4) / 2085.9, abs=2e-4)
    assert out.saturation_temperature == pytest.approx(431.98, abs=0.01)
    assert out.steam_mass_flow == gas.m_dot == pytest.approx(100 * out.steam_fraction)
    assert gas.fluid == STEAM and liquid.fluid == GEOFLUID.fluid
    assert liquid.T == gas.T == out.saturation_temperature
    assert liquid.p == gas.p == 6e5
    assert mass_balance(Separator(), result)["residual"] == 0


def test_closed_in_if97_enthalpies():
    """Closure: m h_in = m_gas h_g + m_liquid h_f; the cp*T audit cannot show latent heat."""
    result = Separator()(fluid_in=GEOFLUID, pressure_setpoint=6e5)
    saturation = _physics.saturation_properties(6e5)
    incoming = GEOFLUID.m_dot * _physics.liquid_enthalpy(GEOFLUID.p, GEOFLUID.T)
    outgoing = (
        result.outlets.gas_out.m_dot * saturation.vapour_enthalpy
        + result.outlets.liquid_out.m_dot * saturation.liquid_enthalpy
    )
    assert outgoing == pytest.approx(incoming, rel=1e-12)


def test_inlet_below_its_saturation_pressure_uses_the_liquid_enthalpy():
    """A wellhead stream already below saturation is the liquid at its temperature."""
    flashing = GEOFLUID.with_(p=8e5)
    result = Separator()(fluid_in=flashing, pressure_setpoint=6e5)
    enthalpy = _physics.liquid_enthalpy(_physics.saturation_pressure(523.15), 523.15)
    assert result.outputs.steam_fraction == pytest.approx(_physics.flash_fraction(enthalpy, 6e5))


def test_subcooled_and_zero_flow():
    """A subcooled inlet passes as liquid at its temperature; zero flow splits nothing."""
    subcooled = Stream(
        m_dot=gm.units.Quantity(50, "kg/s"),
        T=gm.units.Quantity(393.15, "K"),
        p=gm.units.Quantity(10e5, "Pa"),
    )
    result = Separator()(fluid_in=subcooled, pressure_setpoint=6e5)
    assert result.outputs.steam_fraction == 0 and result.outlets.gas_out.m_dot == 0
    assert result.outlets.liquid_out.T == 393.15 and result.outlets.liquid_out.m_dot == 50
    stopped = Separator()(fluid_in=GEOFLUID.with_(m_dot=0), pressure_setpoint=6e5)
    assert reading(stopped).steam_mass_flow == 0 and stopped.outlets.liquid_out.m_dot == 0
    assert stopped.outputs.steam_fraction > 0


def test_invalid_inlets_and_setpoints_raise():
    """Reverse flow, a steam inlet, a setpoint above the inlet and a supercritical feed."""
    separator = Separator()
    cases = [
        (GEOFLUID.with_(m_dot=-1), 6e5),
        (GEOFLUID.with_(fluid=STEAM), 6e5),
        (GEOFLUID, 50e5),
        (GEOFLUID.with_(T=650, p=250e5), 6e5),
    ]
    for inlet, setpoint in cases:
        with pytest.raises(gm.errors.PhysicsError):
            separator(fluid_in=inlet, pressure_setpoint=setpoint)
    with pytest.raises(gm.errors.PhysicsError, match="separator: pressure_setpoint"):
        separator(fluid_in=GEOFLUID, pressure_setpoint=50e5)


def test_traced_call_matches_one_call_per_row():
    """Flashing and subcooled rows at several setpoints trace and equal one call per row."""
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m_dot, "kg/s"),
                T=gm.units.Quantity(T, "K"),
                p=gm.units.Quantity(p, "Pa"),
            ),
            pressure_setpoint=setpoint,
        )
        for m_dot, T, p, setpoint in [
            (100.0, 523.15, 40e5, 6e5),
            (50.0, 523.15, 8e5, 6e5),
            (80.0, 400.0, 20e5, 5e5),
            (0.0, 500.0, 30e5, 2e5),
        ]
    ]
    assert_module_matches(Separator(), rows)
