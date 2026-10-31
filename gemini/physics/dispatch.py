"""The daily energy balance of a schedule: what each doublet runs at for a heat need.

These are design-value estimates with no simulation inside; they run on arrays over the days.
"""

from gemini import ops
from gemini.physics import combustion, constants, refrigeration


@ops.physics
def doublet_flow(heat_need, heat_per_flow, minimum_flow, maximum_flow):
    """Return the volume flow of a doublet for a heat need, and the need it leaves.

    Parameters
    ----------
    heat_need : float
        Heat still needed [W], nonnegative.
    heat_per_flow : float
        Heat of a unit volume flow at the allowed brine cooling [J/m3], positive.
    minimum_flow, maximum_flow : float
        Flow limits of an active doublet [m3/s].

    Returns
    -------
    tuple of float
        ``(flow, remaining)``: the flow that gives the need, clipped to the limits, and zero
        without a need; below the minimum flow a doublet runs at the minimum with less cooling.
        ``remaining`` is the need the doublet does not cover [W].

    Notes
    -----
    The rule of thumb of the task: geothermal heat first, doublets in order.

    Validity: Positive limits with ``minimum_flow <= maximum_flow``.
    Source: A plain energy balance; no published source is needed.
    """
    wanted = ops.minimum(ops.maximum(heat_need / heat_per_flow, minimum_flow), maximum_flow)
    flow = ops.where(heat_need > 0, wanted, 0.0)
    return flow, ops.maximum(heat_need - flow * heat_per_flow, 0.0)


@ops.physics
def loaded_by_cost(demand, capacities, costs):
    """Return what each source takes of a demand when the cheapest is loaded first.

    Parameters
    ----------
    demand : float
        Demand [W], nonnegative.
    capacities : list of float
        Capacity of each source [W], in plant order.
    costs : list of float
        Marginal cost of each source [currency/J of heat], in the same order.

    Returns
    -------
    list of float
        The part of the demand each source takes [W], in the input order. Sources of equal cost
        load in input order; what no source takes is left over.

    Notes
    -----
    Each source takes the demand left after every source before it in the merit order, up to its
    capacity. The order is found by comparing costs, so it holds for arrays of costs that change
    from step to step.

    Validity: Nonnegative demand and capacities.
    Source: A plain merit order; no published source is needed.
    """
    taken = []
    for place, (capacity, cost) in enumerate(zip(capacities, costs)):
        before = 0.0
        for other, (other_capacity, other_cost) in enumerate(zip(capacities, costs)):
            first = (other_cost < cost) if other > place else (other_cost <= cost)
            if other != place:
                before = before + ops.where(first, other_capacity, 0.0)
        taken.append(ops.minimum(ops.maximum(demand - before, 0.0), capacity))
    return taken


@ops.physics
def marginal_cost(price, efficiency, co2_price, emission_factor):
    """Return the cost of a joule of heat or cold from a source.

    Parameters
    ----------
    price : float
        Price of the energy the source draws [currency/J].
    efficiency : float
        Heat or cold delivered per joule drawn [-], positive: a COP, a boiler efficiency or a
        thermal COP.
    co2_price : float
        Cost of a kilogram of CO2 [currency/kg].
    emission_factor : float
        CO2 emitted per joule drawn [kg/J].

    Returns
    -------
    float
        ``(price + co2_price * emission_factor) / efficiency`` [currency/J].

    Notes
    -----
    Validity: Positive efficiency.
    Source: A plain cost per unit of useful energy; no published source is needed.
    """
    return (price + co2_price * emission_factor) / efficiency


def methane_emission_factor():
    """Return the CO2 emitted per joule of methane burnt [kg/J], on the lower heating value.

    One mole of methane forms one mole of CO2 (stoichiometry), so a kilogram forms
    ``CO2_MOLAR_MASS / METHANE_MOLAR_MASS`` kilograms.
    """
    formed = float(constants.CO2_MOLAR_MASS) / float(combustion.METHANE_MOLAR_MASS)
    return formed / combustion.METHANE_HEATING_VALUE


def heat_pump_cop(heating, carnot_fraction, minimum_lift, sink_outlet, source_outlet):
    """Return the Carnot-fraction COP of a heat pump at design outlet temperatures.

    Parameters
    ----------
    heating : bool
        True for the condenser duty (heating), False for the evaporator duty (a chiller).
    carnot_fraction : float
        The share of the Carnot COP the machine reaches [-]; the caller gives it from the module,
        as ``HeatPump.carnot_fraction``, whose default states its source.
    minimum_lift : float
        Lift floor [K].
    sink_outlet, source_outlet : float
        Outlet temperatures [K] of the condenser and the evaporator circuits.

    Returns
    -------
    float
        The heating or cooling COP [-].

    Notes
    -----
    Validity: As ``refrigeration.carnot_fraction_cop_heating``.
    Source: the Carnot COP; the fraction is an argument, see ``refrigeration``.
    """
    function = (
        refrigeration.carnot_fraction_cop_heating
        if heating
        else refrigeration.carnot_fraction_cop_cooling
    )
    return function(
        carnot_fraction, minimum_lift, sink_outlet, sink_outlet, source_outlet, source_outlet
    )


@ops.physics
def temperature_after(start, end, share):
    """Return the temperature [K] of a water that went ``share`` of the way from start to end.

    Parameters
    ----------
    start, end : float
        Temperatures [K] at the two ends of a duty.
    share : float
        Part of the duty done [-], in [0, 1].

    Returns
    -------
    float
        ``start + share (end - start)``: at a constant flow and heat capacity the temperature
        moves in proportion to the duty.

    Notes
    -----
    Validity: Constant flow and specific heat over the duty.
    Source: The steady heat balance of a stream; no published source is needed.
    """
    return start + share * (end - start)


@ops.physics
def circuit_flow(heat, specific_heat, temperature_difference):
    """Return the mass flow [kg/s] of a water circuit that carries a heat rate.

    Parameters
    ----------
    heat : float
        Heat rate [W], nonnegative.
    specific_heat : float
        Specific heat [J/kg/K], positive.
    temperature_difference : float
        Supply and return difference [K], positive.

    Returns
    -------
    float
        ``m = Q / (cp dT)``.

    Notes
    -----
    Reference: the steady hydronic heat balance, ASHRAE Handbook, HVAC Systems and Equipment
    (2020), chapter 13.

    Validity: Liquid circuits at constant specific heat.
    Source: As in the reference.
    """
    return heat / (specific_heat * temperature_difference)


@ops.physics
def flow_share(first, second):
    """Return the share [-] of the first of two flows; one when both are zero.

    Parameters
    ----------
    first, second : float
        Flows or heat rates of the two branches, nonnegative.

    Returns
    -------
    float
        ``first / (first + second)``, in [0, 1].

    Notes
    -----
    Validity: Nonnegative inputs.
    Source: A plain ratio; no published source is needed.
    """
    return ops.where(first + second > 0, ops.truediv(first, first + second), 1.0)
