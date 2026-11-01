"""The constraints of a case, checked against a finished run."""

import numpy as np

from gemini._utils.strings import join_path
from gemini.case import Constraint
from gemini.case._utils.fields import si_unit_of
from gemini.case.roletable import reads
from gemini.errors import ValidationError
from gemini.evaluate._utils.columns import (
    field_of,
    fields,
    is_parameter,
    parameter_values,
    series,
)
from gemini.plants._utils.roles import units_of
from gemini.run._utils.apply import apply_case
from gemini.types.shapes import check, measure
from gemini.units import Quantity

TOLERANCE = 1e-9
"""Relative margin of a limit: a value on the limit passes through its rounding; numerical."""

AGGREGATES = {"sum": np.sum, "mean": np.mean, "max": np.max, "min": np.min}
"""How a constraint with ``over`` other than ``each`` and ``duration`` reads the run."""

NO_VALUE = "no_value: the run gives no value of this field"
"""The reason when the field is not among the results."""

NO_FLOW = "the module carried no flow in this run"
"""The reason when ``when="running"`` leaves no step."""


def constraints(plant, case, results):
    """Check every constraint of ``case`` and the supply temperatures of its services.

    A ``Constraint`` is on a role and a quantity of it (``gm.case.roles()``); it applies to every
    unit of the role in ``plant`` on its own, the units being found by class and wiring. A result
    field is read over the run, a composite's through the leaves its formula names; with
    ``when="running"`` only the steps in which the module carried flow count. ``over`` gives how
    the run is read: ``each`` judges every step and reports the worst; ``sum``, ``mean``, ``max``
    and ``min`` judge one figure of the run; ``duration`` judges the total time of the steps
    that count. A parameter is judged once, or at each date inside the run when it changes over
    time, with the case applied to the plant. A value on a limit passes within ``TOLERANCE``, a
    duration within half a step.

    The service requirement is checked as well: each ``HeatingGrid`` must receive water at least at
    ``demand.heating.supply_temperature`` and each ``CoolingGrid`` at most at
    ``demand.cooling.supply_temperature``, in the steps in which it runs. A service without a
    supply temperature adds no check. A role with no unit in the plant gives one check with
    ``passed`` ``None`` and ``unit_path`` ``None``, whose value says ``no_value``.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    case : Case
        The case whose constraints and services are checked, and that gives design values.
    results : Results
        A finished run.

    Returns
    -------
    list of dict
        One check ``{name, role, unit_path, quantity, passed, value, limit, worst_step}`` per unit
        and constraint: ``name`` is ``<unit path>.<field>``, ``role`` and ``quantity`` those of the
        constraint, ``unit_path`` the path of the unit (``""`` for the plant). ``value`` is a
        ``Quantity`` (SI, ``s`` for ``duration``): the worst value of the run for ``each`` and the
        figure otherwise, and ``limit`` the bound that was violated, else the nearest.
        ``worst_step`` is the ISO 8601 time of the worst step, ``None`` for a figure of the run and
        for a parameter. ``passed`` is ``None``, with the reason in ``value``, for a unit that
        carried no flow, and with ``no_value`` for a field the run does not hold.

    Raises
    ------
    ValidationError
        With code ``unknown_name`` for a role quantity that a unit of the plant does not hold.
    """
    frame = results.to_frame()
    sited = apply_case(plant, case)
    checks = []
    for constraint in (*(case.constraints or ()), *_services(case)):
        found = units_of(sited, constraint.on)
        if not found:
            checks.append(_no_unit(constraint))
        checks += [_check(sited, frame, results.durations, constraint, path) for path in found]
    return checks


def _no_unit(constraint):
    """Return the undecided check of a constraint whose role has no unit in the plant."""
    unit = "s" if constraint.over == "duration" else si_unit_of(constraint.dimension)
    lower, upper = _bounds(constraint)
    reason = f"no_value: the plant has no unit of the role {constraint.on!r}"
    name = f"{constraint.on}.{constraint.quantity}"
    limit = measure(lower if lower is not None else upper, unit)
    verdict = check(name, None, measure(None, unit, reason), limit)
    return verdict | _where(constraint, None, None)


