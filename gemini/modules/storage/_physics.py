"""Thermal storage: mixed water tanks, coil conductance and the phase segments of an ice store.

The relations are lumped (one uniform store temperature): the fully mixed tank balance of
Duffie and Beckman (2013, Solar Engineering of Thermal Processes, 4th ed., section 8.3), the
effectiveness of a circuit against a store at uniform temperature (Incropera et al.,
Fundamentals of Heat and Mass Transfer), and the exact piecewise integration of an
ice-on-coil store across its liquid, freezing or melting and solid segments.
"""

from gemini import ops, units
from gemini.physics import heat_transfer

DEFAULT_LATENT_HEAT = 333550
"""Latent heat of fusion of ice [J/kg]: the conventional 333.55 kJ/kg at 0 degC and 101.325 kPa.

IAPWS R10-06 (Feistel and Wagner 2006, A new equation of state for H2O ice Ih) gives
333.44 kJ/kg at the triple point, 0.03 % lower.
"""

DEFAULT_FREEZING_TEMPERATURE = units.ZERO_CELSIUS
"""Normal melting point of ice [K]."""

DEFAULT_WATER_HEAT_CAPACITY = 4219.9
"""Specific heat capacity [J/kg/K] of saturated liquid water at 0.01 degC (IAPWS-95, Wagner and
Pruss 2002)."""

DEFAULT_ICE_HEAT_CAPACITY = 2096.8
"""Specific heat capacity [J/kg/K] of ice Ih at the triple point (IAPWS R10-06)."""

MAX_SEGMENTS = 3
"""Most phase segments one step can cross: liquid, freezing or melting, then solid (or back)."""


@ops.physics
def circuit_conductance(effectiveness: float, capacity_rate: float) -> float:
    """Return the conductance of a circuit exchanging heat with a store at uniform temperature.

    Parameters
    ----------
    effectiveness : float
        Effectiveness of the circuit [-], in [0, 1].
    capacity_rate : float
        Heat capacity rate ``m cp`` of the circuit fluid [W/K], nonnegative.

    Returns
    -------
    float
        ``G = e C`` [W/K]; the heat flow into the store is ``G (T_in - T)``.

    Notes
    -----
    Reference: Incropera et al., Fundamentals of Heat and Mass Transfer, effectiveness-NTU
    method: ``Q = e C (T_in - T_store)`` against a store at uniform temperature.
    """
    return effectiveness * capacity_rate


@ops.physics
def tank_capacity(volumetric_heat_capacity: float, volume: float) -> float:
    """Return the heat capacity of a tank of liquid.

    Parameters
    ----------
    volumetric_heat_capacity : float
        Liquid ``rho cp`` [J/m3/K].
    volume : float
        Tank volume [m3].

    Returns
    -------
    float
        ``C = rho cp V`` [J/K].

    Notes
    -----
    Reference: Duffie and Beckman (2013), section 8.3, fully mixed storage.

    Validity: volumetric_heat_capacity and volume positive; no division occurs. A uniform tank
    temperature.
    """
    return volumetric_heat_capacity * volume


@ops.physics
def tank_service_report(
    hot: bool,
    capacity: float,
    temperature: float,
    reference_temperature: float,
    charge_heat: float,
    discharge_heat: float,
) -> tuple[float, float, float]:
    """Return the stored energy and the two circuit duties of a tank, signed by its service.

    Parameters
    ----------
    hot : bool
        True for a tank that stores heat, false for one that stores cold.
    capacity : float
        Tank heat capacity ``rho cp V`` [J/K].
    temperature, reference_temperature : float
        Tank temperature and the temperature at which it stores no energy [K].
    charge_heat, discharge_heat : float
        Heat flows of the two circuits into the tank [W], positive when they warm it.

    Returns
    -------
    tuple of float
        ``(E, Q_charge, Q_discharge)`` [J, W, W]: for a hot tank ``E = C (T - T_ref)``,
        charge duty ``Q_c`` and discharge duty ``-Q_d``; for a chilled tank every sign flips.

    Notes
    -----
    A negative duty means the circuit works against the service of the tank. Sign convention
    of GEMINI storage reports.
    """
    sign = ops.where(hot, 1.0, -1.0)
    return (
        sign * capacity * (temperature - reference_temperature),
        sign * charge_heat,
        -sign * discharge_heat,
    )


