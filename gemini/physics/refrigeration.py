"""Heat pump and chiller relations: Carnot and Lorenz COPs and part load.

All functions take and return SI values (K, W, W/K).
"""

from gemini import ops
from gemini.errors import PhysicsError
from gemini.physics import heat_transfer

DEFAULT_CARNOT_FRACTION = 0.5
"""Carnot fraction of a heat pump or chiller [-]: "close to 50 percent of the Carnot value",
H. U. Frutschi, ABB Review 5/1996, pp. 33-34. It is the default of ``HeatPump.carnot_fraction``, a
parameter a design should state from the data of its machine."""


DEFAULT_LORENZ_FRACTION = 0.5
"""Lorenz fraction of a water-to-water heat pump [-]: an assumption, the value of
``DEFAULT_CARNOT_FRACTION``; no source was found for a Lorenz value of its own."""


DEFAULT_MINIMUM_LIFT = 10.0
"""Floor of the temperature lift in a COP [K]: the lowest lift of the water-to-water machines
summarised by Arpagaus et al. (2018), which bounds the COP of nearly equal temperatures."""


@ops.physics
def carnot_cop_heating(
    sink_temperature: float, source_temperature: float, minimum_lift: float = 0.0
) -> float:
    """Return the Carnot heating COP of a heat pump.

    Parameters
    ----------
    sink_temperature, source_temperature : float
        Absolute temperatures [K] at which heat is delivered and taken up.
    minimum_lift : float
        Lift floor [K]: the lift used is ``max(sink - source, minimum_lift)``.

    Returns
    -------
    float
        COP_h = T_sink / (T_sink - T_source) [-], with the floored lift.

    Notes
    -----
    Reference: Carnot efficiency of a reversible heat pump, for example Moran and Shapiro,
    Fundamentals of Engineering Thermodynamics, chapter 5. Valid for any positive temperatures
    whose (floored) lift is positive; the floor bounds the COP of nearly equal temperatures.
    """
    return _heating_cop("carnot_cop_heating", sink_temperature, source_temperature, minimum_lift)


@ops.physics
def carnot_cop_cooling(
    sink_temperature: float, source_temperature: float, minimum_lift: float = 0.0
) -> float:
    """Return the Carnot cooling COP (energy efficiency ratio) of a chiller.

    Parameters
    ----------
    sink_temperature, source_temperature : float
        Absolute temperatures [K] at which heat is rejected and taken up (the cold side).
    minimum_lift : float
        Lift floor [K]: the lift used is ``max(sink - source, minimum_lift)``.

    Returns
    -------
    float
        COP_c = T_source / (T_sink - T_source) [-], with the floored lift.

    Notes
    -----
    Reference: Carnot efficiency of a reversible refrigerator, for example Moran and Shapiro,
    Fundamentals of Engineering Thermodynamics, chapter 5. COP_c = COP_h - 1 for the same lift.

    Validity: Both temperatures positive and minimum_lift >= 0; the floored lift must be positive
    (it is the divisor). The sink is normally warmer than the source.
    """
    lift = _lift("carnot_cop_cooling", sink_temperature, source_temperature, minimum_lift)
    return source_temperature / lift


