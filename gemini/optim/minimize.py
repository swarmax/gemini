"""Optimisation of plant parameters."""

import numpy as np
from scipy.optimize import differential_evolution

from gemini._utils.strings import join_path
from gemini.errors import ValidationError
from gemini.optim._utils.trial import (
    checked_metric,
    limit_si,
    parameter_si,
    quantities,
    require_input,
    run_trial,
)
from gemini.types.shapes import Value, measure

POPULATION_PER_VARIABLE = 5
"""Candidates of a generation per variable: a small budget still sees several generations."""
SMALLEST_POPULATION = 5
"""The fewest candidates of a generation, which ``differential_evolution`` needs."""
SEED = 0
"""Seed of the search: the same call gives the same trials."""


def _broken_constraint(metrics, constraints):
    """Return the reason of the first constraint a trial breaks, or ``None``."""
    for limit in constraints:
        name, lower, upper = limit["metric"], limit.get("minimum"), limit.get("maximum")
        number = metrics[name].value
        if number is None:
            return f"{name} has no value: {metrics[name].reason}"
        lower = None if lower is None else limit_si(lower, metrics[name], name)
        upper = None if upper is None else limit_si(upper, metrics[name], name)
        if (lower is not None and number < lower) or (upper is not None and number > upper):
            return f"{name} = {number}; expected {lower} to {upper}"
    return None


def _entry(parameters, metrics, name, reason):
    """Return one line of the history: the objective, with the parameters and a failed reason."""
    metric = metrics.get(name, measure(None, "-", reason))
    return Value(
        metric.value,
        metric.unit,
        reason or metric.reason,
        metric.parts | {"parameters": parameters},
    )


def _checked_variables(plant, variables):
    """Return ``(names, bounds)`` of the variables, or raise for one that does not fit."""
    if not variables:
        raise ValidationError(
            "optim.minimize: variables = []; expected at least one",
            path="variables",
            code="missing_value",
        )
    names = [join_path(item["path"], item["parameter"]) for item in variables]
    bounds = []
    for name, item in zip(names, variables):
        plant.get(name)
        lower, upper = (parameter_si(plant, name, item[end]) for end in ("lower", "upper"))
        if not lower < upper:
            raise ValidationError(
                f"optim.minimize: {name}: lower = {item['lower']}, upper = {item['upper']}; "
                "expected lower below upper",
                path=name,
            )
        bounds.append((lower, upper))
    return names, bounds


def _generations(evaluations, count):
    """Return ``(population, generations after the first)`` that fit the budget."""
    population = max(SMALLEST_POPULATION, POPULATION_PER_VARIABLE * count)
    if evaluations < population:
        raise ValidationError(
            f"optim.minimize: evaluations = {evaluations}; {count} variables need at least "
            f"{population}",
            path="evaluations",
        )
    return population, evaluations // population - 1


def _best(history, sign):
    """Return the best trial without a reason, or ``None`` with the reason there is none."""
    accepted = [item for item in history if item.reason is None]
    if not accepted:
        return measure(None, "-", "every trial failed or broke a constraint", parameters=None)
    return min(accepted, key=lambda item: sign * item.value)


def minimize(
    plant,
    problem,
    variables,
    objective,
    constraints=None,
    evaluations=100,
    *,
    plan=None,
):
    """Return the parameter values that minimise a metric of a simulated plant.

    Each trial copies the plant, sets the variables with ``set_params``, simulates it on the
    problem (``gm.simulate`` plans the demand on that design) and reads the objective from
    ``gm.evaluate``. The search is
    ``scipy.optimize.differential_evolution`` from a Latin hypercube, with a fixed seed: it needs no
    gradient, takes a failed trial as infinitely bad, and its population gives the exact number of
    simulations. The plant itself is not changed.

    Parameters
    ----------
    plant : Module
        A plant with parameter values.
    problem : Problem or None
        What the plant is asked to do: its demand is planned for each trial, so a variable that
        changes the design changes the plan, and its assumptions give the prices. ``None`` is
        allowed with a ``plan`` and the metrics that need no assumptions; with neither a problem
        nor a plan the call raises ``missing_value``.
    variables : list of dict
        The decision variables, each ``{path, parameter, lower, upper}``: the module path, the
        parameter name and its closed bounds, each a ``Quantity`` or its dict (a plain number only
        for a parameter without a dimension).
    objective : str
        The metric to minimise, a KPI of ``gm.evaluate.totals`` or ``lcoh``, ``lcoc``, ``lcts``,
        ``annualised_cost`` or ``co2``; a metric to maximise is given with a leading ``"-"``.
    constraints : list of dict, optional
        Limits on metrics, each ``{metric, minimum, maximum}`` with ``Quantity`` limits (a plain
        number only for a metric without a dimension), either limit optional; a trial that breaks
        one is rejected.
    evaluations : int
        The largest number of simulations; at least five per variable, and at least five.
    plan : DataFrame, optional
        The run input held fixed over the trials, for a building block with no demand; without it
        each trial is planned from the problem.

    Returns
    -------
    dict
        ``{best, history, evaluations}``: ``best`` is the objective as a ``Value`` in SI, whose
        ``parts["parameters"]`` are ``{"path.parameter": Quantity}``, ready for ``set_params``;
        ``history`` lists the same for every trial, with a ``reason`` for a trial that failed or
        broke a constraint, which is never ``best``; ``evaluations`` is the number of simulations.
        Without an accepted trial, ``best`` has no value and gives a ``reason``. ``to_plain``
        gives the JSON form.
    """
    name = checked_metric(objective.removeprefix("-"), problem)
    sign = -1.0 if objective.startswith("-") else 1.0
    constraints = constraints or []
    names = {name, *(checked_metric(limit["metric"], problem) for limit in constraints)}
    keys, bounds = _checked_variables(plant, variables)
    population, generations = _generations(evaluations, len(keys))
    history = []
    require_input(problem, plan)

    def evaluated(point):
        parameters = dict(zip(keys, map(float, point)))
        metrics, reason = run_trial(plant, problem, plan, parameters, names)
        reason = reason or metrics[name].reason or _broken_constraint(metrics, constraints)
        history.append(_entry(quantities(plant, parameters), metrics, name, reason))
        return np.inf if reason else sign * metrics[name].value

    differential_evolution(
        evaluated,
        bounds,
        maxiter=generations,
        popsize=population,
        tol=0,
        polish=False,
        seed=SEED,
    )
    return {"best": _best(history, sign), "history": history, "evaluations": len(history)}
