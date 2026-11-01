"""Mass conservation for InjectionPump."""

import pytest

import gemini as gm
from gemini.errors import PhysicsError, ValidationError
from gemini.modules.pumps import InjectionPump
from gemini.physics import pumps
from gemini.types.flows import Stream
from gemini.units import Quantity
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises

CURVES = {
    "stage_count": 10,
    "head_coefficients": [100, -0.01, 0, 0, 0, 0],
    "power_coefficients": [1, 0.001, 0, 0, 0, 0],
}


def test_equipment_forward():
    """Equipment preserves mass and valid pressure/temperature."""
    c = InjectionPump().set_params("", {"stage_count": 10, "pump_type": "A", "efficiency": 0.65})
    result = c(fluid_in=Stream(m_dot=1, T=300, p=1e6), pressure_setpoint=2e6)
    assert sum(s.m_dot for s in result.outlets.values() if isinstance(s, Stream)) == 1
    assert result.outlets["fluid_out"].T == 300
    assert result.outlets["fluid_out"].p >= 0


def _rows():
    return [
        dict(fluid_in=Stream(m_dot=m_dot, T=300, p=p), pressure_setpoint=setpoint, frequency=60)
        for m_dot, p, setpoint in [(1, 1e6, 2e6), (5, 2e6, 6e6), (0.5, 1e6, 1e6)]
    ]


def test_setpoint_matches_traced():
    """The setpoint branch traces and equals one call per row."""
    module = InjectionPump().set_params("", {"efficiency": 0.65})
    assert_module_matches(module, _rows())


def test_curves_match_traced():
    """The head and power curve branch traces and equals one call per row."""
    module = InjectionPump().set_params("", CURVES)
    rows = [{k: v for k, v in row.items() if k != "pressure_setpoint"} for row in _rows()]
    assert_module_matches(module, rows)


def test_setpoint_below_suction_raises():
    """A setpoint below the suction pressure is a physics range error."""
    with pytest.raises(PhysicsError, match="below suction pressure"):
        InjectionPump()(fluid_in=Stream(m_dot=1, T=300, p=2e6), pressure_setpoint=1e6)


def test_a_stopped_pump_lets_the_pressure_through():
    """Without flow a setpoint below the suction is no error: the pump adds no pressure."""
    pump = InjectionPump().set_params("", {"efficiency": 0.65})
    result = pump(fluid_in=Stream(m_dot=0.0, T=320.0, p=100e5), pressure_setpoint=30e5)
    assert result.outlets["fluid_out"].p == 100e5
    assert result.outputs["head"] == 0.0


def test_a_pump_on_its_setpoint_needs_an_efficiency():
    """The efficiency has no default: the power of a setpoint needs one."""
    with raises(ValidationError, "missing_value"):
        InjectionPump()(fluid_in=Stream(m_dot=1, T=300, p=1e6), pressure_setpoint=2e6)


def test_a_pump_on_its_curves_needs_no_efficiency():
    """Head and power curves give the power without it."""
    pump = InjectionPump().set_params("", CURVES)
    assert pump(fluid_in=Stream(m_dot=1, T=300, p=1e6)).outputs["power"] > 0


def _finance(**capex):
    """Return the finance of a case that prices what ``capex`` names, with a 2 %/yr fixed opex."""
    return gm.case.Finance(
        capex=gm.case.Capex(**capex),
        opex=gm.case.Opex(fixed={"injection_pump": Quantity(2, "%/yr")}),
    )


def _sized_pump():
    """Return a pump of 0.1 m3/s and 20 bar at an efficiency of 0.5: 400 kW of shaft power."""
    return InjectionPump().set_params(
        "",
        {
            "efficiency": 0.5,
            "nominal_flow": Quantity(0.1, "m3/s"),
            "nominal_head": Quantity(20, "bar"),
        },
    )


def test_the_capex_is_the_price_per_watt_of_the_shaft_power_at_the_nominal_flow():
    """The shaft power is the hydraulic power over the efficiency; the opex is a share of it."""
    finance = _finance(injection_pump=Quantity(0.5, "currency/W"))
    pump = _sized_pump()
    assert pump.equipment_kind == "injection_pump"
    assert pump.capex(finance) == pytest.approx(0.5 * 400000.0)
    assert pump.fixed_opex(finance) == pytest.approx(0.02 * 0.5 * 400000.0)


def test_the_capex_from_curves_is_the_power_curve_at_the_nominal_flow():
    """A pump with a power curve is sized by it, not by the efficiency."""
    pump = InjectionPump().set_params("", CURVES | {"nominal_flow": Quantity(0.1, "m3/s")})
    power = pumps.power(0.1, 60.0, 10, CURVES["power_coefficients"])
    assert pump.capex(_finance(injection_pump=Quantity(1, "currency/W"))) == pytest.approx(power)


def test_a_pump_without_a_price_raises_naming_the_path():
    """The case has no ``injection_pump`` capex: nothing is estimated."""
    finance = _finance(degasser=Quantity(1000.0, "currency"))
    with raises(ValidationError, "missing_assumption", "assumptions.finance.capex.injection_pump"):
        _sized_pump().capex(finance)


def test_a_pump_without_a_nominal_flow_raises_naming_it():
    """The design flow has no default."""
    pump = InjectionPump().set_params("", {"efficiency": 0.5})
    with raises(ValidationError, "missing_value", "nominal_flow"):
        pump.capex(_finance(injection_pump=Quantity(0.5, "currency/W")))


def test_a_pump_that_adds_no_head_costs_nothing():
    """A zero nominal head is no shaft power, so no capex and no fixed opex."""
    pump = InjectionPump().set_params(
        "",
        {
            "efficiency": 0.5,
            "nominal_flow": Quantity(0.1, "m3/s"),
            "nominal_head": Quantity(0, "bar"),
        },
    )
    finance = _finance(injection_pump=Quantity(0.5, "currency/W"))
    assert pump.capex(finance) == 0.0 and pump.fixed_opex(finance) == 0.0