def _services(case):
    """Return the constraints that the supply temperatures of the services of ``case`` make."""
    demand = case.demand
    if demand is None:
        return []
    required = [
        (demand.heating, "heating_supply", "min"),
        (demand.cooling, "cooling_supply", "max"),
    ]
    return [
        Constraint(
            on=role,
            quantity="temperature",
            when="running",
            **{bound: Quantity(service.supply_temperature, "K")},
        )
        for service, role, bound in required
        if service is not None and service.supply_temperature is not None
    ]


def _bounds(constraint):
    """Return ``(lower, upper)`` of a constraint; ``equals`` sets both."""
    lower = [bound for bound in (constraint.min, constraint.equals) if bound is not None]
    upper = [bound for bound in (constraint.max, constraint.equals) if bound is not None]
    return (max(lower) if lower else None, min(upper) if upper else None)


def _reading(plant, frame, constraint, path, name):
    """Return ``(values, keep)`` of a field: its values and the steps that count."""
    if is_parameter(plant, path, name):
        if constraint.over != "each":
            raise ValidationError(
                f"constraint {constraint.on}.{constraint.quantity}: over = {constraint.over!r}; "
                "expected 'each' for a parameter",
                path=f"{constraint.on}.{constraint.quantity}",
                code="invalid_value",
            )
        values = parameter_values(plant, frame, path, name)
        return values, np.isfinite(values)
    values, active = series(plant, frame, path, name)
    keep = np.isfinite(values)
    return values, keep & active if constraint.when == "running" else keep


def _worst_index(values, lower, upper):
    """Return the position of the value furthest out, or nearest the limit inside."""
    if upper is None:
        return int(values.argmin())
    if lower is None:
        return int(values.argmax())
    low, high = int(values.argmin()), int(values.argmax())
    return low if lower - values[low] > values[high] - upper else high


def _measure(constraint, values, keep, durations, bounds):
    """Return ``(measured, margin, position)``; ``position`` is the worst step of ``each``."""
    if constraint.over == "duration":
        return float(durations[keep].sum()), float(np.median(durations)) / 2, None
    judged = values[keep]
    if constraint.over == "each":
        worst = _worst_index(judged, *bounds)
        return float(judged[worst]), TOLERANCE * abs(judged[worst]), int(keep.nonzero()[0][worst])
    measured = float(AGGREGATES[constraint.over](judged))
    return measured, TOLERANCE * abs(measured), None


def _nearest(measured, lower, upper):
    """Return the bound that was violated, else the one nearest to ``measured``."""
    if lower is None or upper is None:
        return upper if lower is None else lower
    if measured < lower or measured > upper:
        return lower if measured < lower else upper
    return lower if measured - lower <= upper - measured else upper


def _no_reason(values, keep, over):
    """Return why nothing can be judged, or ``None``."""
    if not values.size or np.isnan(values).all():
        return NO_VALUE
    if over != "duration" and not keep.any():
        return NO_FLOW
    return None


def _check(plant, frame, durations, constraint, unit_path):
    """Return the check of one constraint on one unit of its role."""
    read = reads(constraint.on, constraint.quantity)
    path, name = field_of(plant, join_path(unit_path, read.path))
    unit = "s" if constraint.over == "duration" else fields(plant, path)[name][0]
    bounds = _bounds(constraint)
    values, keep = _reading(plant, frame, constraint, path, name)
    label = join_path(path, name)
    reason = _no_reason(values, keep, constraint.over)
    if reason:
        limit = measure(bounds[0] if bounds[0] is not None else bounds[1], unit)
        verdict = check(label, None, measure(None, unit, reason), limit)
        return verdict | _where(constraint, unit_path, None)
    measured, margin, position = _measure(constraint, values, keep, durations, bounds)
    lower, upper = bounds
    passed = (lower is None or measured >= lower - margin) and (
        upper is None or measured <= upper + margin
    )
    step = None if position is None or is_parameter(plant, path, name) else frame.index[position]
    limit = measure(_nearest(measured, lower, upper), unit)
    verdict = check(label, bool(passed), measure(measured, unit), limit)
    return verdict | _where(constraint, unit_path, step)


def _where(constraint, unit_path, step):
    """Return the keys that tell which constraint and unit a check answers and when it was worst."""
    return {
        "role": constraint.on,
        "unit_path": unit_path,
        "quantity": constraint.quantity,
        "worst_step": None if step is None else step.isoformat(),
    }
