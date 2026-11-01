"""Rank the reports of several designs and find the Pareto front."""

import numpy as np
import pandas as pd

from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import ValidationError

SENSES = ("min", "max")
"""The two ways to prefer a metric: the smaller or the larger value."""


class Comparison(list):
    """A list of ``{index, values, ranks, pareto}``, one per report, in the order given."""

    def to_frame(self):
        """Return one row per report: its metrics, its ``rank_<metric>`` and ``pareto``."""
        rows = [
            {**entry["values"], **{f"rank_{name}": rank for name, rank in entry["ranks"].items()}}
            | {"pareto": entry["pareto"]}
            for entry in self
        ]
        return pd.DataFrame(rows, index=pd.Index([entry["index"] for entry in self], name="index"))


def compare(reports, by):
    """Rank reports by the given metrics and mark the Pareto front.

    Parameters
    ----------
    reports : list of dict
        Reports as ``gm.evaluate.report`` returns them, or any dicts whose ``by`` keys are values.
    by : str, list of str or dict
        The metrics, keys of the reports whose value is a ``Quantity`` or a number. A name or a list
        prefers the smaller value of each; a dict ``{metric: "min" or "max"}`` says which. A report
        without a value of a metric (``None``) ranks last for it and is never on the front.

    Returns
    -------
    Comparison
        One entry per report, in the order given: ``index`` (its position), ``values`` (the
        metrics in SI, ``None`` for no value), ``ranks`` (1 is best; equal values share a rank) and
        ``pareto``, whether no other report is at least as good in every metric and better in one.
        With one metric the front is its best reports. ``to_frame()`` gives a table.
    """
    senses = _senses(by, reports)
    values = {name: [_value(report, name) for report in reports] for name in senses}
    ranks = {name: _ranks(values[name], senses[name]) for name in senses}
    front = _front(values, senses, len(reports))
    return Comparison(
        {
            "index": position,
            "values": {name: values[name][position] for name in senses},
            "ranks": {name: ranks[name][position] for name in senses},
            "pareto": bool(front[position]),
        }
        for position in range(len(reports))
    )


def _senses(by, reports):
    """Return ``{metric: "min" or "max"}`` and check the names against the reports."""
    senses = _normal(by)
    if not senses:
        raise ValidationError(
            "by = []; expected at least one metric", path="by", code="invalid_value"
        )
    known = sorted({name for report in reports for name in report})
    for name, sense in senses.items():
        if sense not in SENSES:
            raise ValidationError(
                f"by.{name} = {sense!r}; expected one of {join_names(SENSES)}",
                path=f"by.{name}",
                code="invalid_value",
            )
        if reports and not any(name in report for report in reports):
            raise ValidationError(
                f"by = {name!r}; expected a key of the reports" f"{did_you_mean(name, known)}",
                path="by",
                code="unknown_name",
                suggestions=close_matches(name, known),
            )
    return senses


def _normal(by):
    """Return ``by`` as ``{metric: sense}``."""
    if isinstance(by, str):
        return {by: "min"}
    return dict(by) if isinstance(by, dict) else dict.fromkeys(by, "min")


def _value(report, name):
    """Return the SI number of metric ``name`` of a report, or ``None``."""
    found = report.get(name)
    if found is None:
        return None
    number = getattr(found, "si", found)
    return None if number is None else float(number)


def _worse(values, sense):
    """Return the values as numbers where a smaller one is better; no value is infinite."""
    sign = 1.0 if sense == "min" else -1.0
    return np.array([np.inf if value is None else sign * value for value in values])


def _ranks(values, sense):
    """Return the rank of each value, 1 for the best; equal values share the lowest rank."""
    return [int(rank) for rank in pd.Series(_worse(values, sense)).rank(method="min")]


def _front(values, senses, count):
    """Return which reports no other report dominates."""
    table = np.column_stack([_worse(values[name], senses[name]) for name in senses])
    front = np.ones(count, dtype=bool)
    for position in range(count):
        valued = np.isfinite(table[position]).all()
        beaten = (
            (table <= table[position]).all(axis=1) & (table < table[position]).any(axis=1)
        ).any()
        front[position] = valued and not beaten
    return front
