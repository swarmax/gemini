"""Deep coaxial downhole heat exchanger in a linear geothermal gradient."""

import math

import numpy as np
import pytest

import gemini as gm
from gemini.compiler.graph import run
from gemini.modules import energy_balance, mass_balance
from gemini.modules.subsurface import DownholeHeatExchanger
from gemini.types import Stream
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

INLET = Stream(
    m_dot=gm.units.Quantity(5, "kg/s"),
    T=gm.units.Quantity(303.15, "K"),
    p=gm.units.Quantity(3e5, "Pa"),
)
CP = 4217.4


def exchanger():
    """Return a 2.5 km exchanger after one year of operation."""
    return DownholeHeatExchanger().set_params(
        "",
        {
            "borehole_depth": {"value": 2500, "unit": "m"},
            "surface_temperature": {"value": 10, "unit": "degC"},
            "geothermal_gradient": {"value": 30, "unit": "K/km"},
            "ground_conductivity": gm.units.Quantity(2.5, "W/m/K"),
            "ground_diffusivity": gm.units.Quantity(1e-6, "m2/s"),
            "borehole_radius": gm.units.Quantity(0.1, "m"),
            "borehole_resistance": gm.units.Quantity(0.05, "m.K/W"),
            "operating_time": gm.units.Quantity(3.15e7, "s"),
        },
    )


def hand_outlet(m_dot, inlet_T):
    """Return Ramey's bottom-hole temperature [K] computed by hand."""
    function = math.log(2 * math.sqrt(1e-6 * 3.15e7) / 0.1) - 0.5772156649015329 / 2
    relaxation = m_dot * CP * (0.05 + function / (2 * math.pi * 2.5))
    rock = 283.15 + 0.03 * 2500
    decay = math.exp(-2500 / relaxation)
    return rock - 0.03 * relaxation + (inlet_T - 283.15 + 0.03 * relaxation) * decay


def test_outlet_follows_ramey_and_the_balance_closes():
    """The fluid leaves at Ramey's bottom-hole temperature; extracted heat closes the audit."""
    module = exchanger()
    assert module.geothermal_gradient == pytest.approx(0.03)
    result = module(fluid_in=INLET)
    out = reading(result)
    assert out.fluid_out_T == pytest.approx(hand_outlet(5, 303.15), rel=1e-12)
    assert out.heat_extraction_rate == pytest.approx(5 * CP * (out.fluid_out_T - 303.15))
    assert out.heat_absorbed == out.heat_extraction_rate > 0 and out.heat_loss == 0
    assert result.outlets.fluid_out.p == INLET.p and result.outlets.fluid_out.m_dot == 5
    assert energy_balance(module, result)["relative_residual"] < 1e-12
    assert mass_balance(module, result)["residual"] == 0


def test_flow_limits():
    """Slow flow approaches the bottom-hole rock temperature; zero flow passes unchanged."""
    module = exchanger()
    slow = reading(module(fluid_in=INLET.with_(m_dot=0.01))).fluid_out_T
    assert slow == pytest.approx(hand_outlet(0.01, 303.15)) and 0 < 283.15 + 75 - slow < 0.5
    still = module(fluid_in=INLET.with_(m_dot=0))
    assert still.outlets.fluid_out == INLET.with_(m_dot=0)
    assert reading(still).heat_extraction_rate == 0
    with pytest.raises(gm.errors.PhysicsError, match="fluid_in.m_dot = -1"):
        module(fluid_in=INLET.with_(m_dot=-1))


def test_hot_inlet_heats_the_rock():
    """An inlet hotter than the rock everywhere loses heat to it as heat_loss."""
    module = exchanger()
    result = module(fluid_in=INLET.with_(T=400))
    assert reading(result).heat_extraction_rate < 0 and reading(result).heat_absorbed == 0
    assert reading(result).heat_loss == -reading(result).heat_extraction_rate
    assert energy_balance(module, result)["relative_residual"] < 1e-12


def test_short_operating_time_is_bad_design_data():
    """Ramey's long-time function needs alpha t / r**2 >= 25."""
    module = exchanger().set_params("", {"operating_time": gm.units.Quantity(3600, "s")})
    with raises(gm.errors.ValidationError, "invalid_design", match="operating_time rejected"):
        module(fluid_in=INLET)


def test_exchanger_matches_traced():
    """Extraction, heat loss and zero flow equal one call per row."""
    rows = [
        dict(fluid_in=INLET.with_(m_dot=m_dot, T=T))
        for m_dot, T in [(5, 303.15), (0.01, 303.15), (0, 303.15), (20, 400), (1, 283.15)]
    ]
    assert_module_matches(exchanger(), rows)


def test_early_operating_time_is_not_evaluated_at_zero_flow():
    """A stopped exchanger needs no rock resistance, so a short operating time does not raise."""
    module = exchanger().set_params("", {"operating_time": gm.units.Quantity(3600, "s")})
    assert reading(module(fluid_in=INLET.with_(m_dot=0))).heat_extraction_rate == 0


def test_traced_early_operating_time_raises_only_for_flowing_rows():
    """In a traced call the configuration error belongs to the rows that flow."""
    module = exchanger().set_params("", {"operating_time": gm.units.Quantity(3600, "s")})
    stopped = Stream(
        m_dot=gm.units.Quantity(np.zeros(2), "kg/s"),
        T=gm.units.Quantity(np.full(2, 303.15), "K"),
        p=gm.units.Quantity(np.full(2, 3e5), "Pa"),
    )
    assert run(module, {"fluid_in": stopped}).outlets["loss_out"]["power"].tolist() == [0, 0]
    mixed = Stream(
        m_dot=gm.units.Quantity(np.array([0.0, 5.0]), "kg/s"),
        T=gm.units.Quantity(np.full(2, 303.15), "K"),
        p=gm.units.Quantity(np.full(2, 3e5), "Pa"),
    )
    with raises(gm.errors.ValidationError, "invalid_design", match="operating_time rejected"):
        run(module, {"fluid_in": mixed})
