"""Optimisation of plant and case values, and of the number of doublets."""

from copy import deepcopy

import numpy as np
from scipy.optimize import differential_evolution

from gemini import units
from gemini.errors import ValidationError
from gemini.study._utils.best import Best
from gemini.study._utils.choices import STRUCTURE, from_choices, split
from gemini.study._utils.resize import resized
from gemini.study._utils.roles import concrete, expanded, quantities
from gemini.study._utils.target import is_case_name, parameter_value
from gemini.study._utils.trial import LARGEST_VIOLATION, checked_metric, limit_si, run_judged
from gemini.types.shapes import Value, measure

POPULATION_PER_VARIABLE = 5
"""Candidates of a generation per variable: a small budget still sees several generations."""
SMALLEST_POPULATION = 5
"""The fewest candidates of a generation, which ``differential_evolution`` needs."""
SEED = 0
"""Seed of the search: the same call gives the same trials."""


def _broken_constraint(metrics, constraints):
    """Return ``(reason, violation)`` of the metric limits a trial breaks, or ``(None, 0.0)``."""
    reason, violation = None, 0.0
    for limit in constraints:
        name, lower, upper = limit["metric"], limit.get("minimum"), limit.get("maximum")
        number = metrics[name].value
        if number is None:
            return f"{name} has no value: {metrics[name].reason}", LARGEST_VIOLATION
        lower = None if lower is None else limit_si(lower, metrics[name], name)
        upper = None if upper is None else limit_si(upper, metrics[name], name)
        outside = max(0.0 if lower is None else lower - number, 0.0)
        outside = max(outside, 0.0 if upper is None else number - upper)
        if outside > 0:
            reason = reason or f"{name} = {number}; expected {lower} to {upper}"
            violation += outside / (max(abs(number), abs(lower or 0), abs(upper or 0)) or 1.0)
    return reason, violation


def _read(metrics, name, constraints):
    """Return ``(reason, violation)`` of a run the case accepts: the objective and the limits."""
    if metrics[name].value is None:
        return metrics[name].reason, LARGEST_VIOLATION
    return _broken_constraint(metrics, constraints)


def _ranked(sign, number, reason, violation):
    """Return the objective the search sees: feasible trials in (-1, 1), the others above 2.

    The map is monotone, so every feasible trial is better than every infeasible one, and the
    infeasible ones are ordered by their violation.
    """
    if reason is None:
        scaled = sign * number
        return scaled / (1 + abs(scaled))
    return 2 + violation / (1 + violation)


