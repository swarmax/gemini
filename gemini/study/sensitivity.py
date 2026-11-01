"""How much the metrics of a plant depend on each of its parameters."""

import pandas as pd

from gemini._utils.strings import join_names
from gemini.errors import ValidationError
from gemini.study._utils.target import check_name, quantities, value_si
from gemini.study._utils.trial import checked_metric, run_trial
from gemini.types.shapes import measure


class Tornado(list):
    """The rows of a one-at-a-time sensitivity, sorted by effect, with ``to_frame``."""

    def to_frame(self):
        """Return a table of the rows, numbers in SI, the unit of each metric in ``unit``."""
        rows = [
            {
                "parameter": row["parameter"],
                "metric": row["metric"],
                "low": row["low"].value,
                "high": row["high"].value,
                "at_low": row["at_low"].value,
                "at_high": row["at_high"].value,
                "effect": row["effect"].value,
                "unit": str(row["effect"].unit),
            }
            for row in self
        ]
        columns = ["parameter", "metric", "low", "high", "at_low", "at_high", "effect", "unit"]
        return pd.DataFrame(rows, columns=columns)


def _bounds(plant, case, parameters):
    """Return ``{name: (low, high)}`` in SI, or raise for a parameter that does not fit."""
    if not isinstance(parameters, dict) or not parameters:
        raise ValidationError(
            "study.sensitivity: parameters; expected a dict of each name to {'low', 'high'}",
            path="parameters",
            code="invalid_value",
        )
    found = {}
    for name, bounds in parameters.items():
        check_name(plant, case, name)
        if not isinstance(bounds, dict) or set(bounds) != {"low", "high"}:
            raise ValidationError(
                f"study.sensitivity: {name}: expected {join_names(['low', 'high'])}",
                path=name,
                code="invalid_value",
            )
        found[name] = tuple(value_si(plant, case, name, bounds[end]) for end in ("low", "high"))
    return found


def _metric(found, name, reason):
    """Return the metric ``name`` of a trial, or a value with the reason the trial failed."""
    return found[name] if name in found else measure(None, "-", reason)


def _row(name, metric, shown, ends):
    """Return the row of one metric of one parameter."""
    at_low, at_high = ends
    effect = None
    if at_low.value is not None and at_high.value is not None:
        effect = abs(at_high.si - at_low.si)
    unit = at_low.unit if at_low.value is not None else at_high.unit
    reason = at_low.reason or at_high.reason
    return {
        "parameter": name,
        "metric": metric,
        "low": shown[name][0],
        "high": shown[name][1],
        "at_low": at_low,
        "at_high": at_high,
        "effect": measure(effect, unit, reason),
    }


def sensitivity(plant, case, parameters, metrics, *, plan=None):
    """Return how each metric changes when each parameter moves, one at a time.

    Each parameter is run at its low and at its high value, the others at their present values; a
    run is a copy of the plant and the case simulated on the case, as in ``minimize``. The plant
    and the case themselves are not changed.

    Parameters
    ----------
    plant : Plant
        A plant with parameter values.
    case : Case
        What the plant is asked to do.
    parameters : dict
        For each value to move, ``{"low": Quantity, "high": Quantity}``. A key is
        ``"path.parameter"`` for a parameter of the plant or ``"case.<path>"`` for a number of the
        case, as for ``sample``; a plain number is accepted only for a value without a dimension.
    metrics : list of str
        The metrics to read, as for ``minimize``.
    plan : DataFrame, optional
        The run input held fixed, for a building block with no demand.

    Returns
    -------
    Tornado
        A list with one row for each parameter and metric, ``{parameter, metric, low, high,
        at_low, at_high, effect}``: ``low`` and ``high`` are ``Quantity`` values in SI, ``at_low``
        and ``at_high`` the metric as a ``Value`` there, and ``effect`` the size of their
        difference, a ``Value`` that is ``None`` with a ``reason`` when a run failed. The rows
        are grouped by metric in the order given, the largest effect first, the failed last.
        ``to_frame()`` gives the table.
    """
    names = [checked_metric(name) for name in metrics]
    bounds = _bounds(plant, case, parameters)
    rows = []
    for name, ends in bounds.items():
        shown = {name: tuple(quantities(plant, case, {name: end})[name] for end in ends)}
        runs = [run_trial(plant, case, plan, {name: end}, names) for end in ends]
        for metric in names:
            found = [_metric(items, metric, reason) for items, reason in runs]
            rows.append(_row(name, metric, shown, found))
    order = {metric: index for index, metric in enumerate(names)}
    rows.sort(
        key=lambda row: (
            order[row["metric"]],
            row["effect"].value is None,
            -(row["effect"].value or 0),
        )
    )
    return Tornado(rows)
