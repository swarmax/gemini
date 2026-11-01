"""The roles of a plant: what each unit is for, its quantities, and how to find its units.

A role is found from the class of a module and, for a heat pump and a chiller, from the grid its
outlet reaches, never from a module name. ``roles()`` lists the closed table; the private table
below says, for each quantity of a role, its dimension, the result field or parameter it reads
below the unit, and how it is read: ``result`` (an output or port field of the unit),
``parameter``, ``delivery`` (the power the unit gives its circuit, from the enthalpy flows of its
ports) or ``plant`` (a figure of the plant as a whole, read from the edge modules as
``gm.evaluate.totals`` and ``gm.evaluate.co2`` read them).
"""

from collections import namedtuple

from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import ValidationError

Reads = namedtuple("Reads", "dimension path source")
"""One quantity of a role: the dimension of its bounds, the path below the unit (the name of the
figure for ``delivery`` and ``plant``), and ``result``, ``parameter``, ``delivery`` or ``plant``."""

TABLE = {
    "doublet": {
        "production_flow": Reads("volume_flow", "reservoir.liquid_flow", "result"),
        "brine_cooling": Reads("temperature_difference", "brine_cooling", "result"),
        "production_temperature": Reads("temperature", "riser.wellhead_out.temperature", "result"),
        "injection_temperature": Reads("temperature", "injector.wellhead_in.temperature", "result"),
        "pump_power": Reads("power", "esp.power_in", "result"),
        "pump_efficiency": Reads("efficiency", "pump_efficiency", "parameter"),
        "intake_pressure": Reads("pressure", "esp.intake_pressure", "result"),
        "intake_gas_fraction": Reads("fraction", "esp.gas_volume_fraction", "result"),
        "volume_imbalance": Reads("volume_flow", "volume_imbalance", "result"),
        "wellhead_pressure": Reads("pressure", "riser.wellhead_out.pressure", "result"),
    },
    "heat_pump": {
        "cop": Reads("ratio", "cop", "result"),
        "lift": Reads("temperature_difference", "temperature_lift", "result"),
        "heat_output": Reads("power", "heat_output", "delivery"),
    },
    "boiler": {
        "fuel_input": Reads("power", "fuel", "result"),
        "heat_output": Reads("power", "heat_output", "delivery"),
    },
    "chp": {
        "power_output": Reads("power", "power_out", "result"),
        "heat_output": Reads("power", "heat_output", "delivery"),
    },
    "chiller": {
        "cop": Reads("ratio", "cop", "result"),
        "cold_output": Reads("power", "cold_output", "delivery"),
    },
    "heat_exchanger": {
        "duty": Reads("power", "duty", "result"),
        "approach": Reads("temperature_difference", "approach_temperature", "result"),
    },
    "heating_supply": {
        "temperature": Reads("temperature", "supply_in.temperature", "result"),
        "unmet": Reads("power", "unmet_demand", "result"),
    },
    "cooling_supply": {
        "temperature": Reads("temperature", "supply_in.temperature", "result"),
        "unmet": Reads("power", "unmet_sensible", "result"),
    },
    "plant": {
        "electricity_bought": Reads("power", "electricity_bought", "plant"),
        "gas_bought": Reads("power", "gas_bought", "plant"),
        "heat_surplus": Reads("power", "heat_surplus", "plant"),
        "co2": Reads("mass", "co2", "plant"),
    },
}
"""``{role: {quantity: Reads}}``: the one table of roles."""


def roles():
    """Return the closed table of roles as ``{role: [quantities]}``.

    A constraint is on a role and a quantity of it. The roles are ``doublet``, ``heat_pump``,
    ``boiler``, ``chp``, ``chiller`` (absorption, adsorption and compression), ``heat_exchanger``,
    ``heating_supply``, ``cooling_supply`` and ``plant``.

    ``heat_output`` of ``heat_pump``, ``boiler`` and ``chp`` is the heat the unit gives its water
    and ``cold_output`` of ``chiller`` the cold it takes from its chilled water, in W, from the
    enthalpy flows of its ports (the source side for a heat pump in cooling mode). The role
    ``plant`` is the plant itself (``unit_path`` ``""``): ``electricity_bought``, ``gas_bought``
    and ``heat_surplus`` are powers in W as ``gm.evaluate.totals`` sums them; ``co2`` is the mass
    in kg of CO2-equivalent emitted in each step, as ``gm.evaluate.co2`` sums it, so ``over:
    sum`` of it is the mass of the run (``over: each`` judges the mass of a step, which depends
    on its length). ``sum`` of a power adds the step values, as for every other power.
    """
    return {role: list(quantities) for role, quantities in TABLE.items()}


def check_role(role):
    """Return ``role`` or raise ``unknown_name`` listing the roles."""
    if role not in TABLE:
        raise ValidationError(
            f"role {role!r} is unknown; expected one of {join_names(TABLE)}"
            f"{did_you_mean(role, TABLE)}",
            suggestions=close_matches(role, TABLE),
            code="unknown_name",
        )
    return role


def reads(role, quantity):
    """Return the ``Reads`` of ``quantity`` of ``role``, or raise saying what the role has."""
    check_role(role)
    if quantity not in TABLE[role]:
        raise ValidationError(
            f"{quantity!r} is not a quantity of {role!r}; expected one of "
            f"{join_names(TABLE[role])}{did_you_mean(quantity, TABLE[role])}",
            suggestions=close_matches(quantity, TABLE[role]),
            code="invalid_value",
        )
    return TABLE[role][quantity]
