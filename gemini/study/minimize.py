"""Optimisation of plant and case values, and of the number of doublets."""

from copy import deepcopy

import numpy as np
from scipy.optimize import differential_evolution

from gemini import units
from gemini.errors import ValidationError
from gemini.study._utils.best import Best
from gemini.study._utils.choices import STRUCTURE, from_choices, split
from gemini.study._utils.resize import resized
from gemini.study._utils.target import is_case_name, parameter_value, quantities
from gemini.study._utils.trial import checked_metric, limit_si, run_trial
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


def _generations(evaluations, count):
    """Return ``(population, generations after the first)`` that fit the budget."""
    population = max(SMALLEST_POPULATION, POPULATION_PER_VARIABLE * count)
    if evaluations < population:
        raise ValidationError(
            f"study.minimize: evaluations = {evaluations}; {count} variables need at least "
            f"{population}",
            path="evaluations",
        )
    return population, evaluations // population - 1


def _design(plant, parameters):
    """Return a copy of ``plant`` on the doublet count and with the plant parameters of a trial."""
    count = parameters.get(STRUCTURE)
    design = deepcopy(plant) if count is None else resized(plant, int(count.value))
    for name, quantity in parameters.items():
        if name != STRUCTURE and not is_case_name(name):
            path, _, parameter = name.rpartition(".")
            design.set_params(path, {parameter: parameter_value(design, name, quantity.value)})
    return design


def _best(history, sign, plant):
    """Return the best accepted trial with its plant, or a ``Best`` with no value and the reason."""
    accepted = [item for item in history if item.reason is None]
    if not accepted:
        reason = "every trial failed or broke a constraint"
        return Best(None, "-", reason, {"parameters": None}, None)
    found = min(accepted, key=lambda item: sign * item.value)
    return Best(
        found.value, found.unit, None, found.parts, _design(plant, found.parts["parameters"])
    )


def _search(evaluated, keys, bounds, evaluations):
    """Run the search of the continuous variables; with none, evaluate the plant once."""
    if not keys:
        evaluated(np.empty(0))
        return
    population, generations = _generations(evaluations, len(keys))
    differential_evolution(
        evaluated,
        bounds,
        maxiter=generations,
        popsize=population,
        tol=0,
        polish=False,
        seed=SEED,
    )


def minimize(
    plant,
    case,
    objective,
    variables=None,
    constraints=None,
    evaluations=100,
    *,
    plan=None,
):
    """Return the values of the plant and the case that minimise a metric of a simulated plant.

    Each trial copies the plant and the case, sets the variables, simulates the copy on the case
    (``gm.simulate`` plans the demand on that design) and reads the objective from
    ``gm.evaluate``. The continuous variables are searched with
    ``scipy.optimize.differential_evolution`` from a Latin hypercube, with a fixed seed: it needs
    no gradient, takes a failed trial as infinitely bad, and its population gives the exact number
    of simulations. A number of doublets is a discrete variable: the search runs once for each
    count, from the lowest to the highest, on a new plant of that size (``size.doublets``), and
    the best trial of all counts wins. The plant and the case themselves are not changed.

    Parameters
    ----------
    plant : Plant
        A plant with parameter values.
    case : Case
        What the plant is asked to do: its demand is planned for each trial, so a variable that
        changes the design changes the plan, and its assumptions give the prices.
    objective : str
        The metric to minimise, a KPI of ``gm.evaluate.totals`` or ``lcoh``, ``lcoc``, ``lcts``,
        ``annualised_cost`` or ``co2``; a metric to maximise is given with a leading ``"-"``.
    variables : list of dict, optional
        The decision variables, each ``{path, parameter, lower, upper}`` with closed bounds, each a
        ``Quantity`` or its dict (a plain number only for a value without a dimension). The name
        ``path.parameter`` is a parameter of the plant, a number of the case as ``case.<path>`` (for
        example ``case.assumptions.finance.opex.electricity``, a profile becoming the constant),
        or ``size.doublets``, whose bounds are integers and which needs a plant class that takes
        that structural size (``gm.plants.capabilities()``), else ``invalid_design`` is raised.
        Without it the variables are those of ``case.choices``: ``size.doublets`` and ``depth``;
        a case without ``choices`` then raises ``missing_value``.
    constraints : list of dict, optional
        Limits on metrics, each ``{metric, minimum, maximum}`` with ``Quantity`` limits (a plain
        number only for a metric without a dimension), either limit optional; a trial that breaks
        one is rejected.
    evaluations : int
        The largest number of simulations for each doublet count; at least five per continuous
        variable, and at least five.
    plan : DataFrame, optional
        The run input held fixed over the trials, for a building block with no demand; without it
        each trial is planned from the case.

    Returns
    -------
    dict
        ``{best, history, evaluations}``: ``best`` is the objective as a ``Value`` in SI, whose
        ``parts["parameters"]`` are ``{name: Quantity}`` (the parameters of the plant are ready
        for ``set_params``) and whose ``["plant"]`` is the best plant, the plant of the best
        doublet count with the best plant parameters set; ``history`` lists the same for every
        trial, with a ``reason`` for a trial that failed or broke a constraint, which is never
        ``best``; ``evaluations`` is the number of simulations. Without an accepted trial, ``best``
        has no value and no plant, and gives a ``reason``. ``to_plain`` gives the JSON form.
    """
    name = checked_metric(objective.removeprefix("-"))
    sign = -1.0 if objective.startswith("-") else 1.0
    constraints = constraints or []
    names = {name, *(checked_metric(limit["metric"]) for limit in constraints)}
    variables = from_choices(case) if variables is None else variables
    counts, keys, bounds = split(plant, case, variables)
    history = []
    for count in counts:
        design = plant if count is None else resized(plant, count)
        fixed = {} if count is None else {STRUCTURE: units.Quantity(count, "-")}

        def evaluated(point, design=design, fixed=fixed):
            values = dict(zip(keys, map(float, point)))
            metrics, reason = run_trial(design, case, plan, values, names)
            reason = reason or metrics[name].reason or _broken_constraint(metrics, constraints)
            shown = fixed | quantities(design, case, values)
            history.append(_entry(shown, metrics, name, reason))
            return np.inf if reason else sign * metrics[name].value

        _search(evaluated, keys, bounds, evaluations)
    best = _best(history, sign, plant)
    return {"best": best, "history": history, "evaluations": len(history)}
