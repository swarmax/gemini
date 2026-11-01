"""Sorption machines: the characteristic equation and the duties of a chiller."""

import math

from gemini import ops
from gemini.errors import PhysicsError
from gemini.units import k_to_c


@ops.physics
def characteristic_temperature_difference(
    generator_temperature: float,
    rejection_temperature: float,
    evaporator_temperature: float,
    rejection_coefficient: float,
    evaporator_coefficient: float,
) -> float:
    """Return the characteristic temperature difference of a sorption machine.

    Parameters
    ----------
    generator_temperature, rejection_temperature, evaporator_temperature : float
        External temperatures [K] of the driving (generator or desorber), the heat-rejection
        (absorber or adsorber plus condenser) and the chilled (evaporator) circuits.
    rejection_coefficient, evaporator_coefficient : float
        Fitted coefficients ``a`` and ``r`` [-] of the characteristic equation.

    Returns
    -------
    float
        ddt = t_G - a * t_AC + r * t_E [K], evaluated with Celsius temperatures.

    Notes
    -----
    Reference: Hellmann, Schweigler and Ziegler (1999), "The characteristic equations of
    absorption chillers", Proc. Int. Sorption Heat Pump Conference, Munich; Kuehn and Ziegler
    (2005), "Operational results of a 10 kW absorption chiller and adaptation of the
    characteristic equation", Proc. 1st Int. Conf. Solar Air Conditioning. For the ideal Duehring
    form a = 1 + B and r = B (B about 1.1 to 1.2 for water/LiBr); fitted values differ, so the
    equation is evaluated on the Celsius basis of the published fits. Valid for the fitted
    machine range of the published coefficients, with ``a`` and ``r`` nonnegative.
    """
    ops.check_numbers(
        "characteristic_temperature_difference",
        generator_temperature=generator_temperature,
        rejection_temperature=rejection_temperature,
        evaporator_temperature=evaporator_temperature,
        rejection_coefficient=rejection_coefficient,
        evaporator_coefficient=evaporator_coefficient,
    )
    return (
        k_to_c(generator_temperature)
        - rejection_coefficient * k_to_c(rejection_temperature)
        + evaporator_coefficient * k_to_c(evaporator_temperature)
    )


@ops.physics
def characteristic_evaporator_duty(
    driving_difference: float,
    minimum_driving_difference: float,
    slope: float,
    sensitivity: float,
) -> float:
    """Return the evaporator duty [W] of a sorption machine from its characteristic equation.

    Parameters
    ----------
    driving_difference : float
        Characteristic temperature difference [K] at the circuit inlet temperatures.
    minimum_driving_difference : float
        Threshold ddt_min [K] at which the machine stops producing cold.
    slope : float
        Nonnegative slope s [W/K] of the evaporator duty over ddt.
    sensitivity : float
        Nonnegative k [K/W]: how much ddt at the circuit mean temperatures falls per watt of
        evaporator duty (see ``characteristic_sensitivity``); ``inf`` for a stopped circuit.

    Returns
    -------
    float
        Q_E = max(0, s * (ddt_in - ddt_min) / (1 + s * k)) [W].

    Notes
    -----
    The characteristic equation Q_E = s * (ddt_mean - ddt_min) uses the arithmetic mean
    temperatures of the external circuits (Hellmann, Schweigler and Ziegler 1999). Because the
    mean temperatures move linearly with the duties, ddt_mean = ddt_in - k * Q_E, and the
    equation is solved here in closed form from the inlet temperatures.
    """
    ops.check_numbers(
        "characteristic_evaporator_duty",
        driving_difference=driving_difference,
        minimum_driving_difference=minimum_driving_difference,
        slope=slope,
        sensitivity=sensitivity,
    )
    ops.check(
        ops.logical_and(slope >= 0, sensitivity >= 0),
        PhysicsError,
        "characteristic_evaporator_duty: slope = {slope} W/K, sensitivity = "
        "{sensitivity} K/W; expected both >= 0",
        slope=slope,
        sensitivity=sensitivity,
    )
    return ops.where(
        ops.logical_or(ops.isinf(sensitivity), driving_difference <= minimum_driving_difference),
        0.0,
        slope * (driving_difference - minimum_driving_difference) / (1 + slope * sensitivity),
    )