@ops.physics
def log_mean_temperature(inlet_temperature: float, outlet_temperature: float) -> float:
    """Return the logarithmic mean (thermodynamic mean) temperature of a sensible glide.

    Parameters
    ----------
    inlet_temperature, outlet_temperature : float
        Positive absolute temperatures [K] at which a stream enters and leaves.

    Returns
    -------
    float
        T_m = (T_in - T_out) / ln(T_in / T_out) [K]; T_in when both are equal.

    Notes
    -----
    T_m is the temperature at which a reversible engine exchanges the same heat and entropy as
    a stream of constant heat capacity changing from T_in to T_out (Lorenz 1894; Moran and
    Shapiro, Fundamentals of Engineering Thermodynamics, chapter 6). It lies between the
    geometric and the arithmetic mean of the two temperatures.
    """
    ops.check_numbers(
        "log_mean_temperature",
        inlet_temperature=inlet_temperature,
        outlet_temperature=outlet_temperature,
    )
    ops.check(
        ops.logical_and(inlet_temperature > 0, outlet_temperature > 0),
        PhysicsError,
        "log_mean_temperature: inlet_temperature = {inlet_temperature} K, "
        "outlet_temperature = {outlet_temperature} K; expected positive temperatures",
        inlet_temperature=inlet_temperature,
        outlet_temperature=outlet_temperature,
    )
    return ops.where(
        inlet_temperature == outlet_temperature,
        inlet_temperature,
        heat_transfer.logarithmic_mean(inlet_temperature, outlet_temperature),
    )


@ops.physics
def lorenz_cop_heating(
    sink_inlet: float,
    sink_outlet: float,
    source_inlet: float,
    source_outlet: float,
    minimum_lift: float = 0.0,
) -> float:
    """Return the Lorenz (gliding-temperature) heating COP of a heat pump.

    Parameters
    ----------
    sink_inlet, sink_outlet : float
        Absolute temperatures [K] of the heated circuit at the condenser inlet and outlet.
    source_inlet, source_outlet : float
        Absolute temperatures [K] of the cooled circuit at the evaporator inlet and outlet.
    minimum_lift : float
        Lift floor [K] on the difference of the two log-mean temperatures.

    Returns
    -------
    float
        COP_h = T_h / max(T_h - T_s, minimum_lift) [-], with T_h and T_s the log-mean
        temperatures of the sink and source glides (``log_mean_temperature``).

    Notes
    -----
    Reference: Lorenz, H. (1894), "Die Ermittlung der Grenzwerte der thermodynamischen
    Energieumwandlung", Zeitschrift fuer die gesamte Kaelte-Industrie 1, 1-11. The Lorenz cycle
    is the reversible cycle between two streams of finite heat capacity; it reduces to the
    Carnot COP when both glides vanish. It suits water-to-water machines whose circuits change
    temperature by several kelvin. Valid for positive temperatures whose floored log-mean lift
    is positive and for glides of constant heat capacity.
    """
    sink = log_mean_temperature(sink_inlet, sink_outlet)
    source = log_mean_temperature(source_inlet, source_outlet)
    return _heating_cop("lorenz_cop_heating", sink, source, minimum_lift)


@ops.physics
def coefficient_of_performance(useful_duty: float, input_duty: float) -> float:
    """Return the coefficient of performance of a machine.

    Parameters
    ----------
    useful_duty : float
        Useful heating or cooling duty [W].
    input_duty : float
        Driving heat or electricity [W], positive.

    Returns
    -------
    float
        COP = useful duty / input duty [-].

    Notes
    -----
    Definition, Moran and Shapiro, Fundamentals of Engineering Thermodynamics, chapter 10; for
    a sorption machine the input is the generator duty (the thermal COP).
    """
    return useful_duty / input_duty


