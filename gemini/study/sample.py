"""Spread of metrics when the uncertain values of the case are drawn at random."""

import numpy as np

from gemini import units
from gemini._utils.jsonable import to_plain
from gemini.errors import ValidationError
from gemini.study._utils.target import quantities
from gemini.study._utils.parallel import mapped
from gemini.study._utils.trial import checked_metric, drawn_trial
from gemini.study._utils.uncertain import declared
from gemini.types.shapes import measure

ATTEMPTS = 10000
"""Draws of a truncated normal before its bounds are judged out of reach."""
SUMMARY = ("mean", "p5", "p50", "p95")


class Sample(dict):
    """The result of ``sample``: ``{samples, summary}``, with ``to_dict`` and ``from_dict``."""

    def to_dict(self):
        """Return the result as plain JSON: quantities and values as ``{"value", "unit"}``."""
        samples = [
            {
                "parameters": to_plain(draw["parameters"]),
                "metrics": to_plain(draw["metrics"]),
                **({"reason": draw["reason"]} if "reason" in draw else {}),
            }
            for draw in self["samples"]
        ]
        summary = {
            metric: to_plain(spread) for metric, spread in self["summary"].items()
        }
        return {"samples": samples, "summary": summary}

    @classmethod
    def from_dict(cls, data):
        """Return the result of a dictionary of ``to_dict``."""
        samples = [
            {
                "parameters": {
                    k: units.Quantity.from_dict(v) for k, v in draw["parameters"].items()
                },
                "metrics": {k: value_of(v) for k, v in draw["metrics"].items()},
                **({"reason": draw["reason"]} if "reason" in draw else {}),
            }
            for draw in data["samples"]
        ]
        summary = {
            metric: {key: value_of(item) for key, item in spread.items()}
            for metric, spread in data["summary"].items()
        }
        return cls(samples=samples, summary=summary)


def _is_value(item):
    """Whether ``item`` is the JSON form of a value."""
    return isinstance(item, dict) and {"value", "unit"} <= set(item)


def value_of(data):
    """Return the ``Value`` of the JSON value ``{value, unit}`` with its ``reason`` and parts."""
    parts = {
        key: value_of(item) if _is_value(item) else item
        for key, item in data.items()
        if key not in ("value", "unit", "reason")
    }
    return measure(data["value"], data["unit"], data.get("reason"), **parts)


def _draw(generator, name, uncertainty, value):
    """Return one random value in SI of a declared number, whose value in the case is ``value``."""
    kind = uncertainty.kind
    if kind == "uniform":
        return float(generator.uniform(uncertainty.min, uncertainty.max))
    if kind == "triangular":
        return float(generator.triangular(uncertainty.min, value, uncertainty.max))
    low = -np.inf if uncertainty.min is None else uncertainty.min
    high = np.inf if uncertainty.max is None else uncertainty.max
    for _ in range(ATTEMPTS):
        number = float(generator.normal(value, uncertainty.std))
        if low <= number <= high:
            return number
    raise ValidationError(
        f"study.sample: {name}: no draw of the normal inside [{low}, {high}] in {ATTEMPTS} tries; "
        "expected bounds that the distribution reaches",
        path=name,
        code="out_of_bounds",
    )


def _spread(samples, name):
    """Return ``{mean, p5, p50, p95}``, each a ``Value``, of a metric over the samples giving it."""
    metrics = [item["metrics"][name] for item in samples if name in item["metrics"]]
    numbers = [item.value for item in metrics if item.value is not None]
    unit = metrics[0].unit if metrics else "-"
    if not numbers:
        reason = "no sample gives this metric"
        return {key: measure(None, unit, reason) for key in SUMMARY}
    low, middle, high = np.percentile(numbers, (5, 50, 95))
    spread = {"mean": np.mean(numbers), "p5": low, "p50": middle, "p95": high}
    return {key: measure(number, unit) for key, number in spread.items()}


def sample(plant, case, metrics, count, seed, *, plan=None):
    """Return the spread of metrics when the uncertain values of the case are drawn at random.

    The distributions are only those the case declares (``uncertainty`` next to a number of
    ``environment`` or ``assumptions`` in ``case.json``); a case with none raises
    ``missing_value``. Plant parameters are design decisions and are never drawn. Each draw copies
    the plant and the case, sets the drawn values on the copy of the case, simulates the copy
    (``gm.simulate`` plans the demand on that design) and reads the metrics. The plant and the
    case themselves are not changed. With ``gm.runtime.settings(processes=n)`` the draws run in
    ``n`` worker processes and give the same result. A draw that breaks the bounds of a value of the case, such as
    a negative price, is a draw whose run failed.

    Parameters
    ----------
    plant : Plant
        A plant with parameter values.
    case : Case
        What the plant is asked to do, with the ``uncertainty`` of the values to draw. A
        ``uniform`` is drawn between its ``min`` and ``max``, a ``triangular`` with the value of
        the case as mode, a ``normal`` around the value, redrawn until inside its bounds if it
        has any. A profile of the case becomes the drawn constant.
    metrics : list of str
        The metrics to record, as the ``objective`` of ``minimize`` without a sign.
    count : int
        The number of random draws, one simulation each.
    seed : int
        Seed of ``numpy.random.default_rng``; the same seed gives the same draws. A seed is a
        reproducibility choice, so there is no default.
    plan : DataFrame, optional
        The run input held fixed over the draws, as for ``minimize``.

    Returns
    -------
    Sample
        A dict ``{samples, summary}``: ``samples`` lists each draw's ``parameters``, ``Quantity``
        values in SI by ``case.<path>``, and ``metrics``, a ``Value`` per metric, with a
        ``reason`` for a draw whose run failed; ``summary`` gives, for each metric,
        ``{mean, p5, p50, p95}`` over the draws that give it, each a ``Value`` that is ``None``
        with a ``reason`` when none does. ``to_dict()`` is plain JSON; ``Sample.from_dict`` reads
        it back.
    """
    if count < 1:
        raise ValidationError(f"study.sample: count = {count}; expected at least 1", path="count")
    names = [checked_metric(name) for name in metrics]
    found = declared(case, "sample")
    generator = np.random.default_rng(seed)
    draws = [
        {name: _draw(generator, name, uncertainty, value) for name, uncertainty, value in found}
        for _ in range(count)
    ]
    runs = mapped(drawn_trial, (plant, case, plan, names), draws)
    samples = []
    for drawn, (run, reason) in zip(draws, runs):
        failed = {"reason": reason} if reason else {}
        samples.append({"parameters": quantities(plant, case, drawn), "metrics": run, **failed})
    summary = {name: _spread(samples, name) for name in names}
    return Sample(samples=samples, summary=summary)
