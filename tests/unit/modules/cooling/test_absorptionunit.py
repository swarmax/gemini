"""Absorption chiller and heat pump: characteristic equation, modes, limits and closure."""

import pytest

from gemini.errors import PhysicsError
from gemini.modules._utils.balance import energy_balance, mass_balance
from gemini.modules.cooling import AbsorptionUnit
from gemini.types.flows import Stream
from gemini.units import Quantity
from tests.fixtures import si
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.reading import reading

CP = 4217.4
GENERATOR = Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(361.15, "K"), p=Quantity(3e5, "Pa"))
CHILLED = Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(285.15, "K"), p=Quantity(3e5, "Pa"))
COOLING = Stream(m_dot=Quantity(25, "kg/s"), T=Quantity(303.15, "K"), p=Quantity(3e5, "Pa"))


def unit(mode="chiller", **params):
    """Return an absorption unit with a 20 kW/K characteristic and a 10 K threshold."""
    design = dict(
        mode=mode,
        capacity=1e6,
        characteristic_slope=20000,
        minimum_driving_difference=10,
        rejection_coefficient=2.2,
        evaporator_coefficient=1.2,
        auxiliary_power_ratio=0.01,
    )
    return si.set_params(with_values(AbsorptionUnit()), "", design | params)


def call(machine, setpoint, **streams):
    """Call the machine with the default circuits, replaced by ``streams``."""
    ports = dict(generator_in=GENERATOR, chilled_in=CHILLED, cooling_in=COOLING) | streams
    return machine(**ports, temperature_setpoint=setpoint)


def test_chiller_characteristic_hand_value_and_closure():
    """A low setpoint makes the characteristic equation limit the duty, solved in closed form."""
    machine = unit()
    result = call(machine, 273.15 + 4)
    out = reading(result)
    ratio = 1 + 1 / 0.7 + 0.01
    sensitivity = (1 / 0.7) / (2 * 10 * CP) + 2.2 * ratio / (2 * 25 * CP) + 1.2 / (2 * 10 * CP)
    expected = 20000 * (88 - 2.2 * 30 + 1.2 * 12 - 10) / (1 + 20000 * sensitivity)
    assert out.evaporator_duty == out.useful_duty == pytest.approx(expected)
    assert out.evaporator_duty == pytest.approx(20000 * (out.driving_temperature_difference - 10))
    assert out.is_capped and out.cop == pytest.approx(0.7)
    assert out.generator_duty == pytest.approx(expected / 0.7)
    assert out.electricity == pytest.approx(0.01 * expected)
    assert out.absorber_condenser_duty == pytest.approx(expected * ratio)
    assert out.chilled_out_T == pytest.approx(CHILLED.T - expected / (10 * CP))
    assert out.cooling_out_T == pytest.approx(COOLING.T + expected * ratio / (25 * CP))
    assert energy_balance(machine, result)["relative_residual"] < 1e-12
    assert mass_balance(machine, result)["residual"] == 0


def test_chiller_follows_setpoint_and_capacity():
    """A reachable setpoint is met exactly; the capacity caps the evaporator duty."""
    out = reading(call(unit(), 273.15 + 9))
    assert out.chilled_out_T == pytest.approx(273.15 + 9)
    assert out.evaporator_duty == pytest.approx(10 * CP * 3) and not out.is_capped
    capped = reading(call(unit(capacity=5e4), 273.15 + 9))
    assert capped.is_capped and capped.evaporator_duty == pytest.approx(5e4)


def test_heat_pump_mode_delivers_heat_on_the_cooling_circuit():
    """In heat-pump mode the setpoint is the cooling outlet and the COP is 1 + COP_th + aux."""
    machine = unit("heat_pump")
    result = call(machine, COOLING.T + 1)
    out = reading(result)
    assert out.cooling_out_T == pytest.approx(COOLING.T + 1)
    assert out.absorber_condenser_duty == pytest.approx(25 * CP)
    assert out.cop == pytest.approx(0.7 * (1 + 1 / 0.7 + 0.01))
    assert energy_balance(machine, result)["relative_residual"] < 1e-12
    capped = reading(call(unit("heat_pump", capacity=5e4), COOLING.T + 1))
    assert capped.absorber_condenser_duty == pytest.approx(5e4) and capped.is_capped


@pytest.mark.parametrize(
    "streams",
    [
        dict(generator_in=GENERATOR.with_(T=350)),
        dict(generator_in=GENERATOR.with_(m_dot=0)),
        dict(cooling_in=COOLING.with_(m_dot=0)),
        dict(cooling_in=COOLING.with_(T=320)),
    ],
)
def test_no_cold_without_driving_heat_or_flow(streams):
    """Below 80 degC, with a stopped circuit or below the threshold the unit delivers nothing."""
    result = call(unit(), 273.15 + 7, **streams)
    out = reading(result)
    assert out.evaporator_duty == out.generator_duty == out.electricity == 0
    assert out.cop is None and out.is_capped
    for port in ("generator", "chilled", "cooling"):
        assert getattr(result.outlets, f"{port}_out").T == getattr(result.inlets, f"{port}_in").T


def test_negative_flow_raises():
    """A reversed circuit flow is outside the model."""
    with pytest.raises(PhysicsError, match="chilled_in.m_dot = -1"):
        call(unit(), 280, chilled_in=CHILLED.with_(m_dot=-1))


@pytest.mark.parametrize(
    ("mode", "setpoints"),
    [("chiller", (278.15, 284.0, 270.0)), ("heat_pump", (320.0, 305.0, 300.0))],
)
def test_traced_call_matches_one_call_per_row(mode, setpoints):
    """Running, capped, cold-generator and stopped-circuit rows trace and equal per-row calls."""
    machine = unit(mode)
    rows = [
        dict(
            generator_in=GENERATOR.with_(T=generator_T, m_dot=generator_flow),
            chilled_in=CHILLED.with_(m_dot=chilled_flow),
            cooling_in=COOLING,
            temperature_setpoint=setpoint,
        )
        for generator_T, generator_flow, chilled_flow, setpoint in [
            (361.15, 10, 10, setpoints[0]),
            (361.15, 10, 10, setpoints[1]),
            (361.15, 10, 10, setpoints[2]),
            (340.0, 10, 10, setpoints[0]),
            (361.15, 0, 10, setpoints[0]),
            (361.15, 10, 0, setpoints[0]),
        ]
    ]
    assert_module_matches(machine, rows)
