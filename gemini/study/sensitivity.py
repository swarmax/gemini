"""How much the metrics of a plant depend on each of its parameters."""

import pandas as pd

from gemini import units
from gemini._utils.jsonable import to_plain
from gemini.evaluate._utils.display import display_units, in_unit
from gemini.study._utils.target import quantities
from gemini.study._utils.trial import checked_metric, run_trial
from gemini.study._utils.uncertain import declared
from gemini.types.shapes import measure
from gemini.study.sample import value_of


class Tornado(list):
    """The rows of a one-at-a-time sensitivity, sorted by effect, with ``to_frame``."""

    def to_dict(self):
        """Return the rows as plain JSON ``{"rows": [...]}``, quantities as ``{value, unit}``."""
        keys = ("low", "high", "at_low", "at_high", "effect")
        return {
            "rows": [
                {"parameter": row["parameter"], "metric": row["metric"]}
                | {key: to_plain(row[key]) for key in keys}
                for row in self
            ]
        }

    @classmethod
    def from_dict(cls, data):
        """Return the rows of a dictionary of ``to_dict``."""
        return cls(
            {
                "parameter": row["parameter"],
                "metric": row["metric"],
                "low": units.Quantity.from_dict(row["low"]),
                "high": units.Quantity.from_dict(row["high"]),
                **{key: value_of(row[key]) for key in ("at_low", "at_high", "effect")},
            }
            for row in data["rows"]
        )

    def to_frame(self, units=None):
        """Return a table of the rows: the parameter bounds in SI, the metric in a display unit.

        ``at_low``, ``at_high`` and ``effect`` are numbers in the unit of ``unit``: the display
        unit of the metric (MWh, MW, MEUR, EUR/MWh or kt, as in ``Comparison.to_frame``), or the
        one given in ``units``, a dict ``{metric: unit}`` of the metrics of the rows. A metric
        without a display unit stays in SI. A name that is not a metric of the rows raises
        ``invalid_value``; a unit of another dimension, ``invalid_unit``.
        """
        shown = display_units(list(dict.fromkeys(row["metric"] for row in self)), units)
        rows = [
            {
                "parameter": row["parameter"],
                "metric": row["metric"],
                "low": row["low"].value,
                "high": row["high"].value,
                **{name: _number(row, name, shown) for name in ("at_low", "at_high", "effect")},
                "unit": shown.get(row["metric"], str(row["effect"].unit)),
            }
            for row in self
        ]
        columns = ["parameter", "metric", "low", "high", "at_low", "at_high", "effect", "unit"]
        return pd.DataFrame(rows, columns=columns)


def _number(row, name, shown):
    """Return the number of ``name`` of a row in the display unit of its metric, or in SI."""
    found = row[name]
    if row["metric"] not in shown:
        return found.value
    return in_unit(row["metric"], found.si, shown[row["metric"]])


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
        "low": shown[0],
        "high": shown[1],
        "at_low": at_low,
        "at_high": at_high,
        "effect": measure(effect, unit, reason),
    }


def sensitivity(plant, case, metrics, *, plan=None):
    """Return how each metric changes when each uncertain value of the case moves, one at a time.

    The values are those the case declares an ``uncertainty`` for (``missing_value`` when it
    declares none); plant parameters are not moved. Each is run at its low and at its high end,
    the others at their values in the case: ``min`` and ``max`` when the declaration has them,
    else ``value - std`` and ``value + std`` of a ``normal``. A run is a copy of the plant and the
    case simulated on the case, as in ``minimize``. The plant and the case themselves are not
    changed.

    Parameters
    ----------
    plant : Plant
        A plant with parameter values.
    case : Case
        What the plant is asked to do, with the ``uncertainty`` of the values to move.
    metrics : list of str
        The metrics to read, as for ``minimize``.
    plan : DataFrame, optional
        The run input held fixed, for a building block with no demand.

    Returns
    -------
    Tornado
        A list with one row for each uncertain value and metric, ``{parameter, metric, low, high,
        at_low, at_high, effect}``: ``parameter`` is ``case.<path>``, ``low`` and ``high`` are
        ``Quantity`` values in SI, ``at_low`` and ``at_high`` the metric as a ``Value`` there, and
        ``effect`` the size of their difference, a ``Value`` that is ``None`` with a ``reason``
        when a run failed. The rows are grouped by metric in the order given, the largest effect
        first, the failed last. ``to_frame()`` gives the table and ``to_dict()`` plain JSON.
    """
    names = [checked_metric(name) for name in metrics]
    rows = []
    for name, uncertainty, value in declared(case, "sensitivity"):
        ends = uncertainty.limits(value)
        shown = tuple(quantities(plant, case, {name: end})[name] for end in ends)
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
