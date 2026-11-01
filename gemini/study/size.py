"""Size the units of a plant for a case."""

from copy import deepcopy

from gemini import units
from gemini.case._utils.access import require
from gemini.errors import ValidationError
from gemini.physics.fluid import FluidProperties, heat_capacity_rate
from gemini.plants._utils.roles import units_of
from gemini.study._utils.resize import resized


def _limit(case, quantity, bound, required=True):
    """Return the ``bound`` of the constraint on ``quantity`` of each doublet, or raise."""
    for item in case.constraints or ():
        if (item.on, item.quantity, item.over) == ("doublet", quantity, "each"):
            if getattr(item, bound) is not None:
                return getattr(item, bound)
    if not required:
        return 0.0
    raise ValidationError(
        f"constraints is missing a {bound} of {quantity} on each doublet; expected a value in the "
        "case (it has no default)",
        path="constraints",
        code="missing_value",
    )


def _peak(case, service):
    """Return the largest demand [W] of ``heating`` or ``cooling``, or raise ``missing_value``."""
    require(case, f"demand.{service}")
    return float(case.demand.frame[f"{service}_demand"].max())


def _note(notes, path, value, unit, reason):
    """Record one size and the reason for it."""
    notes["sized"].append({"path": path, "value": units.Quantity(value, unit), "reason": reason})


def _takes_doublets(plant):
    """Whether the class of the plant takes the structural size ``doublets``."""
    return "doublets" in (plant.to_dict().get("size") or {})


def _doublets(plant, case, peak, notes):
    """Return the plant on the smallest number of doublets that covers ``peak``, flows set."""
    density = require(case, "environment.fluid.density")
    flow_max = _limit(case, "production_flow", "max")
    cooling_max = _limit(case, "brine_cooling", "max")
    heat = heat_capacity_rate(density * flow_max, FluidProperties().cp_l) * cooling_max
    design = deepcopy(plant)
    count = len(units_of(plant, "doublet"))
    if _takes_doublets(plant):
        top = require(case, "choices.doublets")
        count = next(
            (n for n in range(int(top.min), int(top.max) + 1) if n * heat >= peak), top.max
        )
        design = resized(plant, int(count))
    covered = "covers" if count * heat >= peak else "does not cover"
    notes["sized"].append(
        {
            "path": "size.doublets",
            "value": units.Quantity(count, "-"),
            "reason": f"{count} doublet(s) of {heat:.4g} W each at the flow limit {flow_max:.4g} "
            f"m3/s and the brine cooling limit {cooling_max:.4g} K {covered} the heating peak "
            f"of {peak:.4g} W",
        }
    )
    need = peak / (count * heat_capacity_rate(density, FluidProperties().cp_l) * cooling_max)
    flow = max(_limit(case, "production_flow", "min", required=False), min(flow_max, need))
    for path in units_of(design, "doublet"):
        design.set_params(path, {"nominal_flow": units.Quantity(flow, "m3/s")})
        _note(
            notes, f"{path}.nominal_flow", flow, "m3/s", "the heating peak shared by the doublets"
        )
    return design


def _capacities(design, case, notes):
    """Set the capacity of each heat pump, boiler and chiller from the demand peaks."""
    for role, service in (("boiler", "heating"), ("heat_pump", "heating"), ("chiller", "cooling")):
        paths = units_of(design, role)
        if not paths:
            continue
        peak = _peak(case, service)
        if role == "heat_pump" and not _needs_heat_pump(design, case):
            _skip(notes, paths, "the reservoir is hotter than the heating supply temperature")
            continue
        share = peak / len(paths)
        for path in paths:
            design.set_params(path, {"capacity": units.Quantity(share, "W")})
            reason = f"the {service} peak of {peak:.4g} W shared by {len(paths)} {role} unit(s)"
            _note(notes, f"{path}.capacity", share, "W", reason)
    for role in ("chp", "heat_exchanger"):
        _skip(notes, units_of(design, role), "not sized from the demand")


def _skip(notes, paths, reason):
    """Record the units a size was not computed for."""
    notes["unchanged"].extend({"path": path, "reason": reason} for path in paths)


def _needs_heat_pump(design, case):
    """Whether the reservoir at the depth of the plant is colder than the heating supply."""
    depth = getattr(design, "depth", None)
    if depth is None:
        doublet = units_of(design, "doublet")
        depth = design.get_submodule(doublet[0]).depth if doublet else None
    if depth is None:
        raise ValidationError(
            "depth is missing; expected a value of the plant (it has no default)",
            path="depth",
            code="missing_value",
        )
    supply = require(case, "demand.heating.supply_temperature")
    return case.environment.temperature_at(depth) < supply


def size(plant, case):
    """Return a new plant with first sizes from the case; the plant itself is not changed.

    The sizes use gemini physics only. In order:

    - the number of doublets, the smallest in ``case.choices.doublets`` whose heat at the flow
      limit and the brine cooling limit of the case's constraints covers the heating peak (the
      largest, with a note, when none does), for a plant class that takes the structural size
      ``doublets``; the nominal flow of each doublet, the heating peak shared by them, kept
      within the flow limits;
    - the capacity of each ``boiler`` and, when the reservoir at the depth of the plant is colder
      than the heating supply temperature, of each ``heat_pump``: the heating peak shared by the
      units of the role; the capacity of each ``chiller``: the cooling peak shared likewise.

    A size that is not computed for a module kind (``chp``, ``heat_exchanger``, a heat pump that
    is not needed) leaves it unchanged and lists it.

    Parameters
    ----------
    plant : Plant
        A plant with parameter values.
    case : Case
        The demand, the constraints on each doublet (a maximum production flow and brine cooling),
        the choices of doublets, the reservoir and the fluid.

    Returns
    -------
    Plant
        A new plant. Its attribute ``sizing`` holds the note: ``{"sized": [...], "unchanged":
        [...]}``, each size ``{path, value, reason}`` with a ``Quantity`` value and each unit left
        unchanged ``{path, reason}``.

    Raises
    ------
    ValidationError
        ``missing_value`` naming the path of what a size needs and the case or plant lacks;
        ``invalid_design`` for a plant that has doublets but whose class takes no structural size
        ``doublets``.
    """
    require(case, "demand")
    notes = {"sized": [], "unchanged": []}
    design = deepcopy(plant)
    if units_of(plant, "doublet"):
        design = _doublets(plant, case, _peak(case, "heating"), notes)
    _capacities(design, case, notes)
    design.sizing = notes
    return design