@ops.physics
def characteristic_sensitivity(
    generator_rate: float,
    rejection_rate: float,
    evaporator_rate: float,
    generator_ratio: float,
    rejection_ratio: float,
    rejection_coefficient: float,
    evaporator_coefficient: float,
) -> float:
    """Return how much the mean-temperature ddt falls per watt of evaporator duty [K/W].

    Parameters
    ----------
    generator_rate, rejection_rate, evaporator_rate : float
        Nonnegative heat capacity rates m_dot * cp [W/K] of the three external circuits.
    generator_ratio, rejection_ratio : float
        Generator and heat-rejection duty per unit evaporator duty [-], Q_G / Q_E and
        Q_AC / Q_E.
    rejection_coefficient, evaporator_coefficient : float
        Coefficients ``a`` and ``r`` [-] of the characteristic equation.

    Returns
    -------
    float
        k = Q_G/Q_E / (2 C_G) + a * Q_AC/Q_E / (2 C_AC) + r / (2 C_E) [K/W]; ``inf`` when a
        circuit is stopped, since it then cannot carry any duty.

    Notes
    -----
    Each circuit's mean temperature moves by half its temperature change Q / C. The driving
    circuit cools, the heat-rejection circuit warms and the chilled circuit cools as the
    evaporator duty rises; all three lower ddt for positive coefficients. The half-change
    mean follows Hellmann, Schweigler and Ziegler (1999), who define the characteristic
    equation on the arithmetic mean circuit temperatures.
    """
    ops.check_numbers(
        "characteristic_sensitivity",
        generator_rate=generator_rate,
        rejection_rate=rejection_rate,
        evaporator_rate=evaporator_rate,
    )
    smallest = ops.minimum(ops.minimum(generator_rate, rejection_rate), evaporator_rate)
    ops.check(
        smallest >= 0,
        PhysicsError,
        "characteristic_sensitivity: capacity rates {{'generator_rate': {generator_rate}, "
        "'rejection_rate': {rejection_rate}, 'evaporator_rate': {evaporator_rate}}} W/K; "
        "expected all >= 0",
        generator_rate=generator_rate,
        rejection_rate=rejection_rate,
        evaporator_rate=evaporator_rate,
    )
    return ops.where(
        smallest == 0,
        math.inf,
        generator_ratio / (2 * generator_rate)
        + rejection_coefficient * rejection_ratio / (2 * rejection_rate)
        + evaporator_coefficient / (2 * evaporator_rate),
    )


@ops.physics
def sorption_evaporator_capacity(
    generator_temperature: float,
    rejection_temperature: float,
    evaporator_temperature: float,
    generator_rate: float,
    rejection_rate: float,
    evaporator_rate: float,
    *,
    slope: float,
    minimum_driving_difference: float,
    rejection_coefficient: float,
    evaporator_coefficient: float,
    thermal_cop: float,
    auxiliary_power_ratio: float,
) -> float:
    """Return the largest evaporator duty [W] a sorption chiller delivers at these inlets.

    Parameters
    ----------
    generator_temperature, rejection_temperature, evaporator_temperature : float
        Inlet temperatures [K] of the driving, heat-rejection and chilled circuits.
    generator_rate, rejection_rate, evaporator_rate : float
        Nonnegative heat capacity rates m_dot * cp [W/K] of the same circuits.
    slope, minimum_driving_difference : float
        Characteristic slope s [W/K] and threshold ddt_min [K].
    rejection_coefficient, evaporator_coefficient : float
        Characteristic coefficients ``a`` and ``r`` [-].
    thermal_cop : float
        Positive thermal COP Q_E / Q_G [-].
    auxiliary_power_ratio : float
        Nonnegative pump and auxiliary electricity per unit evaporator duty [-]; it ends up in
        the heat-rejection circuit.

    Returns
    -------
    float
        Q_E from ``characteristic_evaporator_duty`` with the inlet ddt and the mean-temperature
        sensitivity of the duty ratios Q_G / Q_E = 1 / COP and
        Q_AC / Q_E = 1 + 1 / COP + auxiliary_power_ratio.

    Notes
    -----
    Reference: Hellmann, Schweigler and Ziegler (1999) for the characteristic equation; the
    constant thermal COP is a simplification of its separate generator equation, reasonable
    away from the threshold where the measured COP of single-effect machines is nearly flat.
    """
    ops.check(
        ops.logical_and(thermal_cop > 0, auxiliary_power_ratio >= 0),
        PhysicsError,
        "sorption_evaporator_capacity: thermal_cop = {thermal_cop}, auxiliary_power_ratio "
        "= {auxiliary_power_ratio}; expected thermal_cop > 0 and auxiliary_power_ratio >= 0",
        thermal_cop=thermal_cop,
        auxiliary_power_ratio=auxiliary_power_ratio,
    )
    generator_ratio = 1 / thermal_cop
    rejection_ratio = sorption_rejection_ratio(thermal_cop, auxiliary_power_ratio)
    driving = characteristic_temperature_difference(
        generator_temperature,
        rejection_temperature,
        evaporator_temperature,
        rejection_coefficient,
        evaporator_coefficient,
    )
    sensitivity = characteristic_sensitivity(
        generator_rate,
        rejection_rate,
        evaporator_rate,
        generator_ratio,
        rejection_ratio,
        rejection_coefficient,
        evaporator_coefficient,
    )
    return characteristic_evaporator_duty(driving, minimum_driving_difference, slope, sensitivity)


