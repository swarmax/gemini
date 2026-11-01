"""Rank the reports of several designs and find the Pareto front."""

import numpy as np
import pandas as pd

from gemini._utils.jsonable import to_plain
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import ValidationError
from gemini.evaluate._utils.display import display_units, in_unit
from gemini.units import Quantity, si_unit

SENSES = ("min", "max")
"""The two ways to prefer a metric: the smaller or the larger value."""

SERVICES = {"heating": "heat_delivered", "cooling": "cold_delivered"}
"""The metric that shows a service of the case being delivered."""


class Comparison(list):
    """A list of ``{index, values, ranks, pareto, feasible}``, one per report in the order given."""

    def to_frame(self, units=None):
        """Return one row per report: its metrics, its ``rank_<metric>``, ``pareto``, ``feasible``.

        Parameters
        ----------
        units : dict, optional
            ``{metric: unit}``. A metric is shown in its display unit (energy in MWh, power in
            MW, money in MEUR, LCTS in EUR/MWh, mass in kt) unless a unit is given; its column is
            named ``<metric> [<unit>]``. A metric without a display unit stays in SI under its
            own name. A name that is not a metric, or a unit of another dimension, raises
            ``invalid_value`` or ``invalid_unit``.
        """
        names = list(self[0]["values"]) if self else []
        shown = display_units(names, units)
        rows = [
            {
                **{
                    _label(name, shown): (
                        in_unit(name, _number(entry["values"][name]), shown[name])
                        if name in shown
                        else _number(entry["values"][name])
                    )
                    for name in names
                },
                **{f"rank_{name}": rank for name, rank in entry["ranks"].items()},
                "pareto": entry["pareto"],
                "feasible": entry["feasible"],
            }
            for entry in self
        ]
        return pd.DataFrame(rows, index=pd.Index([entry["index"] for entry in self], name="index"))

    def to_dict(self):
        """Return the entries as plain JSON: every ``Quantity`` as ``{value, unit}`` in SI."""
        return to_plain(list(self))

    @classmethod
    def from_dict(cls, data):
        """Return the ``Comparison`` of what ``to_dict`` gave; a metric value is a ``Quantity`` again.

        The ``reasons`` stay plain dicts, as ``to_dict`` wrote them.
        """
        return cls(
            {
                **entry,
                "values": {
                    name: Quantity.from_dict(item) if isinstance(item, dict) else item
                    for name, item in entry["values"].items()
                },
            }
            for entry in data
        )


def _number(value):
    """Return the SI number of a value of a comparison: a ``Quantity``, a plain number or ``None``."""
    return value.si if isinstance(value, Quantity) else value


def _label(name, shown):
    """Return the column name of a metric: with its unit in brackets when it has one."""
    return f"{name} [{shown[name]}]" if name in shown else name


def compare(reports, by):
    """Rank reports by the given metrics and mark the Pareto front of the feasible ones.

    A report is feasible when ``passed`` is ``True`` (or ``None`` with no
    constraint to check), it has no failed step and it delivers every
    service in its ``services`` (``heat_delivered`` has a value for ``"heating"``,
    ``cold_delivered`` for ``"cooling"``). A dict without these keys, such as a plain table of
    figures, is feasible. Feasible reports rank before all infeasible ones; the infeasible are
    ordered by their number of reasons, then by the metrics.

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
        metrics as ``gm.units.Quantity`` in SI; a plain number stays a float; ``None`` for no value), ``ranks`` (1 is best; equal values share a
        rank), ``pareto`` (whether no other feasible report is at least as good in every metric and
        better in one; an infeasible report is never on it), ``feasible`` and, when not feasible,
        ``reasons``: the failed constraints as ``gm.evaluate.constraints`` gives them, and
        ``{name, reason}`` for a missing service, a failed step or constraints none of which
        was checked.
        With one metric the front is its best reports. ``to_frame()`` gives a table in display units and ``to_dict()`` plain JSON.
    """
    senses = _senses(by, reports)
    values = {name: [_value(report, name) for report in reports] for name in senses}
    quantities = {name: [_quantity(report, name) for report in reports] for name in senses}
    reasons = [_reasons(report) for report in reports]
    feasible = [not found for found in reasons]
    ranks = {name: _ranks(values[name], senses[name], reasons) for name in senses}
    front = _front(values, senses, feasible)
    return Comparison(
        {
            "index": position,
            "values": {name: quantities[name][position] for name in senses},
            "ranks": {name: ranks[name][position] for name in senses},
            "pareto": bool(front[position]),
            "feasible": feasible[position],
            **({} if feasible[position] else {"reasons": reasons[position]}),
        }
        for position in range(len(reports))
    )


def _reasons(report):
    """Return why a report is not feasible: the failed constraints and the services not given."""
    found = [item for item in report.get("constraints", []) if item["passed"] is False]
    if "passed" in report and report["passed"] is None and report.get("constraints"):
        found.append({"name": "constraints", "reason": "no constraint was checked"})
    if report.get("failed_steps"):
        found.append({"name": "failed_steps", "reason": f"{report['failed_steps']} steps failed"})
    for service, key in SERVICES.items():
        if service in report.get("services", ()) and _value(report, key) is None:
            found.append({"name": key, "reason": f"the run gives no {key} for the {service}"})
    return found


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


def _quantity(report, name):
    """Return metric ``name`` of a report as a ``Quantity`` in SI, a plain number, or ``None``."""
    found = report.get(name)
    number = _value(report, name)
    if number is None or not isinstance(found, Quantity):
        return number
    return Quantity(number, si_unit(str(found.unit)))


def _worse(values, sense):
    """Return the values as numbers where a smaller one is better; no value is infinite."""
    sign = 1.0 if sense == "min" else -1.0
    return np.array([np.inf if value is None else sign * value for value in values])


def _ranks(values, sense, reasons):
    """Return the rank of each report, 1 for the best; the infeasible come after the feasible.

    Equal reports share the lowest rank. The infeasible are ordered by their number of reasons,
    then by the metric.
    """
    keys = list(zip((len(found) for found in reasons), _worse(values, sense)))
    return [1 + sum(other < key for other in keys) for key in keys]


def _front(values, senses, feasible):
    """Return which feasible reports no other feasible report dominates."""
    table = np.column_stack([_worse(values[name], senses[name]) for name in senses])
    front = np.zeros(len(feasible), dtype=bool)
    allowed = np.asarray(feasible)
    rivals = table[allowed]
    for position in np.flatnonzero(allowed):
        valued = np.isfinite(table[position]).all()
        beaten = (
            (rivals <= table[position]).all(axis=1) & (rivals < table[position]).any(axis=1)
        ).any()
        front[position] = valued and not beaten
    return front
