"""The circulation pump: a fixed flow, a pressure rise and an efficiency."""

import pytest

import gemini as gm
from gemini.modules import CirculationPump
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches


def pump():
    """Return a pump of 4 kg/s and 0.5 bar on a circuit held at 3 bar."""
    return with_values(CirculationPump()).set_params(
        "",
        {
            "flow": gm.units.Quantity(4.0, "kg/s"),
            "pressure_rise": {"value": 0.5, "unit": "bar"},
            "loop_pressure": {"value": 3, "unit": "bar"},
        },
    )


def test_the_circuit_leaves_at_the_flow_and_the_pressure_of_the_pump():
    """The inlet gives only the temperature and the fluid."""
    result = pump()(
        fluid_in=gm.Stream(
            m_dot=gm.units.Quantity(1.0, "kg/s"),
            T=gm.units.Quantity(320.0, "K"),
            p=gm.units.Quantity(1e5, "Pa"),
        )
    )
    outlet = result.outlets.fluid_out
    assert (outlet.m_dot, outlet.T, outlet.p) == (4.0, 320.0, 3e5)


def test_the_electricity_is_the_hydraulic_power_over_the_efficiency():
    """All the electricity leaves as a loss, so the module closes and the water stays as it is."""
    result = pump()(
        fluid_in=gm.Stream(
            m_dot=gm.units.Quantity(1.0, "kg/s"),
            T=gm.units.Quantity(320.0, "K"),
            p=gm.units.Quantity(1e5, "Pa"),
        )
    )
    assert result.outputs.pumping_power == pytest.approx(4.0 / 1000 * 5e4, rel=1e-3)
    assert result.inlets.power_in == pytest.approx(result.outputs.pumping_power / 0.55)
    assert result.outlets.loss_out == result.inlets.power_in


def test_every_backend_agrees_with_a_direct_call():
    """Rows of any temperature give one answer on every path."""
    rows = [
        {
            "fluid_in": gm.Stream(
                m_dot=gm.units.Quantity(1.0, "kg/s"),
                T=gm.units.Quantity(temperature, "K"),
                p=gm.units.Quantity(1e5, "Pa"),
            )
        }
        for temperature in (300.0, 320.0, 340.0)
    ]
    assert_module_matches(pump(), rows)
