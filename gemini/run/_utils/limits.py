"""The constraints a schedule enforces, found by their general form against the doublets.

A constraint is read by its path, with ``*`` matching one name, and by its ``over`` and ``when``:

- flow range: ``<doublet>.reservoir.liquid_flow``, ``over="each"``, ``when="running"``, ``min`` and
  ``max``;
- maximum brine cooling: ``<doublet>.brine_cooling``, ``over="each"``, ``max``;
- operating duration: ``<doublet>.reservoir.liquid_flow``, ``over="duration"``,
  ``when="running"``, ``max`` or ``equals`` a duration.

Every other constraint, a duration with only ``min``, and a bound of a constraint that the form
does not read are left to the check of a run.
"""

from dataclasses import dataclass
from fnmatch import fnmatchcase

import pandas as pd

from gemini import units
from gemini._utils.strings import join_path
from gemini._utils.time import to_timedelta
from gemini.errors import ValidationError
from gemini.run.constraint import BOUNDS

FLOW = "reservoir.liquid_flow"
"""The path below a doublet of its flow."""
COOLING = "brine_cooling"
"""The path below a doublet of the cooling of its brine."""


@dataclass(frozen=True)
class DoubletLimits:
    """The limits of one doublet in SI: flows [m3/s], cooling [K] and the running time or None."""

    minimum_flow: float
    maximum_flow: float
    brine_cooling: float
    operating_time: pd.Timedelta | None


def _fits(pattern, path):
    """Return whether ``path`` fits ``pattern``, name by name."""
    wanted, given = pattern.split("."), path.split(".")
    return len(wanted) == len(given) and all(map(fnmatchcase, given, wanted))


def _forms(constraint):
    """Return the forms ``constraint`` has, each with the path below a doublet it reads."""
    forms = []
    if constraint.over == "each" and constraint.when == "running":
        if constraint.min is not None and constraint.max is not None:
            forms.append(("range", FLOW))
    if constraint.over == "each" and constraint.max is not None:
        forms.append(("cooling", COOLING))
    if constraint.over == "duration" and constraint.when == "running":
        if constraint.max is not None or constraint.equals is not None:
            forms.append(("duration", FLOW))
    return forms


def _quantity(bound, unit):
    """Return a bound as a number in ``unit``; a temperature is a difference."""
    number, given = units.parse(bound) if isinstance(bound, str) else (bound, unit)
    return units.convert(number, given, unit, "temperature_difference" if unit == "K" else None)


def _duration(constraint):
    """Return the duration of a duration constraint as a ``Timedelta``."""
    bound = constraint.equals if constraint.equals is not None else constraint.max
    try:
        return to_timedelta(bound)
    except (TypeError, ValueError) as error:
        raise ValidationError(
            f"schedule: constraint {constraint.path} duration = {bound!r}; expected a duration",
            path=constraint.path,
            code="invalid_value",
        ) from error


def _missing(doublet, name, form):
    """Return the ``missing_value`` error of a limit that no constraint gives for ``doublet``."""
    path = join_path(doublet, name)
    return ValidationError(
        f"schedule: no constraint gives {form} of {path}; expected one, a limit has no default",
        path=f"constraints.{path}",
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
    data = constraint.to_dict() | dict.fromkeys(enforced)
    return data if any(data[name] is not None for name in BOUNDS) else None


def _found(constraints, doublet):
    """Return ``{form: (index, constraint)}``, the first constraint of each form that fits."""
    found = {}
    for index, constraint in enumerate(constraints):
        for form, name in _forms(constraint):
            if _fits(constraint.path, join_path(doublet, name)):
                found.setdefault(form, (index, constraint))
    return found


def of_doublet(constraints, doublet):
    """Return ``(DoubletLimits, used)`` of the doublet at path ``doublet``.

    ``used`` maps the index of each constraint that gave a limit to the bounds the schedule
    enforces of it. A flow range or a brine cooling that no constraint gives raises
    ``ValidationError`` (code ``missing_value``).
    """
    found = _found(constraints, doublet)
    if "range" not in found:
        raise _missing(doublet, FLOW, "a flow range (over='each', when='running', min and max)")
    if "cooling" not in found:
        raise _missing(doublet, COOLING, "a maximum (over='each', max)")
    flow, cooling = found["range"][1], found["cooling"][1]
    duration = found.get("duration")
    limits = DoubletLimits(
        _quantity(flow.min, "m3/s"),
        _quantity(flow.max, "m3/s"),
        _quantity(cooling.max, "K"),
        None if duration is None else _duration(duration[1]),
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
    limits, used = {}, {}
    for doublet in doublets:
        limits[doublet], taken = of_doublet(constraints, doublet)
        used |= taken
    left = [_left_over(item, used.get(index, ())) for index, item in enumerate(constraints)]
    return limits, [item for item in left if item is not None]
