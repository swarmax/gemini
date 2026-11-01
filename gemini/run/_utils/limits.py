"""The constraints a schedule enforces, found by their role and quantity.

A constraint of the case applies to every unit of its role on its own. The schedule reads three
forms of the role ``doublet``:

- flow range: ``production_flow``, ``over="each"``, ``when="running"``, ``min`` and ``max``;
- maximum brine cooling: ``brine_cooling``, ``over="each"``, ``max``;
- operating duration: ``production_flow``, ``over="duration"``, ``when="running"``, ``max`` or
  ``equals`` a duration.

Every other constraint, a duration with only ``min``, and a bound of a constraint that the form
does not read are left to the check of a run.
"""

from dataclasses import dataclass

import pandas as pd

from gemini._utils.strings import join_path
from gemini._utils.time import to_timedelta
from gemini.errors import ValidationError

BOUNDS = ("min", "max", "equals")
"""The bounds of a constraint."""
ROLE = "doublet"
"""The role whose units the schedule limits."""
FLOW = "production_flow"
"""The quantity of the flow of a doublet."""
COOLING = "brine_cooling"
"""The quantity of the cooling of its brine."""


@dataclass(frozen=True)
class DoubletLimits:
    """The limits of one doublet in SI: flows [m3/s], cooling [K] and the running time or None."""

    minimum_flow: float
    maximum_flow: float
    brine_cooling: float
    operating_time: pd.Timedelta | None


def _has(constraint, *names):
    """Return whether ``constraint`` has one of the bounds ``names``."""
    return any(getattr(constraint, name) is not None for name in names)


def _forms(constraint):
    """Return the forms ``constraint`` has."""
    if constraint.on != ROLE:
        return []
    forms = []
    if constraint.quantity == FLOW and constraint.over == "each" and constraint.when == "running":
        if constraint.min is not None and constraint.max is not None:
            forms.append("range")
    if constraint.quantity == COOLING and constraint.over == "each" and constraint.max is not None:
        forms.append("cooling")
    if constraint.quantity == FLOW and constraint.over == "duration":
        if constraint.when == "running" and _has(constraint, "max", "equals"):
            forms.append("duration")
    return forms


def _duration(constraint):
    """Return the duration of a duration constraint as a ``Timedelta``."""
    bound = constraint.equals if constraint.equals is not None else constraint.max
    try:
        return to_timedelta(bound)
    except ValueError as error:
        raise ValidationError(
            f"schedule: constraint on {constraint.on} {constraint.quantity} duration = {bound}; "
            "expected a duration",
            path="constraints",
            code="invalid_value",
        ) from error


def _missing(doublet, name, form):
    """Return the ``missing_value`` error of a limit that no constraint gives for ``doublet``."""
    return ValidationError(
        f"schedule: no constraint on {ROLE} gives {form} of {join_path(doublet, name)}; "
        "expected one, a limit has no default",
        path="constraints",
        code="missing_value",
    )


def _enforced(form, constraint):
    """Return the names of the bounds of ``constraint`` a schedule enforces in ``form``."""
    if form == "range":
        return ("min", "max")
    if form == "duration" and constraint.equals is not None:
        return ("equals",)
    return ("max",)


def _left_over(constraint, enforced):
    """Return ``to_dict()`` of ``constraint`` without ``enforced``; ``None`` if no bound is left."""
    rest = constraint.model_copy(update=dict.fromkeys(enforced))
    if all(getattr(rest, name) is None for name in BOUNDS):
        return None
    return rest.to_dict()


def _found(constraints):
    """Return ``{form: (index, constraint)}``, the first constraint of each form."""
    found = {}
    for index, constraint in enumerate(constraints):
        for form in _forms(constraint):
            found.setdefault(form, (index, constraint))
    return found


def of_doublet(found, doublet):
    """Return ``(DoubletLimits, used)`` of the doublet at path ``doublet``.

    ``used`` maps the index of each constraint that gave a limit to the bounds the schedule
    enforces of it. A flow range or a brine cooling that no constraint gives raises
    ``ValidationError`` (code ``missing_value``).
    """
    if "range" not in found:
        raise _missing(doublet, FLOW, "a flow range (over='each', when='running', min and max)")
    if "cooling" not in found:
        raise _missing(doublet, COOLING, "a maximum (over='each', max)")
    flow, cooling = found["range"][1], found["cooling"][1]
    duration = found.get("duration")
    limits = DoubletLimits(
        flow.min, flow.max, cooling.max, None if duration is None else _duration(duration[1])
    )
    return limits, {
        index: _enforced(form, constraint) for form, (index, constraint) in found.items()
    }


def split(constraints, doublets):
    """Return ``({doublet: DoubletLimits}, check_only)`` for the doublet paths ``doublets``.

    ``check_only`` lists the ``to_dict()`` of every constraint the schedule did not enforce, and of
    one it enforced in part with only the bounds left: a duration of ``min`` and ``max`` runs to
    the maximum, so its entry keeps the minimum.
    """
    constraints = constraints or ()
    found = _found(constraints)
    limits, used = {}, {}
    for doublet in doublets:
        limits[doublet], taken = of_doublet(found, doublet)
        used |= taken
    left = [_left_over(item, used.get(index, ())) for index, item in enumerate(constraints)]
    return limits, [item for item in left if item is not None]
