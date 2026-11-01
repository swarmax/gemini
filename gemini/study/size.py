"""Size the units of a plant for a case."""

from copy import deepcopy

from gemini import units
from gemini.analysis import solves
from gemini.analysis.wells import WELLHEAD_PRESSURES
from gemini.case._utils.access import require
from gemini.errors import PhysicsError, RunError, ValidationError
from gemini.evaluate import constraints
from gemini.modules.pumps import InjectionPump
from gemini.physics.fluid import FluidProperties, heat_capacity_rate
from gemini.plants._utils.roles import units_of
from gemini.run import simulate
from gemini.run._utils.apply import apply_case
from gemini.study._utils.resize import resized
from gemini.types import Stream

POLICIES = ("none", "peak")
"""The backup policies of ``size``."""


def _limit(case, quantity, bound, required=True):
    """Return the ``bound`` of the constraint on ``quantity`` of each doublet.

    Without it, ``None`` when not ``required``, else ``missing_value`` is raised.
    """
    for item in case.constraints or ():
        if (item.on, item.quantity, item.over) == ("doublet", quantity, "each"):
            if getattr(item, bound) is not None:
                return getattr(item, bound)
    if not required:
        return None
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
    """Return ``(plant, heat)``: the plant on the smallest number of doublets that covers ``peak``.

    ``heat`` is the heat [W] of all its doublets at the flow limit and the brine cooling limit.
    Each doublet is rated for the largest flow the case lets it run: the flow limit.
    """
    density = require(case, "environment.fluid.density")
    flow_max = _limit(case, "production_flow", "max")
    cooling_max = _limit(case, "brine_cooling", "max")
    heat = heat_capacity_rate(density * flow_max, FluidProperties().cp_l) * cooling_max
    count = len(units_of(plant, "doublet"))
    if _takes_doublets(plant):
        top = require(case, "choices.doublets")
        count = next(
            (n for n in range(int(top.min), int(top.max) + 1) if n * heat >= peak), top.max
        )
        design = resized(plant, int(count))
    else:
        design = deepcopy(plant)
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
    for path in units_of(design, "doublet"):
        design.set_params(path, {"nominal_flow": units.Quantity(flow_max, "m3/s")})
        _note(notes, f"{path}.nominal_flow", flow_max, "m3/s", "the flow limit of the case")
    return design, count * heat


def _closes_series(design, path):
    """Whether the chiller at ``path`` is the last of its chilled-water circuit."""
    module = design.get_submodule(path)
    port = "source_out" if hasattr(module, "source_out") else "chilled_out"
    chillers = set(units_of(design, "chiller")) - {path}
    return not chillers.intersection(design.feeds(f"{path}.{port}"))


def _boiler_peak(design, case, peak, backup, cover):
    """Return the heat [W] the boilers of the plant are rated for under the policy ``backup``."""
    if backup == "peak" or not units_of(design, "doublet"):
        return peak
    return max(peak - cover, _lift_share(design, case) * peak)


def _capacities(design, case, notes, backup, cover):
    """Set the capacity of each heat pump, boiler and chiller from the demand peaks."""
    for role, service in (("boiler", "heating"), ("heat_pump", "heating"), ("chiller", "cooling")):
        paths = units_of(design, role)
        if not paths:
            continue
        peak = _peak(case, service)
        if role == "heat_pump":
            part = _lift_share(design, case)
            duty = part * peak
        elif role == "boiler":
            duty = _boiler_peak(design, case, peak, backup, cover)
            part = duty / peak
        else:
            part, duty = 1.0, peak
        if duty <= 0:
            why = (
                "the reservoir is hotter than the heating supply temperature"
                if role == "heat_pump"
                else "the doublets cover the whole heating peak"
            )
            _skip(notes, paths, why)
            continue
        for path in paths:
            if role == "chiller" and _closes_series(design, path):
                value, reason = peak, f"the whole {service} peak of {peak:.4g} W: it closes the series"
            else:
                value = duty / len(paths)
                reason = (
                    f"{part:.3g} of the {service} peak of {peak:.4g} W "
                    f"shared by {len(paths)} {role} unit(s)"
                )
            design.set_params(path, {"capacity": units.Quantity(value, "W")})
            _note(notes, f"{path}.capacity", value, "W", reason)
    for role in ("chp", "heat_exchanger"):
        _skip(notes, units_of(design, role), "not sized from the demand")


