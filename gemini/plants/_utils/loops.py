"""Closing a loop of a plant: the iteration on its tear streams.

A plant whose connections form a cycle cuts it at one connection, the tear stream, chosen by the
plan. ``close`` finds the stream that one pass around the loop maps to itself. Each pass calls the
modules of the loop without recording them; when the streams have converged every module is
called once with them, so outputs and balances see exactly one call of each. In a trace the
iteration is one ``fixed_point`` node of the graph, whose interpreter runs ``iterate``.
"""

import dataclasses

import numpy as np

from gemini import ops
from gemini._utils.strings import join_path
from gemini.errors import PhysicsError, ValidationError
from gemini.ops.failures import Failures, attached, is_marking, merge, stripped
from gemini.ops.solvers import wegstein
from gemini.types.flows import STREAM_FIELDS, Stream

TOLERANCE = 1e-9
"""Default convergence of a loop: a pass may change a tear stream field by at most this, in SI."""

MAX_PASSES = 50
"""Default number of passes around a loop before it raises ``PhysicsError``."""


class Field:
    """The iteration on one field of a tear stream: a float, or one value per row."""

    def __init__(self, current, lower=None, upper=None):
        """Start at ``current``, clamped to ``[lower, upper]``; ``None`` is no limit."""
        self.lower, self.upper = lower, upper
        self.current = self._clamped(current)
        self.previous = self.previous_image = self.tried = self.current

    def _clamped(self, value):
        """Return ``value`` within the limits as ``max(value, lower)`` and ``min`` give it."""
        if self.lower is not None:
            value = ops.where(self.lower > value, self.lower, value)
        return value if self.upper is None else ops.where(self.upper < value, self.upper, value)

    def advance(self, image, tolerance, active):
        """Move the rows of ``active`` to the next iterate unless ``image`` is within ``tolerance``.

        Return which rows are within it. A row that stands still keeps its history.
        """
        image = stripped(image)
        within = ops.abs(image - self.current) <= tolerance
        moves = ops.logical_and(active, ops.logical_not(within))
        proposed = self._clamped(wegstein(self.current, image, self.previous, self.previous_image))
        self.previous = ops.where(moves, self.current, self.previous)
        self.previous_image = ops.where(moves, image, self.previous_image)
        self.current = ops.where(moves, proposed, self.current)
        return within

    def keep(self, active):
        """Remember the iterate a trial pass starts from for the rows still iterating."""
        self.tried = ops.where(active, self.current, self.tried)


class Tear:
    """The iteration on one tear stream: its mass flow, temperature and pressure."""

    def __init__(self, start, lower, upper):
        """Start from the stream ``start``, the temperature within ``[lower, upper]``."""
        self.fluid = start.fluid
        self.fields = {name: Field(getattr(start, name)) for name in STREAM_FIELDS}
        self.fields["T"] = Field(start.T, lower, upper)

    def values(self, trial):
        """Return the fields a trial pass starts from, or the converged ones for the last call.

        A row that has stopped iterating keeps the iterate of its last trial, so that the passes
        that wait for the other rows repeat what it computed and raise nothing new.
        """
        return {
            name: field.tried if trial else field.current for name, field in self.fields.items()
        }

    def stream(self, trial):
        """Return the stream of ``values``."""
        return Stream._si(fluid=self.fluid, **self.values(trial))

    def advance(self, image, tolerance, active):
        """Move every field of the rows of ``active``; return the rows where all have converged.

        A stream that stands still carries nothing, so only its flow has to converge.
        """
        settled = [
            field.advance(getattr(image, name), tolerance, active)
            for name, field in self.fields.items()
        ]
        flowless = ops.logical_and(stripped(image.m_dot) == 0, self.fields["m_dot"].current == 0)
        return ops.logical_or(flowless, _all(settled))


def _all(conditions):
    """Return the rows where every one of ``conditions`` holds."""
    found = conditions[0]
    for condition in conditions[1:]:
        found = ops.logical_and(found, condition)
    return found