@ops.physics
def part_load_duty(requested: float, capacity: float, minimum_part_load: float) -> float:
    """Return the duty [W] a capacity-limited machine with a minimum part load delivers.

    Parameters
    ----------
    requested : float
        Nonnegative duty [W] asked for by the setpoint.
    capacity : float
        Positive rated duty [W].
    minimum_part_load : float
        Smallest steady load as a fraction of capacity [-], in [0, 1].

    Returns
    -------
    float
        min(requested, capacity), or 0 when that is below minimum_part_load * capacity.

    Notes
    -----
    Below the minimum part load the machine is taken as switched off for the step rather than
    cycling on and off; at hourly steps this underestimates the delivered heat of a cycling
    machine. EN 14825 (seasonal performance of heat pumps and chillers) describes the cycling
    alternative with a degradation coefficient. This on/off cutoff is a retained GEMINI
    simplification, not a published relation.
    """
    ops.check_numbers(
        "part_load_duty",
        requested=requested,
        capacity=capacity,
        minimum_part_load=minimum_part_load,
    )
    ops.check(
        ops.logical_and(
            ops.logical_and(requested >= 0, capacity > 0),
            ops.logical_and(minimum_part_load >= 0, minimum_part_load <= 1),
        ),
        PhysicsError,
        "part_load_duty: requested = {requested} W, capacity = {capacity} W, "
        "minimum_part_load = {minimum_part_load}; expected requested >= 0, capacity > 0 "
        "and minimum_part_load in [0, 1]",
        requested=requested,
        capacity=capacity,
        minimum_part_load=minimum_part_load,
    )
    duty = ops.minimum(requested, capacity)
    return ops.where(duty < minimum_part_load * capacity, 0.0, duty)


def _heating_cop(function, sink_temperature, source_temperature, minimum_lift):
    """Return ``T_sink / max(T_sink - T_source, minimum_lift)``, the reversible heating COP."""
    lift = _lift(function, sink_temperature, source_temperature, minimum_lift)
    return sink_temperature / lift


def _lift(function, sink_temperature, source_temperature, minimum_lift):
    """Return the floored temperature lift [K]; reject nonpositive temperatures and lifts."""
    ops.check_numbers(
        function,
        sink_temperature=sink_temperature,
        source_temperature=source_temperature,
        minimum_lift=minimum_lift,
    )
    ops.check(
        ops.logical_and(
            ops.logical_and(sink_temperature > 0, source_temperature > 0), minimum_lift >= 0
        ),
        PhysicsError,
        "{function}: sink_temperature = {sink_temperature} K, source_temperature = "
        "{source_temperature} K, minimum_lift = {minimum_lift} K; expected positive "
        "temperatures and minimum_lift >= 0",
        function=function,
        sink_temperature=sink_temperature,
        source_temperature=source_temperature,
        minimum_lift=minimum_lift,
    )
    lift = sink_temperature - source_temperature
    floored = ops.maximum(lift, minimum_lift)
    ops.check(
        floored > 0,
        PhysicsError,
        "{function}: lift = {lift} K, minimum_lift = {minimum_lift} K; expected "
        "sink_temperature above source_temperature or a positive minimum_lift",
        function=function,
        lift=lift,
        minimum_lift=minimum_lift,
    )
    return floored


@ops.physics
def carnot_fraction_cop_heating(
    efficiency: float,
    minimum_lift: float,
    sink_inlet: float,
    sink_outlet: float,
    source_inlet: float,
    source_outlet: float,
) -> float:
    """Return the heating COP as a fraction of the Carnot COP at the outlet temperatures.

    Parameters
    ----------
    efficiency : float
        Carnot fraction [-].
    minimum_lift : float
        Lift floor [K].
    sink_inlet, sink_outlet, source_inlet, source_outlet : float
        Absolute temperatures [K] of the circuits; only the outlets enter.

    Returns
    -------
    float
        COP = efficiency * ``carnot_cop_heating(sink_outlet, source_outlet, minimum_lift)`` [-].

    Notes
    -----
    Same signature as ``carnot_fraction_cop_cooling`` and ``lorenz_fraction_cop_heating``, so a
    module picks the COP model structurally. Carnot fraction: ``DEFAULT_CARNOT_FRACTION``.

    Validity: efficiency in (0, 1]; outlet temperatures positive and minimum_lift >= 0 with a
    positive floored lift (the divisor of the Carnot COP). The inlets are not used.
    """
    return efficiency * carnot_cop_heating(sink_outlet, source_outlet, minimum_lift)


