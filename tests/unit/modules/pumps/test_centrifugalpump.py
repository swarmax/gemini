"""Centrifugal pump curve, affinity laws, loss heating and limits."""

import pytest

from gemini.errors import PhysicsError, ValidationError
from gemini.modules._utils.balance import energy_balance, mass_balance
from gemini.modules.pumps import CentrifugalPump
from gemini.types.flows import Stream
from gemini.units import Quantity
from tests.fixtures import si
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

CP = 4217.4
PARAMS = dict(
    head_coefficients=[6e5, 0, -4e7],
    rated_frequency=50,
    best_efficiency=0.8,
    best_efficiency_flow=0.05,
    motor_efficiency=0.95,
)


def pump():
    """Return a pump with a 6 bar shutoff head and its best efficiency at 180 m3/h."""
    return si.set_params(CentrifugalPump(), "", PARAMS)


def test_best_efficiency_point_by_hand():
    """At the rated speed and the best-efficiency flow every output follows by hand."""
    result = pump()(
        fluid_in=Stream(m_dot=Quantity(50, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa")),
        frequency=50,
    )
    out = reading(result)
    assert out.flow == pytest.approx(0.05)
    assert out.head == pytest.approx(6e5 - 4e7 * 0.05**2)
    assert out.efficiency == pytest.approx(0.8)
    assert out.hydraulic_power == pytest.approx(0.05 * 5e5)
    assert out.shaft_power == pytest.approx(25000 / 0.8)
    assert out.electricity == pytest.approx(31250 / 0.95)
    assert out.heat_loss == pytest.approx(31250 / 0.95 - 31250)
    assert out.fluid_out_T == pytest.approx(330 + 6250 / (50 * CP))
    discharge = result.outlets.fluid_out
    assert discharge.p == pytest.approx(8e5) and discharge.m_dot == 50
    assert discharge.T == out.fluid_out_T


def test_part_load_efficiency_curve():
    """Half the best-efficiency flow gives three quarters of the best efficiency."""
    out = reading(
        pump()(
            fluid_in=Stream(
                m_dot=Quantity(25, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa")
            ),
            frequency=50,
        )
    )
    assert out.efficiency == pytest.approx(0.8 * 0.5 * 1.5)
    assert out.shaft_power == pytest.approx(0.025 * (6e5 - 4e7 * 0.025**2) / 0.6)


def test_affinity_laws_scale_flow_head_and_power():
    """At speed ratio s, flow s*Q gives s^2 times the head and s^3 times the shaft power."""
    rated = reading(
        pump()(
            fluid_in=Stream(
                m_dot=Quantity(40, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa")
            ),
            frequency=50,
        )
    )
    slow = reading(
        pump()(
            fluid_in=Stream(
                m_dot=Quantity(32, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa")
            ),
            frequency=40,
        )
    )
    assert slow.head == pytest.approx(0.8**2 * rated.head)
    assert slow.shaft_power == pytest.approx(0.8**3 * rated.shaft_power)
    assert slow.efficiency == pytest.approx(rated.efficiency)


def test_first_law_closure_with_flow_work():
    """Electricity becomes sensible heat, flow work and motor heat loss; mass is conserved."""
    machine = pump()
    suction = Stream(m_dot=Quantity(45, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa"))
    result = machine(fluid_in=suction, frequency=47)
    out, discharge = reading(result), result.outlets.fluid_out
    sensible = suction.m_dot * CP * (discharge.T - suction.T)
    flow_work = out.flow * (discharge.p - suction.p)
    assert out.electricity == pytest.approx(sensible + flow_work + out.heat_loss, rel=1e-12)
    assert mass_balance(machine, result)["residual"] == 0
    balance = energy_balance(machine, result)
    assert balance["residual"] == pytest.approx(out.hydraulic_power, rel=1e-9)
    assert balance["unresolved_power"] == 0


def test_zero_flow_is_a_stopped_pump():
    """Zero mass flow raises no pressure and draws no power."""
    suction = Stream(m_dot=Quantity(0, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa"))
    result = pump()(fluid_in=suction, frequency=50)
    assert result.outlets.fluid_out == suction
    assert all(result.outputs[name] == 0 for name in ("head", "shaft_power"))
    assert result.inlets.power_in == 0
    assert reading(result).fluid_out_T == 330


def test_off_curve_and_reverse_flow_raise():
    """Run-out beyond twice the best-efficiency flow, negative head and reverse flow raise."""
    with pytest.raises(PhysicsError, match="off its curve"):
        pump()(
            fluid_in=Stream(
                m_dot=Quantity(100, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa")
            ),
            frequency=50,
        )
    steep = pump().set_params("", {"head_coefficients": [6e5, 0, -4e8]})
    with pytest.raises(PhysicsError, match="head = -"):
        steep(
            fluid_in=Stream(
                m_dot=Quantity(60, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa")
            ),
            frequency=50,
        )
    with pytest.raises(PhysicsError, match="reverse flow"):
        pump()(
            fluid_in=Stream(
                m_dot=Quantity(-1, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa")
            ),
            frequency=50,
        )
    with raises(ValidationError, "missing_value"):
        CentrifugalPump()(
            fluid_in=Stream(m_dot=Quantity(1, "kg/s"), T=Quantity(330, "K"), p=Quantity(3e5, "Pa")),
            frequency=50,
        )


def test_traced_call_matches_one_call_per_row():
    """Stopped, part-load, rated and slow rows trace and equal one call per row."""
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=Quantity(m_dot, "kg/s"), T=Quantity(330.0, "K"), p=Quantity(3e5, "Pa")
            ),
            frequency=frequency,
        )
        for m_dot, frequency in [(0.0, 50.0), (25.0, 50.0), (50.0, 50.0), (32.0, 40.0)]
    ]
    assert_module_matches(pump(), rows)