def _entering(run, step):
    """Return the streams that reach ``step`` from outside its loop."""
    arguments = run.known_arguments(step).values()
    return [value for value in arguments if isinstance(value, Stream)]


def _start(run, loop, tear, lower, upper):
    """Return the first guess of a tear stream: no flow, at what its source module expects.

    A module of the loop may set the pressure, as a circulation pump does, and then the guess does
    not matter. Where none does, the pressure stays the highest that enters the loop, so a pipe in
    it has something to lose. The fluid is that of the water that enters the module of the tear.
    """
    path, port = tear.source
    step = next(item for item in loop.steps if item.path == path)
    module, entering = step.module, _entering(run, step)
    temperature = module._loop_start(port, entering)
    if temperature is None:
        name = join_path(*tear.source)
        raise ValidationError(
            f"{run.plant.path}: tear stream {name} has no first guess; expected a module of the "
            "loop that gives one",
            path=name,
            code="invalid_design",
        )
    pressures = [stream.p for item in loop.steps for stream in _entering(run, item)]
    pressure = pressures[0] if pressures else 0.0
    for other in pressures[1:]:
        pressure = ops.where(other > pressure, other, pressure)
    fluid = entering[0].fluid if entering else module.fluid
    return Tear(Stream._si(m_dot=0.0, T=temperature, p=pressure, fluid=fluid), lower, upper)


def _limits(run, loop):
    """Return the tightest temperature limits the modules of a loop set on the tear streams.

    A limit is ``None``, a float or one value per row.
    """
    lower, upper = None, None
    for step in loop.steps:
        low, high = step.module._loop_limits(run.known_arguments(step))
        if low is not None:
            lower = low if lower is None else ops.where(low > lower, low, lower)
        if high is not None:
            upper = high if upper is None else ops.where(high < upper, high, upper)
    return lower, upper


def _not_converged(run, tear, temperature):
    name = join_path(*tear.source)
    return PhysicsError(
        f"{run.plant.path}: loop temperature at {name} = {temperature} K after "
        f"{run.plant.loop_passes} passes; expected a change of at most "
        f"{run.plant.loop_tolerance} K (the loop did not converge)",
        path=name,
        code="loop_not_converged",
    )


def _around(run, loop, streams, trial):
    """Run one pass around the loop from the tear ``streams``; return the images of the tears.

    A trial pass records no call; the last pass calls every module for the record.
    """
    run.tears = {tear.index: stream for tear, stream in zip(loop.tears, streams)}
    for step in loop.steps:
        run.call(step, trial=trial)
    return [run.outlet(tear.source) for tear in loop.tears]


def _outlet_values(run, loop):
    """Return the values of every outlet of every step of the last pass.

    A row alone fails as soon as one step of a pass fails, whether or not that step feeds the tear.
    """
    outlets = (value for step in loop.steps for value in run.results[step.path].outlets.values())
    return [
        getattr(outlet, field.name)
        for outlet in outlets
        for field in (dataclasses.fields(outlet) if dataclasses.is_dataclass(outlet) else ())
    ]


def _failed(run, loop):
    """Return the rows that got a failed value into any outlet of the last pass, else ``False``."""
    failures = merge(_outlet_values(run, loop))
    return False if failures is None else failures.mask


def _advance(tears, images, tolerance, active, failed):
    """Move the tears of the rows of ``active``; return the rows that have still to iterate.

    A row whose pass failed in a check (``failed``) stops with its iterate, the one that failed:
    the last call fails it again with the error of the row alone. A row is done when all its tears
    have converged on the same pass.
    """
    active = ops.logical_and(active, ops.logical_not(failed))
    settled = [tear.advance(image, tolerance, active) for tear, image in zip(tears, images)]
    active = ops.logical_and(active, ops.logical_not(_all(settled)))
    for tear in tears:
        for field in tear.fields.values():
            field.keep(active)
    return active