def _entry(parameters, metrics, name, reason, violation):
    """Return one line of the history: the objective, with the parameters and the violation."""
    metric = metrics.get(name, measure(None, "-", reason))
    return Value(
        metric.value,
        metric.unit,
        reason or metric.reason,
        metric.parts | {"parameters": parameters, "violation": violation},
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
    values = {k: q.value for k, q in parameters.items() if k != STRUCTURE and not is_case_name(k)}
    for name, number in expanded(design, values).items():
        path, _, parameter = name.rpartition(".")
        design.set_params(path, {parameter: parameter_value(design, name, number)})
    return design


def _best(history, sign, plant):
    """Return ``(Best, feasible)``: the best feasible trial, else the least violating one.

    A trial that ran but broke a limit is returned, with its ``reason``, only when none is
    feasible; with no trial that ran, ``Best`` has no value and no plant.
    """
    ran = [item for item in history if item.value is not None]
    feasible = [item for item in ran if item.reason is None]
    if not ran:
        reason = "every trial failed"
        return Best(None, "-", reason, {"parameters": None}, None), False
    if feasible:
        found = min(feasible, key=lambda item: sign * item.value)
    else:
        found = min(ran, key=lambda item: item.parts["violation"])
    design = _design(plant, found.parts["parameters"])
    return Best(found.value, found.unit, found.reason, found.parts, design), bool(feasible)


def _start(design, keys, bounds):
    """Return the point of the design itself, each value clipped to its bounds.

    A variable of the plant takes the value the design has for it (the first unit of a role); a
    number of the case, or a parameter with no number, takes the middle of its bounds.
    """
    point = []
    for name, (low, high) in zip(keys, bounds):
        found = None
        if not is_case_name(name):
            path, _, parameter = concrete(design, name)[0].rpartition(".")
            found = getattr(design.get_submodule(path), parameter, None)
        number = (low + high) / 2 if not isinstance(found, (int, float)) else found
        point.append(min(max(float(number), low), high))
    return point


def _search(evaluated, keys, bounds, evaluations, start):
    """Run the search of the continuous variables from ``start``; with none, evaluate once."""
    if not keys:
        evaluated(np.empty(0))
        return
    population, generations = _generations(evaluations, len(keys))
    differential_evolution(
        evaluated,
        bounds,
        maxiter=generations,
        popsize=population,
        x0=start,
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
    ``scipy.optimize.differential_evolution`` from a Latin hypercube with a fixed seed. One member
    is the plant as it is given (its own values, clipped to the bounds), so a start inside the
    bounds is among the trials and the best is never worse than it. It needs no gradient and its
    population gives the exact number of simulations. A number of doublets is
    a discrete variable: the search runs once for each count, from the lowest to the highest, on
    a new plant of that size (``size.doublets``), and the best trial of all counts wins. The
    plant and the case themselves are not changed.

    A trial is feasible when its run has no failed step and every constraint of the case passes,
    the supply temperatures of the services included (``gm.evaluate.constraints``), and every
    limit of ``constraints``. A trial that does not run (a physics error, say at some depth) is
    infeasible with the largest violation. The search sees feasible trials as better than
    infeasible ones, and infeasible ones ordered by their total relative violation, so it moves
    towards feasibility. The best feasible trial is ``best``; with none, ``best`` is the least
    violating trial and ``feasible`` is ``False``.

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
        or ``size.doublets``, whose bounds are integers. ``<role>.<parameter>`` (a role of
        ``gm.case.roles()``, with ``path`` the role and ``parameter`` the parameter, for example
        ``{"path": "heat_pump", "parameter": "capacity", "lower": Quantity(1, "MW"), "upper":
        Quantity(5, "MW")}``) sets that parameter on every unit of the role, after the doublet
        count is applied, so one list serves plants with other paths and counts. ``depth`` on a
        plant with no depth of its own is the depth of every doublet. A variable the plant cannot
        take is not searched and is listed in ``fixed``: a role it has no unit of, and
        ``size.doublets`` on a plant class that takes no such size; when nothing is left to
        search, ``invalid_design`` is raised.
        Without ``variables`` they are those of ``case.choices``: ``size.doublets`` and ``depth``;
        a case without ``choices`` then raises ``missing_value``. A capacity is searched only when
        listed, and a list replaces the choices of the case: restate ``size.doublets`` and
        ``depth`` in it to keep searching them.
    constraints : list of dict, optional
        Limits on metrics, each ``{metric, minimum, maximum}`` with ``Quantity`` limits (a plain
        number only for a metric without a dimension), either limit optional; a trial that breaks
        one is infeasible, like one that breaks a constraint of the case.
    evaluations : int
        The largest number of simulations for each doublet count; at least five per continuous
        variable, and at least five.
    plan : DataFrame, optional
        The run input held fixed over the trials, for a building block with no demand; without it
        each trial is planned from the case.

    Returns
    -------
    dict
        ``{best, feasible, fixed, history, evaluations}``. ``best`` is the objective as a ``Value``
        in SI, whose ``parts["parameters"]`` are ``{name: Quantity}`` (a plant parameter is ready
        for ``set_params``; a ``<role>.<parameter>`` name is as listed) and whose ``["plant"]`` is
        the best plant, with the best doublet count and the parameters set. ``feasible`` is
        whether ``best`` is feasible; if not, ``best`` is the least violating trial that ran and
        its ``reason`` says why. ``fixed`` lists ``{name, value, reason}`` of the variables the
        plant fixed. ``history`` lists the same as ``best`` for every trial, with
        ``parts["violation"]`` (0 when feasible) and a ``reason`` for an infeasible trial: the first
        failed check of ``gm.evaluate.constraints`` (its dict), a text for a limit on a metric or
        a failed run.
        ``evaluations`` is the number of simulations. With no trial that ran, ``best`` has no value
        and no plant, and gives a ``reason``. ``to_plain`` gives the JSON form.
    """
    name = checked_metric(objective.removeprefix("-"))
    sign = -1.0 if objective.startswith("-") else 1.0
    constraints = constraints or []
    names = {name, *(checked_metric(limit["metric"]) for limit in constraints)}
    variables = from_choices(case) if variables is None else variables
    counts, keys, bounds, fixed = split(plant, case, variables)
    history = []
    for count in counts:
        design = plant if count is None else resized(plant, count)
        chosen = {} if count is None else {STRUCTURE: units.Quantity(count, "-")}

        def evaluated(point, design=design, chosen=chosen):
            values = dict(zip(keys, map(float, point)))
            metrics, reason, violation = run_judged(
                design, case, plan, expanded(design, values), names
            )
            if reason is None:
                reason, violation = _read(metrics, name, constraints)
            shown = chosen | quantities(design, case, values)
            history.append(_entry(shown, metrics, name, reason, violation))
            return _ranked(sign, history[-1].value, reason, violation)

        _search(evaluated, keys, bounds, evaluations, _start(design, keys, bounds))
    best, feasible = _best(history, sign, plant)
    return {
        "best": best,
        "feasible": feasible,
        "fixed": fixed,
        "history": history,
        "evaluations": len(history),
    }
