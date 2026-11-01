"""Spread of metrics when uncertain parameters are drawn at random."""

import numpy as np

from gemini._utils.strings import close_matches, join_names
from gemini.errors import ValidationError
from gemini.study._utils.trial import (
    checked_metric,
    parameter_si,
    quantities,
    require_input,
    run_trial,
)
from gemini.types.shapes import measure

DISTRIBUTIONS = {
    "normal": ("mean", "std"),
    "uniform": ("lower", "upper"),
    "triangular": ("lower", "mode", "upper"),
}
"""The fields of each distribution, in the order of the method of its name of the generator."""


def _checked_distribution(plant, name, distribution):
    """Refuse a distribution that does not fit: the parameter, the kind or a missing field."""
    plant.get(name)
    kind = distribution.get("kind")
    if kind not in DISTRIBUTIONS:
        raise ValidationError(
            f"study.sample: {name}: kind = {kind!r}; expected one of {join_names(DISTRIBUTIONS)}",
            path=name,
            code="unknown_name",
            suggestions=close_matches(str(kind), list(DISTRIBUTIONS)),
        )
    missing = set(DISTRIBUTIONS[kind]) - set(distribution)
    if missing:
        raise ValidationError(
            f"study.sample: {name}: expected {join_names(sorted(missing))} for {kind}",
            path=name,
            code="missing_value",
        )


def _draw(generator, plant, name, distribution):
    """Return one random value of a parameter, in SI."""
    kind = distribution["kind"]
    fields = [
        parameter_si(plant, name, distribution[field], difference=field == "std")
        for field in DISTRIBUTIONS[kind]
    ]
    try:
        return float(getattr(generator, kind)(*fields))
    except ValueError as error:
        raise ValidationError(f"study.sample: {name}: {error}", path=name) from error


def _spread(samples, name):
    """Return ``{mean, p5, p50, p95}``, each a ``Value``, of a metric over the samples giving it."""
    metrics = [item["metrics"][name] for item in samples if name in item["metrics"]]
    numbers = [item.value for item in metrics if item.value is not None]
    unit = metrics[0].unit if metrics else "-"
    if not numbers:
        reason = "no sample gives this metric"
        return {key: measure(None, unit, reason) for key in ("mean", "p5", "p50", "p95")}
    low, middle, high = np.percentile(numbers, (5, 50, 95))
    spread = {"mean": np.mean(numbers), "p5": low, "p50": middle, "p95": high}
    return {key: measure(number, unit) for key, number in spread.items()}


def sample(plant, problem, distributions, metrics, count, seed=0, *, plan=None):
    """Return the spread of metrics when uncertain parameters are drawn at random.

    Each draw copies the plant, sets the drawn values with ``set_params``, simulates it on the
    problem (``gm.simulate`` plans the demand on that design) and reads the metrics. The plant
    itself is not changed.

    Parameters
    ----------
    plant : Module
        A plant with parameter values.
    problem : Problem or None
        What the plant is asked to do, as for ``minimize``.
    distributions : dict
        For each uncertain parameter ``"path.parameter"``, its distribution:
        ``{"kind": "normal", "mean", "std"}``, ``{"kind": "uniform", "lower", "upper"}`` or
        ``{"kind": "triangular", "lower", "mode", "upper"}``, each field a ``Quantity`` or its dict
        (a plain number only for a parameter without a dimension).
    metrics : list of str
        The metrics to record, as the ``objective`` of ``minimize`` without a sign.
    count : int
        The number of random draws, one simulation each.
    seed : int
        Seed of ``numpy.random.default_rng``; the same seed gives the same draws.
    plan : DataFrame, optional
        The run input held fixed over the draws, as for ``minimize``.

    Returns
    -------
    dict
        ``{samples, summary}``: ``samples`` lists each draw's ``parameters``, ``Quantity`` values
        in SI, and ``metrics``, a ``Value`` per metric, with a ``reason`` for a draw whose run
        failed; ``summary`` gives, for each metric, ``{mean, p5, p50, p95}`` over the draws that
        give it, each a ``Value`` that is ``None`` with a ``reason`` when none does.
    """
    if count < 1:
        raise ValidationError(f"study.sample: count = {count}; expected at least 1", path="count")
    names = [checked_metric(name, problem) for name in metrics]
    for name, distribution in distributions.items():
        _checked_distribution(plant, name, distribution)
    generator = np.random.default_rng(seed)
    samples = []
    require_input(problem, plan)
    for _ in range(count):
        drawn = {key: _draw(generator, plant, key, item) for key, item in distributions.items()}
        found, reason = run_trial(plant, problem, plan, drawn, names)
        failed = {"reason": reason} if reason else {}
        samples.append({"parameters": quantities(plant, drawn), "metrics": found, **failed})
    summary = {name: _spread(samples, name) for name in names}
    return {"samples": samples, "summary": summary}
