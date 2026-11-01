"""One trial of a search: a copy of the plant and the case with new values, run and read."""

from copy import deepcopy

from gemini import units
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import GeminiError, ValidationError
from gemini.evaluate import annualised_cost, co2, constraints, lcoc, lcoh, lcts, totals
from gemini.evaluate.failures import failures
from gemini.evaluate.totals import KPI_NAMES
from gemini.run._utils.apply import applied_in_place
from gemini.run.simulate import simulate
from gemini.study._utils.target import is_case_name, parameter_value, with_case_values
from gemini.types.shapes import measure

ECONOMICS = {
    "lcoh": lcoh,
    "lcoc": lcoc,
    "lcts": lcts,
    "annualised_cost": annualised_cost,
    "co2": co2,
}
"""The economic metrics of ``gm.evaluate``; the others are the KPIs of ``gm.evaluate.totals``."""


LARGEST_VIOLATION = 1e6
"""The violation of a trial that failed: above that of any design that ran."""


def checked_metric(name):
    """Return ``name`` when it is a metric the call can read, or raise with the close names."""
    known = [*KPI_NAMES, *ECONOMICS]
    if name not in known:
        raise ValidationError(
            f"study: metric = {name!r}; expected one of {join_names(known)}"
            f"{did_you_mean(name, known)}",
            path="metric",
            code="unknown_name",
            suggestions=close_matches(name, known),
        )
    return name


def limit_si(bound, metric, name):
    """Return a limit on a metric in the SI unit of the ``metric`` value; a number needs no unit."""
    if isinstance(bound, dict):
        bound = units.Quantity.from_dict(bound)
    if isinstance(bound, units.Quantity):
        return units.value_in_si(bound, str(metric.unit), name)
    if metric.unit != "-":
        raise ValidationError(
            f"study: {name} limit = {bound!r}; expected {units.QUANTITY_FORM}, because the metric "
            f"has the unit {str(metric.unit)!r}",
            path=name,
            code="invalid_value",
        )
    return bound


def metric(plant, case, results, name):
    """Return one metric of a finished run; a value it cannot give is ``None`` with a reason."""
    if name in ECONOMICS:
        return ECONOMICS[name](plant, case, results, on_error="record")
    return totals(plant, case, results)[name]


def _run(plant, case, plan, values):
    """Return ``(copy, case, results)`` of one run of a copy of ``plant`` with ``values`` set."""
    trial = deepcopy(plant)
    for name, number in values.items():
        if not is_case_name(name):
            path, _, parameter = name.rpartition(".")
            trial.set_params(path, {parameter: parameter_value(trial, name, number)})
    changed = with_case_values(case, {k: v for k, v in values.items() if is_case_name(k)})
    trial = applied_in_place(trial, changed)
    return trial, changed, simulate(trial, changed, plan=plan)


def failure_reason(results):
    """Return the reason of a run with failed steps: their count and the most frequent failure.

    The failure is the group of ``gm.evaluate.failures`` with the most failed rows, as
    ``path code (rows): message``.
    """
    top = next(group for group in failures(results).groups if group["kind"] == "failed")
    return (
        f"{len(results.failures)} steps failed; most frequent: {top['path']} {top['code']} "
        f"({top['count']} rows): {top['message']}"
    )


def run_trial(plant, case, plan, values, names):
    """Return ``(metrics, reason)`` of one run of a copy; a run that fails has its reason.

    A run with a failed step is no valid design: every metric is ``None`` with the reason
    ``failure_reason``.

    ``values`` are SI numbers by name: a parameter of the plant, or ``case.<path>`` for a number of
    the case, which the copy of the case takes.
    """
    try:
        trial, changed, results = _run(plant, case, plan, values)
        if results.failures:
            reason = failure_reason(results)
            return {item: measure(None, "-", reason) for item in names}, reason
        return {item: metric(trial, changed, results, item) for item in names}, None
    except GeminiError as error:
        return {}, str(error)


def _excess(check):
    """Return how far a failed check is out of its limit, relative to the larger of the two."""
    found, limit = check["value"].value, check["limit"].value
    return abs(found - limit) / (max(abs(found), abs(limit)) or 1.0)


def judged(plant, case, results):
    """Return ``(reason, violation)`` of a finished run against the constraints of the case.

    The checks are those of ``gm.evaluate.constraints``, the supply temperatures of the services
    included. A run with a failed step is infeasible with ``LARGEST_VIOLATION``. Otherwise the
    ``violation`` is the sum of the relative excess of every failed check, and the ``reason`` is the
    first failed check itself (the dict of ``gm.evaluate.constraints``). A feasible run is
    ``(None, 0.0)``; a check with nothing to judge does not fail.
    """
    if results.failures:
        return failure_reason(results), LARGEST_VIOLATION
    failed = [item for item in constraints(plant, case, results) if item["passed"] is False]
    if not failed:
        return None, 0.0
    return failed[0], min(sum(map(_excess, failed)), LARGEST_VIOLATION)


def run_judged(plant, case, plan, values, names):
    """Return ``(metrics, reason, violation)`` of one run of a copy, judged against the case.

    A run that raises is infeasible with its message as the reason and ``LARGEST_VIOLATION``;
    ``values`` are as for ``run_trial``.
    """
    try:
        trial, changed, results = _run(plant, case, plan, values)
        metrics = {item: metric(trial, changed, results, item) for item in names}
        return (metrics, *judged(trial, changed, results))
    except GeminiError as error:
        return {}, str(error), LARGEST_VIOLATION


def drawn_trial(shared, values):
    """Return ``run_trial`` of ``values`` with the ``(plant, case, plan, names)`` it shares.

    The function ``gemini.study._utils.parallel.mapped`` runs in a worker process.
    """
    plant, case, plan, names = shared
    return run_trial(plant, case, plan, values, names)
