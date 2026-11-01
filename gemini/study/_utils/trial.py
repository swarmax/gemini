"""One trial of a search: a copy of the plant and the case with new values, run and read."""

from copy import deepcopy

from gemini import units
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import GeminiError, ValidationError
from gemini.evaluate import annualised_cost, co2, lcoc, lcoh, lcts, totals
from gemini.evaluate.totals import KPI_NAMES
from gemini.run.simulate import simulate
from gemini.study._utils.target import is_case_name, parameter_value, with_case_values

ECONOMICS = {
    "lcoh": lcoh,
    "lcoc": lcoc,
    "lcts": lcts,
    "annualised_cost": annualised_cost,
    "co2": co2,
}
"""The economic metrics of ``gm.evaluate``; the others are the KPIs of ``gm.evaluate.totals``."""


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


def run_trial(plant, case, plan, values, names):
    """Return ``(metrics, reason)`` of one run of a copy; a run that fails has its reason.

    ``values`` are SI numbers by name: a parameter of the plant, or ``case.<path>`` for a number of
    the case, which the copy of the case takes.
    """
    trial = deepcopy(plant)
    try:
        for name, number in values.items():
            if not is_case_name(name):
                path, _, parameter = name.rpartition(".")
                trial.set_params(path, {parameter: parameter_value(trial, name, number)})
        changed = with_case_values(case, {k: v for k, v in values.items() if is_case_name(k)})
        results = simulate(trial, changed, plan=plan)
        return {item: metric(trial, changed, results, item) for item in names}, None
    except GeminiError as error:
        return {}, str(error)