@ops.physics
def tank_relaxation(
    temperature: float,
    capacity: float,
    duration: float,
    charge_conductance: float,
    charge_temperature: float,
    discharge_conductance: float,
    discharge_temperature: float,
    loss_conductance: float,
    ambient_temperature: float,
) -> float:
    """Return the temperature of a fully mixed tank after a step with constant inlets.

    Parameters
    ----------
    temperature : float
        Tank temperature at the start of the step [K].
    capacity : float
        Tank heat capacity ``rho cp V`` [J/K], positive.
    duration : float
        Step length [s], nonnegative.
    charge_conductance, discharge_conductance : float
        Circuit conductances ``e C`` [W/K], nonnegative (``circuit_conductance``).
    charge_temperature, discharge_temperature : float
        Circuit inlet temperatures [K].
    loss_conductance, ambient_temperature : float
        Conductance ``UA`` to the surroundings [W/K], nonnegative, and their temperature [K].

    Returns
    -------
    float
        ``T_eq + (T - T_eq) exp(-b dt / C)`` [K] with ``b = G_c + G_d + UA`` and
        ``T_eq = (G_c T_c + G_d T_d + UA T_amb) / b``; unchanged for ``b = 0``.

    Notes
    -----
    Reference: Duffie and Beckman (2013), section 8.3, fully mixed storage:
    ``C dT/dt = G_c (T_c - T) + G_d (T_d - T) - UA (T - T_amb)``, solved exactly for constant
    inlets; unconditionally stable.
    """
    total = charge_conductance + discharge_conductance + loss_conductance
    weighted = (
        charge_conductance * charge_temperature
        + discharge_conductance * discharge_temperature
        + loss_conductance * ambient_temperature
    )
    equilibrium = weighted / total
    factor = heat_transfer.relaxation_factor(total, duration, capacity)
    relaxed = heat_transfer.exponential_relaxation(temperature, equilibrium, factor)
    return ops.where(total == 0, temperature, relaxed)


@ops.physics
def ice_stored_cold(water_mass: float, latent_heat: float, fraction: float) -> float:
    """Return the latent cold stored in an ice store.

    Parameters
    ----------
    water_mass : float
        Mass of water in the store [kg].
    latent_heat : float
        Latent heat of fusion [J/kg].
    fraction : float
        Frozen fraction of the water [-], in [0, 1].

    Returns
    -------
    float
        ``E = M L x`` [J].

    Notes
    -----
    Latent heat of fusion released when the frozen fraction melts.

    Validity: water_mass nonnegative, latent_heat positive, fraction in [0, 1]; no division occurs.
    Source: A first-law latent-heat balance; no published source is needed.
    """
    return water_mass * latent_heat * fraction


@ops.physics
def ice_advance(
    fraction: float,
    temperature: float,
    duration: float,
    inlet_temperature: float,
    conductance: float,
    water_mass: float,
    latent_heat: float,
    freezing_temperature: float,
    water_specific_heat: float,
    ice_specific_heat: float,
) -> tuple[float, float]:
    """Return the frozen fraction and the temperature of an ice store after a step.

    Parameters
    ----------
    fraction : float
        Frozen fraction x at the start [-]; 0 for all liquid, 1 for all ice.
    temperature : float
        Store temperature [K]: the freezing temperature while partly frozen, above it only for
        x = 0, below it only for x = 1.
    duration : float
        Step length [s].
    inlet_temperature : float
        Glycol inlet temperature [K], held constant over the step.
    conductance : float
        Coil conductance ``e C`` [W/K], nonnegative (``circuit_conductance``).
    water_mass : float
        Mass of water in the store [kg].
    latent_heat, freezing_temperature : float
        Latent heat of fusion [J/kg] and freezing temperature [K].
    water_specific_heat, ice_specific_heat : float
        Specific heat capacities of liquid water and of ice [J/kg/K].

    Returns
    -------
    tuple of float
        ``(x, T)`` at the end of the step.

    Notes
    -----
    The enthalpy balance is integrated exactly and piecewise for a constant inlet
    (``MAX_SEGMENTS`` passes, a finished pass keeping its state): in the latent segment the duty
    is constant and x changes linearly by ``-Q t / (M L)``; in a sensible segment T relaxes to
    the inlet with the time constant ``M c / G`` and stops at the freezing temperature.
    Reference: Incropera et al., Fundamentals of Heat and Mass Transfer (lumped capacitance);
    ASHRAE Handbook, HVAC Applications, Thermal Storage.
    """
    state = (fraction, temperature, duration)
    for _ in range(MAX_SEGMENTS):
        finished = ops.logical_or(state[2] <= 0, conductance == 0)
        advanced = ice_step(
            *state,
            inlet_temperature,
            conductance,
            water_mass,
            latent_heat,
            freezing_temperature,
            water_specific_heat,
            ice_specific_heat,
        )
        state = _select(finished, state, advanced)
    return state[0], state[1]