@ops.physics
def sorption_rejection_ratio(thermal_cop: float, auxiliary_power_ratio: float) -> float:
    """Return the heat-rejection duty of a sorption machine per unit evaporator duty.

    Parameters
    ----------
    thermal_cop : float
        Thermal COP Q_E / Q_G [-], positive.
    auxiliary_power_ratio : float
        Pump and auxiliary electricity per unit evaporator duty [-], nonnegative.

    Returns
    -------
    float
        Q_AC / Q_E = 1 + 1 / COP + auxiliary_power_ratio [-].

    Notes
    -----
    First-law closure of a sorption machine (Herold, Radermacher and Klein 2016, Absorption
    Chillers and Heat Pumps, 2nd ed.): the absorber and condenser reject the evaporator,
    generator and auxiliary energy.
    """
    return 1 + 1 / thermal_cop + auxiliary_power_ratio


@ops.physics
def sorption_delivered_duty(
    requested: float, available: float, capacity: float, useful_ratio: float
) -> tuple:
    """Return the evaporator duty a sorption machine delivers and whether it falls short.

    Parameters
    ----------
    requested : float
        Useful duty [W] asked for by the setpoint.
    available : float
        Evaporator duty [W] the characteristic equation allows.
    capacity : float
        Cap on the useful duty [W].
    useful_ratio : float
        Useful duty per unit evaporator duty [-]: 1 for cooling, the rejection ratio for heating.

    Returns
    -------
    tuple of float
        ``(Q_E, is_capped)``: ``Q_E = min(min(requested / ratio, available), capacity / ratio)``
        [W], and whether it is below ``requested / ratio``.

    Notes
    -----
    Retained GEMINI throttling: the machine follows the request at an unchanged COP until the
    characteristic equation or the capacity limits it.

    Validity: useful_ratio positive (the code divides by it); requested, available and capacity
    nonnegative.
    """
    wanted = requested / useful_ratio
    delivered = ops.minimum(ops.minimum(wanted, available), capacity / useful_ratio)
    return delivered, delivered < wanted


@ops.physics
def sorption_duties(
    evaporator_duty: float, thermal_cop: float, auxiliary_power_ratio: float
) -> tuple:
    """Return the generator duty, auxiliary electricity and rejected heat of a sorption machine.

    Parameters
    ----------
    evaporator_duty : float
        Evaporator duty Q_E [W].
    thermal_cop : float
        Thermal COP Q_E / Q_G [-], positive.
    auxiliary_power_ratio : float
        Auxiliary electricity per unit evaporator duty [-], nonnegative.

    Returns
    -------
    tuple of float
        ``(Q_G, P, Q_AC)`` [W]: ``Q_G = Q_E / COP``, ``P = ratio * Q_E`` and
        ``Q_AC = Q_G + Q_E + P``.

    Notes
    -----
    Constant thermal COP with the first-law closure of ``sorption_rejection_ratio``.

    Source: First-law closure of Herold, Radermacher and Klein (2016), Absorption Chillers and Heat
    Pumps, 2nd ed.
    """
    generator = evaporator_duty / thermal_cop
    electricity = evaporator_duty * auxiliary_power_ratio
    return generator, electricity, generator + evaporator_duty + electricity