@ops.physics
def carnot_fraction_cop_cooling(
    efficiency: float,
    minimum_lift: float,
    sink_inlet: float,
    sink_outlet: float,
    source_inlet: float,
    source_outlet: float,
) -> float:
    """Return the cooling COP as a fraction of the Carnot COP at the outlet temperatures.

    Parameters
    ----------
    efficiency : float
        Carnot fraction [-].
    minimum_lift : float
        Lift floor [K].
    sink_inlet, sink_outlet, source_inlet, source_outlet : float
        Absolute temperatures [K] of the circuits; only the outlets enter.

    Returns
    -------
    float
        COP = efficiency * ``carnot_cop_cooling(sink_outlet, source_outlet, minimum_lift)`` [-].

    Notes
    -----
    See ``carnot_fraction_cop_heating``.

    Validity: efficiency in (0, 1]; outlet temperatures positive and minimum_lift >= 0 with a
    positive floored lift (the divisor of the Carnot COP). The inlets are not used.
    """
    return efficiency * carnot_cop_cooling(sink_outlet, source_outlet, minimum_lift)


@ops.physics
def lorenz_fraction_cop_heating(
    efficiency: float,
    minimum_lift: float,
    sink_inlet: float,
    sink_outlet: float,
    source_inlet: float,
    source_outlet: float,
) -> float:
    """Return the heating COP as a fraction of the Lorenz COP at the circuit glides.

    Parameters
    ----------
    efficiency : float
        Lorenz fraction [-].
    minimum_lift : float
        Lift floor [K] on the log-mean temperature difference.
    sink_inlet, sink_outlet, source_inlet, source_outlet : float
        Absolute temperatures [K] of the circuits.

    Returns
    -------
    float
        COP = efficiency * ``lorenz_cop_heating`` [-].

    Notes
    -----
    See ``carnot_fraction_cop_heating`` and ``lorenz_cop_heating`` (Lorenz 1894).

    Validity: efficiency in (0, 1]; all four temperatures positive, minimum_lift >= 0, and the
    floored log-mean lift positive (the divisor of the Lorenz COP).
    """
    cop = lorenz_cop_heating(sink_inlet, sink_outlet, source_inlet, source_outlet, minimum_lift)
    return efficiency * cop


@ops.physics
def heating_evaporator_duty(condenser_duty: float, cop: float) -> float:
    """Return the evaporator duty of a heat pump from its condenser duty and heating COP.

    Parameters
    ----------
    condenser_duty : float
        Useful heating duty [W].
    cop : float
        Heating COP [-].

    Returns
    -------
    float
        ``Q_E = Q_C - Q_C / COP`` [W]; the difference is the compressor electricity.

    Notes
    -----
    First law of a steady vapour-compression cycle, Moran and Shapiro, Fundamentals of
    Engineering Thermodynamics, chapter 10.

    Validity: cop nonzero (the code divides by it) and above one for a heat pump, so that Q_E is
    nonnegative; condenser_duty nonnegative.
    Source: First law of a steady vapour-compression cycle, Moran and Shapiro, Fundamentals of
    Engineering Thermodynamics, chapter 10.
    """
    return condenser_duty - condenser_duty / cop


@ops.physics
def cooling_condenser_duty(evaporator_duty: float, cop: float) -> float:
    """Return the condenser duty of a chiller from its evaporator duty and cooling COP.

    Parameters
    ----------
    evaporator_duty : float
        Useful cooling duty [W].
    cop : float
        Cooling COP [-].

    Returns
    -------
    float
        ``Q_C = Q_E + Q_E / COP`` [W]; the sum is the evaporator duty and the electricity.

    Notes
    -----
    First law of a steady vapour-compression cycle, Moran and Shapiro, Fundamentals of
    Engineering Thermodynamics, chapter 10.

    Validity: cop positive (the code divides by it); evaporator_duty nonnegative.
    Source: First law of a steady vapour-compression cycle, Moran and Shapiro, Fundamentals of
    Engineering Thermodynamics, chapter 10.
    """
    return evaporator_duty + evaporator_duty / cop