@ops.physics
def ice_step(
    fraction: float,
    temperature: float,
    duration: float,
    inlet_temperature: float,
    conductance: float,
    water_mass: float,
    latent_heat: float,
    freezing_temperature: float,
    water_specific_heat: float,
    ice_specific_heat: float,
) -> tuple[float, float, float]:
    """Advance an ice store through one phase segment.

    Parameters
    ----------
    fraction, temperature, duration, inlet_temperature, conductance, water_mass, latent_heat,
    freezing_temperature, water_specific_heat, ice_specific_heat : float
        As in ``ice_advance``; ``duration`` is the time left in the step [s].

    Returns
    -------
    tuple of float
        ``(x, T, time left)`` after the segment: the time left is zero when the step ends
        inside the segment and positive when the store became full, empty or reached freezing.

    Notes
    -----
    Liquid segment (T above freezing, or x = 0 with a warm inlet) and solid segment relax
    sensibly; otherwise the latent segment runs at the constant duty ``G (T_in - T_f)``.

    Source: Incropera et al., Fundamentals of Heat and Mass Transfer, lumped capacitance method, as
    for ``ice_advance``. Valid for conductance positive (the code divides by it), water_mass and
    latent_heat positive, duration nonnegative.
    """
    freezing = freezing_temperature
    liquid = ops.logical_or(
        temperature > freezing,
        ops.logical_and(fraction == 0, inlet_temperature > freezing),
    )
    solid = ops.logical_or(
        temperature < freezing,
        ops.logical_and(fraction == 1, inlet_temperature < freezing),
    )
    water = water_mass * water_specific_heat
    ice = water_mass * ice_specific_heat
    args = (fraction, temperature, inlet_temperature, freezing)
    return _select(
        liquid,
        _sensible(*args, water / conductance, duration),
        _select(
            solid,
            _sensible(*args, ice / conductance, duration),
            _latent(
                fraction,
                conductance * (inlet_temperature - freezing),
                duration,
                water_mass * latent_heat,
                freezing,
            ),
        ),
    )


def _select(condition, if_true, if_false):
    """Return the tuple of ``if_true`` where ``condition`` holds, else of ``if_false``."""
    return tuple(ops.where(condition, a, b) for a, b in zip(if_true, if_false))


def _sensible(fraction, temperature, inlet_temperature, freezing, time_constant, duration):
    """Relax an all-liquid or all-ice store towards the inlet, stopping at freezing."""
    crosses = (temperature - freezing) * (inlet_temperature - freezing) < 0
    reach = time_constant * ops.log(
        (temperature - inlet_temperature) / (freezing - inlet_temperature)
    )
    stops = ops.logical_and(crosses, reach < duration)
    relaxed = heat_transfer.exponential_relaxation(
        temperature, inlet_temperature, ops.exp(-duration / time_constant)
    )
    overshoots = ops.logical_and(crosses, (relaxed - freezing) * (temperature - freezing) <= 0)
    return (
        fraction,
        ops.where(ops.logical_or(stops, overshoots), freezing, relaxed),
        ops.where(stops, duration - reach, 0.0),
    )


def _latent(fraction, heat, duration, latent_capacity, freezing):
    """Freeze (heat < 0) or melt (heat > 0) at constant duty until full, empty or done."""
    target = ops.where(heat > 0, 0.0, 1.0)
    reach = latent_capacity * ops.abs(target - fraction) / ops.abs(heat)
    changed = fraction - heat * duration / latent_capacity
    reached = reach < duration
    moved = (
        ops.where(reached, target, ops.minimum(1.0, ops.maximum(0.0, changed))),
        freezing,
        ops.where(reached, duration - reach, 0.0),
    )
    return _select(heat == 0, (fraction, freezing, 0.0), moved)