def _injection_head(applied, case, path):
    """Return the pressure rise [Pa] that the doublet at ``path`` asks of an injection pump.

    The wellhead pressure that injects the nominal flow, less the pressure of the production
    wellhead (``nominal_wellhead_pressure``), which the pump suction can be at best; zero when the
    column of brine injects the flow alone. The brine is injected at the reservoir temperature
    less the brine cooling limit.
    """
    doublet = applied.get_submodule(path)
    cooling = _limit(case, "brine_cooling", "max")
    temperature = case.environment.temperature_at(doublet.depth) - cooling
    rate = doublet.fluid.density * doublet.nominal_flow
    stream = Stream(
        m_dot=rate, T=temperature, p=doublet.nominal_wellhead_pressure, fluid=doublet.fluid
    )
    low = float(doublet.nominal_wellhead_pressure)
    needed = solves.solve_injection_pressure(
        doublet.injector, doublet.sink, stream, (low, WELLHEAD_PRESSURES[1])
    )
    return 0.0 if needed is None else needed - low


def _lacking(applied, served):
    """Return why a pump cannot be rated for the doublets ``served``, or ``None`` when it can."""
    if not served:
        return "it serves no doublet of the plant"
    for path in served:
        doublet = applied.get_submodule(path)
        for name in ("depth", "nominal_flow", "nominal_wellhead_pressure"):
            if getattr(doublet, name) is None:
                return f"{path}.{name} is missing"
    return None


def _injection_pumps(design, case, notes):
    """Rate each injection pump for the doublets it serves: their total flow and the head.

    A pump serves the doublets that its brine reaches in the plant, found from the wiring. The
    nominal flow is the sum of their nominal flows and the nominal head the largest head one of
    them asks (``_injection_head``), floored at zero. A pump that serves no doublet of the plant,
    or whose doublets lack a design value, is left unsized with a note.
    """
    pumps = [path for path, module in design.named_modules() if isinstance(module, InjectionPump)]
    if not pumps:
        return
    applied = apply_case(design, case)
    doublets = units_of(design, "doublet")
    for path in pumps:
        served = [item for item in design.feeds(f"{path}.fluid_out") if item in doublets]
        reason = _lacking(applied, served)
        if reason:
            _skip(notes, [path], f"not sized: {reason}")
            continue
        flow = sum(applied.get_submodule(item).nominal_flow for item in served)
        head = max(_injection_head(applied, case, item) for item in served)
        values = {"nominal_flow": units.Quantity(flow, "m3/s")}
        values["nominal_head"] = units.Quantity(head, "Pa")
        design.set_params(path, values)
        why = f"the flow of {len(served)} doublet(s) it serves, and the head that injects it"
        _note(notes, f"{path}.nominal_flow", flow, "m3/s", why)
        _note(notes, f"{path}.nominal_head", head, "Pa", why)


def _skip(notes, paths, reason):
    """Record the units a size was not computed for."""
    notes["unchanged"].extend({"path": path, "reason": reason} for path in paths)


def _lift_share(design, case):
    """Return the part of the heating peak that the reservoir cannot reach by itself, 0 to 1.

    ``(supply - reservoir) / (supply - return)`` with the reservoir temperature at the depth of the
    plant: the water of the heating network warms to the reservoir temperature in the exchanger
    and the heat pump lifts it the rest of the way. Zero when the reservoir is hotter than the
    supply temperature.
    """
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
    back = require(case, "demand.heating.return_temperature")
    reservoir = case.environment.temperature_at(depth)
    return min(1.0, max(0.0, (supply - reservoir) / (supply - back)))


def _check(design, case, notes):
    """Simulate the sized plant once and note each constraint it breaks."""
    notes["broken"] = []
    try:
        results = simulate(design, case)
    except (ValidationError, PhysicsError, RunError) as error:
        notes["simulation"] = f"not simulated: {error.code}: {error}"
        return
    notes["simulation"] = "simulated"
    for item in constraints(design, case, results):
        if item["passed"] is False:
            notes["broken"].append(
                {
                    key: item[key]
                    for key in ("unit_path", "role", "quantity", "value", "limit", "worst_step")
                }
            )


