"""Adsorption chiller: characteristic map, driving-temperature range, limits and closure."""

import pytest

from gemini.errors import PhysicsError, ValidationError
from gemini.modules._utils.balance import energy_balance, mass_balance
from gemini.modules.cooling import AdsorptionChiller
from gemini.types.flows import Stream
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

CP = 4217.4
GENERATOR = Stream(m_dot=5, T=343.15, p=3e5)
CHILLED = Stream(m_dot=5, T=291.15, p=3e5)
COOLING = Stream(m_dot=10, T=300.15, p=3e5)


def chiller(**params):
    """Return an adsorption chiller with a 2 kW/K characteristic and a 5 K threshold."""
    design = dict(
        capacity=1e5,
        characteristic_slope=2000,
        minimum_driving_difference=5,
        rejection_coefficient=2.0,
        evaporator_coefficient=1.0,
        auxiliary_power_ratio=0.02,
    )
    return AdsorptionChiller().set_params("", design | params)


def call(machine, setpoint, **streams):
    """Call the chiller with the default circuits, replaced by ``streams``."""
    ports = dict(generator_in=GENERATOR, chilled_in=CHILLED, cooling_in=COOLING) | streams
    return machine(**ports, temperature_setpoint=setpoint)


def test_characteristic_hand_value_and_closure():
    """At 70/27/18 degC the duty follows the closed-form characteristic equation, COP 0.55."""
    machine = chiller()
    result = call(machine, 273.15 + 5)
    out = reading(result)
    ratio = 1 + 1 / 0.55 + 0.02
    sensitivity = (1 / 0.55) / (2 * 5 * CP) + 2.0 * ratio / (2 * 10 * CP) + 1.0 / (2 * 5 * CP)
    expected = 2000 * (70 - 2 * 27 + 18 - 5) / (1 + 2000 * sensitivity)
    assert out.evaporator_duty == pytest.approx(expected)
    assert out.evaporator_duty == pytest.approx(2000 * (out.driving_temperature_difference - 5))
    assert out.cop == pytest.approx(0.55) and out.is_capped
    assert out.generator_duty == pytest.approx(expected / 0.55)
    assert out.adsorber_condenser_duty == pytest.approx(expected * ratio)
    assert out.generator_out_T == pytest.approx(GENERATOR.T - expected / 0.55 / (5 * CP))
    assert energy_balance(machine, result)["relative_residual"] < 1e-12
    assert mass_balance(machine, result)["residual"] == 0


def test_setpoint_and_capacity():
    """A reachable setpoint is met; the capacity caps the evaporator duty."""
    out = reading(call(chiller(), 273.15 + 17))
    assert out.chilled_out_T == pytest.approx(273.15 + 17) and not out.is_capped
    capped = reading(call(chiller(capacity=1e4), 273.15 + 15))
    assert capped.evaporator_duty == pytest.approx(1e4) and capped.is_capped


def test_driving_temperature_range():
    """Below 55 degC the chiller is off; above 90 degC the map is out of range."""
    result = call(chiller(), 280, generator_in=GENERATOR.with_(T=273.15 + 50))
    assert reading(result).evaporator_duty == 0 and result.outputs.cop is None
    assert result.outlets.chilled_out.T == CHILLED.T
    with pytest.raises(PhysicsError, match="generator_in.T = 368.15"):
        call(chiller(), 280, generator_in=GENERATOR.with_(T=368.15))
    with raises(ValidationError, "invalid_design", match="minimum_driving_temperature"):
        call(chiller(minimum_driving_temperature=370), 280)


def test_zero_and_negative_flow():
    """A stopped circuit gives no cold; a reversed flow raises."""
    out = reading(call(chiller(), 280, cooling_in=COOLING.with_(m_dot=0)))
    assert out.evaporator_duty == 0 and out.electricity == 0
    with pytest.raises(PhysicsError, match="generator_in.m_dot = -2"):
        call(chiller(), 280, generator_in=GENERATOR.with_(m_dot=-2))


def test_traced_call_matches_one_call_per_row():
    """Running, capped, cold-generator and stopped-circuit rows trace and equal per-row calls."""
    machine = chiller()
    rows = [
        dict(
            generator_in=GENERATOR.with_(T=generator_T, m_dot=generator_flow),
            chilled_in=CHILLED.with_(m_dot=chilled_flow),
            cooling_in=COOLING,
            temperature_setpoint=setpoint,
        )
        for generator_T, generator_flow, chilled_flow, setpoint in [
            (343.15, 5, 5, 278.15),
            (343.15, 5, 5, 289.0),
            (343.15, 5, 5, 270.0),
            (320.0, 5, 5, 278.15),
            (343.15, 0, 5, 278.15),
            (343.15, 5, 0, 278.15),
        ]
    ]
    assert_module_matches(machine, rows)


def test_a_stopped_drive_circuit_has_no_driving_temperature():
    """Water that does not flow drives nothing, whatever its temperature: no limit applies."""
    chiller = AdsorptionChiller().set_params(
        "",
        {
            "capacity": {"value": 100, "unit": "kW"},
            "characteristic_slope": 2000,
            "minimum_driving_difference": 5,
            "rejection_coefficient": 2.0,
            "evaporator_coefficient": 1.0,
            "auxiliary_power_ratio": 0.02,
        },
    )
    result = chiller(
        generator_in=Stream(m_dot=0.0, T=373.15, p=3e5),
        chilled_in=Stream(m_dot=5.0, T=291.15, p=3e5),
        cooling_in=Stream(m_dot=10.0, T=300.15, p=3e5),
        temperature_setpoint=285.15,
    )
    assert result.outlets.chilled_out.T == 291.15
