"""The circuit rates and outlet temperatures that the two sorption machines share."""

from types import SimpleNamespace

import pytest

from gemini.errors import PhysicsError
from gemini.modules.cooling import _sorption
from gemini.types.flows import Stream


def test_rates_are_the_heat_capacity_rate_of_each_inlet():
    """Each port gets ``m_dot * cp_l`` of its stream."""
    inlets = {"hot": Stream(m_dot=2.0, T=350.0, p=1e5), "cold": Stream(m_dot=0.0, T=300.0, p=1e5)}
    rates = _sorption.rates("unit", inlets)
    assert rates["hot"] == inlets["hot"].heat_capacity_rate()
    assert rates["cold"] == 0.0


def test_rates_reject_negative_flow_naming_the_port():
    """A negative mass flow raises with the module path and the port."""
    inlets = {"hot": Stream(m_dot=-1.0, T=350.0, p=1e5)}
    message = r"^unit: hot.m_dot = -1.0 kg/s; expected >= 0 \(reverse flow is not modelled\)$"
    with pytest.raises(PhysicsError, match=message):
        _sorption.rates("unit", inlets)


def test_outlet_temperature_adds_the_duty_over_the_rate():
    """No duty keeps the inlet temperature; a duty shifts it by duty / rate."""
    stream = Stream(m_dot=1.0, T=350.0, p=1e5)
    assert _sorption.outlet_T(stream, 4000.0, 0.0) == 350.0
    assert _sorption.outlet_T(stream, 4000.0, -2000.0) == 349.5


def test_outlet_streams_keep_each_inlet_and_take_the_new_temperature():
    """The three streams copy their inlets and change only the temperature."""
    inlets = SimpleNamespace(
        generator_in=Stream(m_dot=1.0, T=360.0, p=1e5),
        chilled_in=Stream(m_dot=2.0, T=290.0, p=2e5),
        cooling_in=Stream(m_dot=3.0, T=300.0, p=3e5),
    )
    values = {"generator_out_T": 350.0, "chilled_out_T": 285.0, "cooling_out_T": 310.0}
    generator, chilled, cooling = _sorption.outlet_streams(inlets, values)
    assert (generator.T, chilled.T, cooling.T) == (350.0, 285.0, 310.0)
    assert (generator.m_dot, chilled.p, cooling.m_dot) == (1.0, 2e5, 3.0)