def size(plant, case, backup=None):
    """Return a new plant with first sizes from the case; the plant itself is not changed.

    The sizes use gemini physics only. In order:

    - the number of doublets, the smallest in ``case.choices.doublets`` whose heat at the flow
      limit and the brine cooling limit of the case's constraints covers the heating peak (the
      largest, with a note, when none does), for a plant class that takes the structural size
      ``doublets``; the nominal flow of each doublet is the flow limit, the largest flow the case
      lets it run, so that its share in ``gm.evaluate.capacities`` is at most one;
    - the capacity of each ``boiler`` by the policy ``backup`` (below); the capacity of each
      ``heat_pump``: the part of the heating peak the reservoir cannot reach, ``(supply -
      reservoir) / (supply - return)`` of it, shared by the units of the role, the reservoir
      temperature taken at the depth of the plant and the temperatures from ``demand.heating`` (a
      heat pump is left unsized, with a note, when the reservoir is hotter than the supply
      temperature); the capacity of each ``chiller``: the cooling peak shared by the units, except
      the chiller that closes the chilled-water series, which gets the whole peak because a
      sorption unit delivers less than its rating when its characteristic map says so at the peak
      conditions and the last chiller makes up the difference;
    - the ``nominal_flow`` and ``nominal_head`` of each ``InjectionPump``: the total nominal flow
      of the doublets its brine reaches, and the largest pressure rise one of them asks, the
      wellhead pressure that injects its flow less ``nominal_wellhead_pressure`` as the best
      suction, floored at zero (the injection well and aquifer of the case, ``gm.analysis``'s
      ``solve_injection_pressure``). A pump that serves no doublet of the plant, such as the one
      of a ``NodalDoublet``, or whose doublet lacks a depth or a wellhead pressure, is left
      unsized with a note.

    The heat pump share assumes an ideal exchanger: a finite approach leaves the water colder at
    the heat pump, which a boiler downstream makes up; a plant with a heat pump and no boiler may
    then fall short of its supply temperature at the peak.

    A size that is not computed for a module kind (``chp``, ``heat_exchanger``, a heat pump that
    is not needed) leaves it unchanged and lists it. The sized plant is then simulated once on the
    case and every constraint it breaks is listed: size never hides an infeasible start.

    Parameters
    ----------
    plant : Plant
        A plant with parameter values.
    case : Case
        The demand, the constraints on each doublet (a maximum production flow and brine cooling),
        the choices of doublets, the reservoir and the fluid.
    backup : str
        The design policy of the top-up units, required (it has no default):

        - ``"none"``: a boiler covers only the heat the doublets cannot reach, the larger of the
          heating peak less the heat of the doublets at their limits and the part of the peak
          that the reservoir temperature cannot reach; a plant without doublets gets the peak;
        - ``"peak"``: a boiler covers the whole heating peak with the doublets off, so that it
          carries the peak when a doublet is out.

    Returns
    -------
    Plant
        A new plant. Its attribute ``sizing`` holds the notes: ``{"sized": [...], "unchanged":
        [...], "broken": [...], "simulation": str}``. Each size is ``{path, value, reason}`` with a
        ``Quantity`` value, each unit left unchanged ``{path, reason}``, each broken constraint
        ``{unit_path, role, quantity, value, limit, worst_step}`` as ``gm.evaluate.constraints``
        gives it, and ``simulation`` says ``simulated``, or ``not simulated: <code>: <reason>`` when the
        sized plant cannot run (a value it still lacks, a design the case refuses).

    Raises
    ------
    ValidationError
        ``missing_value`` naming ``backup`` or the path of what a size needs and the case or plant
        lacks; ``invalid_value`` for a ``backup`` that is not a policy; ``invalid_design`` for a
        plant that has doublets but whose class takes no structural size ``doublets``.
    """
    if backup is None:
        raise ValidationError(
            f"backup is missing; expected one of {POLICIES} (it has no default)",
            path="backup",
            code="missing_value",
        )
    if backup not in POLICIES:
        raise ValidationError(
            f"backup = {backup!r}; expected one of {POLICIES}", path="backup", code="invalid_value"
        )
    require(case, "demand")
    notes = {"sized": [], "unchanged": []}
    design, cover = deepcopy(plant), 0.0
    if units_of(plant, "doublet"):
        design, cover = _doublets(plant, case, _peak(case, "heating"), notes)
    _capacities(design, case, notes, backup, cover)
    _injection_pumps(design, case, notes)
    _check(design, case, notes)
    design.sizing = notes
    return design