@ops.physics
def carnot_heating_source_outlet(
    source_inlet: float,
    temperature_change: float,
    sink_outlet: float,
    efficiency: float,
    minimum_lift: float,
) -> float:
    """Return the source outlet temperature that closes the balance of a Carnot-fraction pump.

    Parameters
    ----------
    source_inlet : float
        Source inlet temperature [K].
    temperature_change : float
        Duty over source capacity rate Q / C [K], nonnegative.
    sink_outlet : float
        Sink outlet temperature [K].
    efficiency : float
        Carnot fraction [-].
    minimum_lift : float
        Lift floor [K].

    Returns
    -------
    float
        x [K] solving C (T_in - x) = Q (1 - 1 / COP) with COP = eta T_h / max(T_h - x, lift): with
        the floored lift x = T_in - dT (1 - lift / (eta T_h)), which applies when it leaves the
        lift within the floor; otherwise x = (T_in - dT (1 - 1 / eta)) / (1 + dT / (eta T_h)).

    Notes
    -----
    Closed form of a linear balance; first law of ``heating_evaporator_duty``.
    """
    floored = source_inlet - temperature_change * (1 - minimum_lift / (efficiency * sink_outlet))
    unfloored = (source_inlet - temperature_change * (1 - 1 / efficiency)) / (
        1 + temperature_change / (efficiency * sink_outlet)
    )
    return ops.where(sink_outlet - floored > minimum_lift, unfloored, floored)


@ops.physics
def heating_cop_minimum_source(sink_outlet: float, efficiency: float) -> float:
    """Return the source temperature below which a Carnot-fraction heating COP is at most 1.

    Parameters
    ----------
    sink_outlet : float
        Sink outlet temperature [K].
    efficiency : float
        Carnot fraction [-].

    Returns
    -------
    float
        ``(1 - eta) T_h`` [K]: COP = eta T_h / (T_h - T_s) exceeds 1 above it.

    Notes
    -----
    Valid for a lift above the floor.
    """
    return (1 - efficiency) * sink_outlet


@ops.physics
def carnot_cooling_sink_outlet(
    sink_inlet: float,
    temperature_change: float,
    source_outlet: float,
    efficiency: float,
    minimum_lift: float,
) -> tuple:
    """Return the sink outlet temperature that closes the balance of a Carnot-fraction chiller.

    Parameters
    ----------
    sink_inlet : float
        Sink inlet temperature [K].
    temperature_change : float
        Duty over sink capacity rate Q / C [K], nonnegative.
    source_outlet : float
        Chilled outlet temperature [K].
    efficiency : float
        Carnot fraction [-].
    minimum_lift : float
        Lift floor [K].

    Returns
    -------
    tuple
        ``(y, within_floor, denominator)``: y [K] solving C (y - T_in) = Q (1 + 1 / COP) with
        COP = eta T_c / max(y - T_c, lift); with the floored lift
        y = T_in + dT (1 + lift / (eta T_c)) when that is within the floor, otherwise
        y = (T_in + dT (1 - 1 / eta)) / denominator. ``denominator = 1 - dT / (eta T_c)`` must be
        positive for the second form (a sink capacity rate above Q / (eta T_c)).

    Notes
    -----
    Closed form of a linear balance; first law of ``cooling_condenser_duty``. The caller checks
    the denominator where the floor does not apply.
    """
    floored = sink_inlet + temperature_change * (1 + minimum_lift / (efficiency * source_outlet))
    within_floor = floored - source_outlet <= minimum_lift
    denominator = 1 - temperature_change / (efficiency * source_outlet)
    unfloored = (sink_inlet + temperature_change * (1 - 1 / efficiency)) / denominator
    return ops.where(within_floor, floored, unfloored), within_floor, denominator