def _unconverged(run, loop, tear, active):
    """Raise the error of a row that did not converge, or mark those rows when asked to.

    A scalar call raises. An array call raises for the first such row unless the rows are
    marked, which the eager executor does: the other rows then keep their results.
    """
    temperature = tear.fields["T"].current
    if not np.ndim(active):
        raise _not_converged(run, loop.tears[0], temperature)
    if not is_marking():
        row = int(np.flatnonzero(active)[0])
        raise _not_converged(run, loop.tears[0], float(temperature[row]))

    def build(row):
        return _not_converged(run, loop.tears[0], float(temperature[row]))

    failures = Failures.at(active, build)
    for field in tear.fields.values():
        field.current = attached(field.current, failures)
    ops.require(tear.fields["T"].current)


def iterate(tears, tolerance, passes, around):
    """Pass around the loop until every row stops or ``passes`` passes; return the active rows.

    ``around(tears)`` runs one trial pass from the iterates of ``tears`` and returns the images of
    the tears and the rows that failed in the pass. The iteration is that of a call on floats and
    on arrays, and the one a graph runs for a compiled plant.
    """
    active = True
    for _ in range(passes):
        images, failed = around(tears)
        active = _advance(tears, images, tolerance, active, failed)
        if not np.any(active):
            break
    return active


def _close_traced(run, loop, graph, tears, lower, upper):
    """Record the iteration as a ``fixed_point`` of the graph and take its converged tears.

    One pass is traced as the body of the node, from carries that stand for the tear fields; the
    node gives the converged iterates. A row that did not converge fails whatever it reads, as a
    call does that raises for it.
    """
    plant = run.plant
    names = list(tears[0].fields)

    def around(carries):
        streams = []
        for index, tear in enumerate(tears):
            fields = dict(zip(names, carries[index * len(names) :]))
            streams.append(Stream._si(fluid=tear.fluid, **fields))
        images = _around(run, loop, streams, False)
        return [getattr(image, name) for image in images for name in names], _outlet_values(
            run, loop
        )

    fields = [field for tear in tears for field in tear.fields.values()]
    settings = {
        "fluids": tuple(tear.fluid for tear in tears),
        "tolerance": plant.loop_tolerance,
        "passes": plant.loop_passes,
    }
    found = graph.fixed_point([field.current for field in fields], [lower, upper], settings, around)
    ops.check(
        ops.logical_not(found["active"]),
        PhysicsError,
        "{path}: loop temperature at {name} = {temperature} K after {passes} passes; expected "
        "a change of at most {tolerance} K (the loop did not converge)",
        code="loop_not_converged",
        path=plant.path,
        name=join_path(*loop.tears[0].source),
        temperature=found[names.index("T")],
        passes=plant.loop_passes,
        tolerance=plant.loop_tolerance,
    )
    for index, field in enumerate(fields):
        field.current = found[index]


def _converge(run, loop, tears):
    """Iterate the tears of a call on floats or arrays, then fail the rows that did not close."""
    plant = run.plant

    def around(tears):
        images = _around(run, loop, [tear.stream(True) for tear in tears], True)
        return images, _failed(run, loop)

    active = iterate(tears, plant.loop_tolerance, plant.loop_passes, around)
    if np.any(active):
        _unconverged(run, loop, tears[0], active)


def close(run, loop):
    """Iterate ``loop`` of the running plant until its tear streams converge, then run it once.

    The same iteration serves a call on floats and on arrays: each row has the iterates it has
    alone, stops when its tears have converged and waits (still computed, unchanged) for the other
    rows. The loop ends when every row has stopped, or at ``loop_passes`` passes. In a trace the
    iteration is one ``fixed_point`` node of the graph, which runs this iteration on arrays.
    """
    lower, upper = _limits(run, loop)
    tears = [_start(run, loop, tear, lower, upper) for tear in loop.tears]
    graph = ops.scope.traced_graph()
    if graph is None:
        _converge(run, loop, tears)
    else:
        _close_traced(run, loop, graph, tears, lower, upper)
    _around(run, loop, [tear.stream(False) for tear in tears], False)
