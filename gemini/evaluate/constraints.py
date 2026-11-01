"""The constraints of a problem, checked against a finished run."""

import numpy as np

from gemini import units
from gemini._utils.strings import join_path
from gemini.errors import ValidationError
from gemini.evaluate._utils.columns import (
    fields,
    is_parameter,
    matched,
    parameter_values,
    series,
)
from gemini.types.shapes import check, measure

TOLERANCE = 1e-9
"""Relative margin of a limit: a value on the limit passes through its rounding; numerical."""

AGGREGATES = {"sum": np.sum, "mean": np.mean, "max": np.max, "min": np.min}
"""How a constraint with ``over`` other than ``each`` and ``duration`` reads the run."""

NO_VALUE = "no_value: the run gives no value of this field"
"""The reason when the field is not among the results."""

NO_FLOW = "the module carried no flow in this run"
"""The reason when ``when="running"`` leaves no step."""


def constraints(plant, problem, results):
    """Check every constraint of ``problem`` against a finished run.

    Each ``Constraint`` path is matched against the module paths of ``plant``, name by name, and
    each match is checked on its own; a violated constraint is an answer, not an error. A result
    field is read over the run, a composite's through the leaves its formula names; with
    ``when="running"`` only the steps in which the module carried flow count. ``over`` gives how
    the run is read: ``each`` judges every step and reports the worst; ``sum``, ``mean``, ``max``
    and ``min`` judge one figure of the run; ``duration`` judges the total time of the steps
    that count. A parameter path takes ``over="each"`` and is judged once, or at each date inside
    the run when it changes over time, with the site of the problem applied to the plant.
    A value on a limit passes within ``TOLERANCE``, a duration within half a step.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    problem : Problem
        The problem whose constraints are checked, and whose site gives design values.
    results : Results
        A finished run.

    Returns
    -------
    list of dict
        One check ``{name, passed, value, limit, path, worst_step}`` per matched module and
        constraint: ``name`` is the matched ``<module path>.<field>``, ``path`` the path of the
        constraint, ``value`` the worst value of the run for ``each`` and the figure otherwise
        and ``limit`` the bound that was violated, else the nearest, in the unit of the field
        (``s`` for ``duration``). ``worst_step`` is the ISO 8601 time of the worst step, ``None``
        for a figure of the run and for a parameter. ``passed`` is ``None``, with the reason in
        ``value``, for a module that carried no flow, and with ``no_value`` for a field the
        run does not hold, every row having failed.

    Raises
    ------
    ValidationError
        With code ``unknown_name`` for a path that matches no module, or no module with that
        field, and ``invalid_value`` for a parameter with an ``over`` other than ``each``.
    """
    frame = results.to_frame()
    sited = problem.apply_site(plant)
    checks = []
    for constraint in problem.constraints:
        paths, name = matched(sited, constraint.path)
        checks += [
            _check(sited, frame, results.durations, constraint, path, name) for path in paths
        ]
    return checks


def _in_unit(bound, name, unit, quantity, path):
    """Return a bound in the SI unit of its field; a number is accepted for a field of no unit."""
    if bound is None:
        return bound
    if isinstance(bound, units.Quantity):
        return units.value_in_si(bound, unit, path, quantity)
    if unit != "-":
        raise ValidationError(
            f"constraint {path}: {name} = {bound!r}; expected {units.QUANTITY_FORM}, because the "
            f"field has the unit {unit!r}",
            path=path,
            code="invalid_value",
        )
    return bound


def _bounds(constraint, unit, quantity):
    """Return ``(lower, upper)`` of a constraint in ``unit``; ``equals`` sets both."""
    given = {name: getattr(constraint, name) for name in ("min", "max", "equals")}
    bound = {
        name: _in_unit(item, name, unit, quantity, constraint.path)
        for name, item in given.items()
        if item is not None
    }
    lower = [bound[name] for name in ("min", "equals") if name in bound]
    upper = [bound[name] for name in ("max", "equals") if name in bound]
    return (max(lower) if lower else None, min(upper) if upper else None)


def _reading(plant, frame, constraint, path, name):
    """Return ``(values, keep)`` of a field: its values and the steps that count."""
    if is_parameter(plant, path, name):
        if constraint.over != "each":
            raise ValidationError(
                f"constraint {constraint.path}: over = {constraint.over!r}; expected 'each' for "
                "a parameter",
                path=constraint.path,
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


def _check(plant, frame, durations, constraint, path, name):
    """Return the check of one constraint on one matched module."""
    unit, quantity = ("s", None) if constraint.over == "duration" else fields(plant, path)[name]
    bounds = _bounds(constraint, unit, quantity)
    values, keep = _reading(plant, frame, constraint, path, name)
    label = join_path(path, name)
    reason = _no_reason(values, keep, constraint.over)
    if reason:
        limit = measure(bounds[0] if bounds[0] is not None else bounds[1], unit)
        return check(label, None, measure(None, unit, reason), limit) | _where(constraint, None)
    measured, margin, position = _measure(constraint, values, keep, durations, bounds)
    lower, upper = bounds
    passed = (lower is None or measured >= lower - margin) and (
        upper is None or measured <= upper + margin
    )
    step = None if position is None or is_parameter(plant, path, name) else frame.index[position]
    limit = measure(_nearest(measured, lower, upper), unit)
    return check(label, bool(passed), measure(measured, unit), limit) | _where(constraint, step)


def _where(constraint, step):
    """Return the keys that tell which constraint a check answers and when it was worst."""
    return {"path": constraint.path, "worst_step": None if step is None else step.isoformat()}