@ops.physics
def cooling_minimum_sink_rate(duty: float, efficiency: float, source_outlet: float) -> float:
    """Return the sink capacity rate [W/K] a Carnot-fraction chiller needs to reject its duty.

    Parameters
    ----------
    duty : float
        Cooling duty [W].
    efficiency : float
        Carnot fraction [-].
    source_outlet : float
        Chilled outlet temperature [K].

    Returns
    -------
    float
        ``Q / (eta T_c)`` [W/K], the bound of ``carnot_cooling_sink_outlet``'s denominator.

    Notes
    -----
    Valid for a lift above the floor.
    """
    return duty / (efficiency * source_outlet)


@ops.physics
def lorenz_source_surplus(
    source_outlet: float,
    source_rate: float,
    source_inlet: float,
    sink_inlet: float,
    sink_outlet: float,
    duty: float,
    efficiency: float,
    minimum_lift: float,
) -> float:
    """Return the evaporator balance surplus [W] of a Lorenz-fraction pump at a source outlet.

    Parameters
    ----------
    source_outlet : float
        Trial source outlet temperature x [K].
    source_rate : float
        Source capacity rate C [W/K].
    source_inlet, sink_inlet, sink_outlet : float
        Circuit temperatures [K].
    duty : float
        Heating duty Q [W].
    efficiency : float
        Lorenz fraction [-].
    minimum_lift : float
        Lift floor [K].

    Returns
    -------
    float
        ``C (T_in - x) - Q (1 - 1 / COP(x))`` [W], zero at the balanced source outlet.

    Notes
    -----
    A root-finding function of ``ops.brentq``; ``lorenz_fraction_cop_heating`` gives the COP.

    Validity: efficiency positive and the COP nonzero (the code divides by it); source_rate and duty
    nonnegative; all temperatures positive and minimum_lift >= 0 with a positive floored lift.
    """
    cop = lorenz_fraction_cop_heating(
        efficiency, minimum_lift, sink_inlet, sink_outlet, source_inlet, source_outlet
    )
    return source_rate * (source_inlet - source_outlet) - duty * (1 - 1 / cop)


@ops.physics
def source_limit_shortfall(
    cop_function,
    useful_duty: float,
    sink_inlet: float,
    sink_rate: float,
    source_inlet: float,
    source_limit: float,
    available: float,
    efficiency: float,
    minimum_lift: float,
) -> float:
    """Return the evaporator demand minus the available source heat [W] at a heating duty.

    Parameters
    ----------
    cop_function : callable
        Structural choice of the COP model: ``carnot_fraction_cop_heating`` or
        ``lorenz_fraction_cop_heating``.
    useful_duty : float
        Trial heating duty Q [W].
    sink_inlet, sink_rate : float
        Sink inlet temperature [K] and capacity rate [W/K].
    source_inlet, source_limit : float
        Source inlet temperature and its lowest allowed outlet [K].
    available : float
        Heat C_source (T_in - T_min) the source can give [W].
    efficiency : float
        Carnot or Lorenz fraction [-].
    minimum_lift : float
        Lift floor [K].

    Returns
    -------
    float
        ``Q (1 - 1 / COP) - available`` [W], with the sink outlet T_sink_in + Q / C_sink and the
        source outlet at its limit; zero at the duty that cools the source exactly to the limit.

    Notes
    -----
    A root-finding function of ``ops.brentq``, bound with ``functools.partial``.

    Validity: efficiency positive and the COP nonzero (the code divides by it); useful_duty and
    available nonnegative; sink_rate nonnegative, a zero rate gives a zero sink temperature rise;
    temperatures positive and minimum_lift >= 0 with a positive floored lift.
    """
    sink_outlet = sink_inlet + heat_transfer.temperature_change(useful_duty, sink_rate)
    cop = cop_function(
        efficiency, minimum_lift, sink_inlet, sink_outlet, source_inlet, source_limit
    )
    return useful_duty * (1 - 1 / cop) - available
