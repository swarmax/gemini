"""The roles of a plant: what each unit is for, its quantities, and how to find its units.

A role is found from the class of a module and, for a heat pump and a chiller, from the grid its
outlet reaches, never from a module name. ``roles()`` lists the closed table; the private table
below says, for each quantity of a role, its dimension, the result field or parameter it reads
below the unit, and whether that is a result or a parameter.
"""

from collections import namedtuple

from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import ValidationError
from gemini.plants._utils import roles as by_class

Reads = namedtuple("Reads", "dimension path source")
"""One quantity of a role: the dimension of its bounds, the path below the unit, ``result`` or
``parameter``."""

TABLE = {
    "doublet": {
        "production_flow": Reads("volume_flow", "reservoir.liquid_flow", "result"),
        "brine_cooling": Reads("temperature_difference", "brine_cooling", "result"),
        "production_temperature": Reads("temperature", "riser.wellhead_out.temperature", "result"),
        "injection_temperature": Reads("temperature", "injector.wellhead_in.temperature", "result"),
        "pump_power": Reads("power", "esp.power_in", "result"),
        "pump_efficiency": Reads("efficiency", "pump_efficiency", "parameter"),
        "volume_imbalance": Reads("volume_flow", "volume_imbalance", "result"),
        "wellhead_pressure": Reads("pressure", "riser.wellhead_out.pressure", "result"),
    },
    "heat_pump": {
        "cop": Reads("ratio", "cop", "result"),
        "lift": Reads("temperature_difference", "temperature_lift", "result"),
    },
    "boiler": {
        "fuel_input": Reads("power", "fuel", "result"),
    },
    "chp": {
        "power_output": Reads("power", "power_out", "result"),
    },
    "chiller": {
        "cop": Reads("ratio", "cop", "result"),
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
}
"""``{role: {quantity: Reads}}``: the one table of roles."""


def roles():
    """Return the closed table of roles as ``{role: [quantities]}``.

    A constraint is on a role and a quantity of it. The roles are ``doublet``, ``heat_pump``,
    ``boiler``, ``chp``, ``chiller`` (absorption, adsorption and compression), ``heat_exchanger``,
    ``heating_supply`` and ``cooling_supply``.
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


def units_of(plant, role):
    """Return the paths of the units of ``role`` in ``plant``, found by class and wiring.

    The roles are decided by ``gemini.plants._utils.roles``: a heat pump is a ``heat_pump`` when
    its ``sink_out`` reaches a ``HeatingGrid`` and a ``chiller`` when its ``source_out`` reaches a
    ``CoolingGrid``; an absorption or adsorption unit is a ``chiller`` when its ``chilled_out``
    reaches a ``CoolingGrid``. A plant without such a unit gives ``[]``.
    """
    return by_class.units_of(plant, check_role(role))
