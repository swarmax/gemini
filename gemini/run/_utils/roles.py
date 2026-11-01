"""What each unit of a plant is for: read from the wiring, not from its class.

A unit whose useful outlet feeds the ``HeatingGrid``, directly or through other modules of the
circuit, is a heating unit, and one that feeds the ``CoolingGrid`` a cooling unit
(``gemini.case.roletable.units_of``). A ``HeatPump`` is
either: its ``sink_out`` heats, and its ``source_out`` cools as a compression chiller. Its condenser
then rejects to a cooler, which is the environment.
"""

from gemini._utils.strings import join_path
from gemini.case.roletable import units_of
from gemini.errors import ValidationError
from gemini.modules.cooling import AbsorptionUnit, AdsorptionChiller
from gemini.modules.heating import HeatPump

COOLING_KINDS = ("absorption", "adsorption", "compression")
"""The kinds of cooling unit, heat-driven first."""
HEAT_DRIVEN = ("absorption", "adsorption")
"""The kinds of cooling unit whose drive heat adds to the heat need."""
CHILLERS = {"absorption": AbsorptionUnit, "adsorption": AdsorptionChiller}
"""The class of each heat-driven kind."""


def _one(found, label):
    """Return the only item of ``found``, or ``None``; more than one breaks the design."""
    if len(found) > 1:
        raise ValidationError(
            f"schedule: {len(found)} units of role {label}: {', '.join(found)}; expected at most "
            "one per role and kind",
            code="invalid_design",
        )
    return found[0] if found else None


def heat_pumps(plant):
    """Return ``(heating, cooling)``, the paths of the heat pumps of each role, or ``None``."""
    heating = units_of(plant, "heat_pump")
    cooling = [
        path
        for path in units_of(plant, "chiller")
        if isinstance(plant.get_submodule(path), HeatPump)
    ]
    both = set(heating) & set(cooling)
    if both:
        raise ValidationError(
            f"schedule: {', '.join(sorted(both))} feeds both grids; expected one role, because a "
            "heat pump has one setpoint",
            code="invalid_design",
        )
    return _one(heating, "heating heat pump"), _one(cooling, "compression chiller")


def cooling_units(plant):
    """Return ``{kind: path}`` of the cooling units of ``plant``."""
    units = {"compression": heat_pumps(plant)[1]}
    for kind, chiller in CHILLERS.items():
        found = [
            path
            for path in units_of(plant, "chiller")
            if isinstance(plant.get_submodule(path), chiller)
        ]
        units[kind] = _one(found, f"{kind} chiller")
    return {kind: units[kind] for kind in COOLING_KINDS if units[kind] is not None}


def setpoint(plant, path):
    """Return the ``temperature_setpoint`` of the design module at ``path``, or raise saying so."""
    name = join_path(path, "temperature_setpoint")
    value = plant.input_value(name)
    if value is None:
        raise ValidationError(
            f"schedule: {name} has no value; expected the supply setpoint of the design, set "
            "with plant.set_inputs",
            path=name,
            code="invalid_design",
        )
    return value
