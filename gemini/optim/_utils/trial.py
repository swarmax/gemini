"""One trial of a search: a copy of the plant with drawn values, run and read."""

from copy import deepcopy

from gemini import units
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import GeminiError, ValidationError
from gemini.evaluate import annualised_cost, co2, lcoc, lcoh, lcts, totals
from gemini.evaluate.totals import KPI_NAMES
from gemini.run.simulate import simulate

ECONOMICS = {
    "lcoh": lcoh,
    "lcoc": lcoc,
    "lcts": lcts,
    "annualised_cost": annualised_cost,
    "co2": co2,
}
"""The economic metrics of ``gm.evaluate``; the others are the KPIs of ``gm.evaluate.totals``."""


def checked_metric(name, problem):
    """Return ``name`` when it is a metric the call can read, or raise with the close names."""
    known = [*KPI_NAMES, *ECONOMICS]
    if name not in known:
        raise ValidationError(
            f"optim: metric = {name!r}; expected one of {join_names(known)}"
            f"{did_you_mean(name, known)}",
            path="metric",
            code="unknown_name",
            suggestions=close_matches(name, known),
        )
    if name in ECONOMICS and problem is None:
        raise ValidationError(
            f"optim: metric = {name!r} needs the assumptions of a problem; problem = None",
            path="problem",
            code="missing_value",
        )
    return name


def _declaration(plant, name):
    """Return the parameter declaration of the dotted path ``name``."""
    path, _, parameter = name.rpartition(".")
    return plant.get_submodule(path)._parameters[parameter]


def parameter_si(plant, name, bound, difference=False):
    """Return ``bound``, a ``Quantity`` or its dict, in the SI unit of the parameter ``name``.

    A plain number is accepted only for a parameter without a dimension. A ``difference`` is
    a spread such as a standard deviation, which a unit offset does not move.
    """
    declaration = _declaration(plant, name)
    if isinstance(bound, dict):
        bound = units.Quantity.from_dict(bound)
    if isinstance(bound, units.Quantity):
        number = units.value_in_si(bound, declaration.unit, name, declaration.quantity)
        return number - units.to_si(0, bound.unit) if difference else number
    if declaration.unit not in (None, "-"):
        raise ValidationError(
            f"optim: {name} = {bound!r}; expected {units.QUANTITY_FORM}, because the parameter "
            f"has the unit {declaration.unit!r}",
            path=name,
            code="invalid_value",
        )
    return bound


def quantities(plant, parameters):
    """Return ``{name: Quantity}`` for SI parameter values, each in the SI unit of its parameter."""
    return {
        name: units.Quantity(number, _declaration(plant, name).unit or "-")
        for name, number in parameters.items()
    }


def limit_si(bound, metric, name):
    """Return a limit on a metric in the SI unit of the ``metric`` value; a number needs no unit."""
    if isinstance(bound, dict):
        bound = units.Quantity.from_dict(bound)
    if isinstance(bound, units.Quantity):
        return units.value_in_si(bound, str(metric.unit), name)
    if metric.unit != "-":
        raise ValidationError(
            f"optim: {name} limit = {bound!r}; expected {units.QUANTITY_FORM}, because the metric "
            f"has the unit {str(metric.unit)!r}",
            path=name,
            code="invalid_value",
        )
    return bound


def require_input(problem, plan):
    """Raise ``missing_value`` unless a search has a problem or a plan to run."""
    if problem is None and plan is None:
        raise ValidationError(
            "optim: problem = None and plan = None; expected a problem or a plan",
            path="problem",
            code="missing_value",
        )


def _metric(plant, problem, results, name):
    """Return one metric of a finished run; a value it cannot give is ``None`` with a reason."""
    if name in ECONOMICS:
        return ECONOMICS[name](plant, problem, results, on_error="record")
    return totals(plant, problem, results)[name]


def run_trial(plant, problem, plan, parameters, names):
    """Return ``(metrics, reason)`` of one run of a copy; a run that fails has its reason."""
    trial = deepcopy(plant)
    try:
        for name, number in parameters.items():
            path, _, parameter = name.rpartition(".")
            trial.set_params(path, {parameter: number})
        results = simulate(trial, problem, plan=plan)
        return {item: _metric(trial, problem, results, item) for item in names}, None
    except GeminiError as error:
        return {}, str(error)
