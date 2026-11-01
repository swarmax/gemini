"""The one runner: chunks of ticks through the executor, then results and callbacks.

``Runner.run`` is what ``Engine.replay``, ``live``, ``simulate`` and ``resume`` all execute. A
run is a list of twins (the equipment twins of a replay, the plant of a simulation) evaluated
over **chunks** of ticks, each inside a stretch of ticks that share one dated parameter
snapshot. A chunk is the whole stretch, except that it is one tick when a stateful module is
stepped, a twin sits below another twin or a callback declares ``changes_run``. For each chunk
and twin: the bound columns become SI arrays (``columns``), the twin is evaluated by the
engine's executor on the selected backend (``outcome``), the health is assessed and the columns
of the twin join one ``ResultChunk``.

Callbacks are replayed from the results of a chunk, tick by tick, seeing the engine as a tick
loop would have left it: ``on_step_start``, the inputs of the tick, the results, the position and
the states of the tick, then ``on_step_end``. Without callbacks a chunk is committed at once.
With ``on_error="raise"`` the ticks before the first failing one are committed and delivered,
then the error is raised.
"""

import numpy as np

from gemini.engine.chunks import ResultChunk
from gemini.engine.columns import read
from gemini.engine.outcome import UNCHANGED, StepResults, evaluate_twin
from gemini.errors import GeminiError, RunError, ValidationError
from gemini.types.shapes import problem


class Failure:
    """The first failing tick of a chunk under ``on_error="raise"``."""

    def __init__(self, tick, index, error):
        """Keep the tick (a position in the chunk), the index of the twin and its exception."""
        self.tick, self.index, self.error = tick, index, error


class Runner:
    """Run the twins of a plan over the aligned samples of one engine run."""

    def __init__(self, engine, plan, aligned):
        """Prepare the chunk loop of ``engine`` over ``aligned`` rows."""
        self.engine, self.plan, self.aligned = engine, plan, aligned
        self.callbacks = engine.callbacks
        changes_run = any(getattr(callback, "changes_run", False) for callback in self.callbacks)
        self.single = plan.one_tick or changes_run
        self.total = len(aligned.times)
        self.done = 0

    def run(self):
        """Evaluate and commit every tick, stretch by stretch."""
        for start, stop in self.plan.parameter_stretches(self.aligned.times):
            size = 1 if self.single else stop - start
            for first in range(start, stop, size):
                self._chunk(first, min(first + size, stop), first == start)

    def _chunk(self, first, stop, opening):
        """Evaluate the ticks ``[first, stop)`` and commit what happened.

        The start of a single tick is announced before it is evaluated, so a callback sees the
        engine, the plant and its inputs as they were before the tick.
        """
        single = stop - first == 1
        started = bool(self.callbacks) and single
        if started:
            self.engine._notify("on_step_start", self.aligned.sample(first))
        if opening:
            self.engine.plant._apply_params_at(self.aligned.times[first])
        outcomes = self._evaluate(first, stop)
        failure = self._failure(outcomes)
        count = failure.tick if failure is not None else stop - first
        if not single and not self.callbacks:
            self._persist_last(outcomes, failure, count)
        self._deliver(first, count, self._chunk_of(first, count, outcomes), outcomes, started)
        if failure is not None:
            self._fail(first, outcomes, failure, single)

    def _evaluate(self, first, stop):
        """Return the outcome of every twin over the chunk; a single tick persists inputs at once.

        Under ``on_error="raise"`` a failing twin stops a single tick: the twins after it are
        not evaluated.
        """
        engine = self.engine
        outcomes = []
        engine._in_step = True
        try:
            for twin in self.plan.twins:
                outcomes.append(self._twin(twin, first, stop))
                if self._halts(outcomes[-1], stop - first):
                    break
        finally:
            engine._in_step = False
        return outcomes

    def _twin(self, twin, first, stop):
        """Return the outcome of one twin over the chunk; a single tick persists its inputs."""
        engine = self.engine
        block = read(twin, self.aligned, first, stop)
        state = engine.module_states.get(twin.path)
        durations = self.aligned.durations[first:stop]
        outcome = evaluate_twin(twin, block, engine._executor, durations, state)
        self._note_breaks(outcome)
        if stop - first == 1:
            self._set(outcome, 0)
        return outcome

    def _halts(self, outcome, count):
        """Whether a failing twin stops the single tick, as it stopped the tick loop."""
        return count == 1 and self.plan.on_error == "raise" and bool(outcome.errors)

    def _note_breaks(self, outcome):
        if outcome.evaluation is not None:
            breaks = outcome.evaluation.breaks
            self.engine.graph_breaks[outcome.twin.path] = [reason for _, reason in breaks]

    def _failure(self, outcomes):
        """Return the first failing tick under ``on_error="raise"``, else ``None``."""
        if self.plan.on_error != "raise":
            return None
        failing = [
            (tick, index, error)
            for index, outcome in enumerate(outcomes)
            for tick, error in outcome.errors.items()
        ]
        return Failure(*min(failing, key=lambda item: item[:2])) if failing else None

    def _chunk_of(self, first, count, outcomes):
        """Return the ``ResultChunk`` of the first ``count`` ticks of the chunk."""
        tables, skips = {}, [{} for _ in range(count)]
        for outcome in outcomes:
            for path, table in outcome.tables.items():
                tables[path] = table.sliced(0, count)
            _add_skips(skips, outcome, count)
        errors = sorted(
            (tick, index, error_record(outcome.twin.path, error, outcome.block.status[tick] < 0))
            for index, outcome in enumerate(outcomes)
            for tick, error in outcome.errors.items()
            if tick < count
        )
        stop = first + count
        return ResultChunk(
            self.aligned.times[first:stop],
            self.aligned.durations[first:stop].tolist(),
            tables,
            skips,
            [(tick, record) for tick, _, record in errors],
        )

    def _deliver(self, first, count, chunk, outcomes, started):
        """Commit the chunk: at once without callbacks, else tick by tick between callbacks."""
        engine = self.engine
        if not self.callbacks:
            if count:
                engine.results.commit(chunk)
                self._finish(first + count - 1, outcomes)
            return
        for tick in range(count):
            if not started:
                engine._notify("on_step_start", self.aligned.sample(first + tick))
            if count > 1:
                self._persist_tick(outcomes, tick, len(outcomes))
            engine.results.commit(chunk.rows(tick, tick + 1))
            self._finish(first + tick, outcomes)
            engine.step_results = StepResults(outcomes, tick)
            engine._notify("on_step_end", self.aligned.sample(first + tick))
            self.done += 1
            engine._notify("on_progress", self.done, self.total)

    def _finish(self, index, outcomes):
        """Move the engine to a committed tick: its position and the states of its twins."""
        self.engine.position = self.aligned.times[index]
        for outcome in outcomes:
            if outcome.state is not UNCHANGED:
                self.engine.module_states[outcome.twin.path] = outcome.state

    def _fail(self, first, outcomes, failure, single):
        """Announce the failing tick, persist what it read and raise its error."""
        if self.callbacks and not single:
            self.engine._notify("on_step_start", self.aligned.sample(first + failure.tick))
            self._persist_tick(outcomes, failure.tick, failure.index + 1)
        if self.plan.kind == "simulate":
            raise failure.error
        module = self.plan.twins[failure.index].module
        raise RunError(f"{module.path}: {failure.error}", code="step") from failure.error

    def _persist_last(self, outcomes, failure, count):
        """Set the inputs of each twin's last applied tick, as a tick loop leaves the plant.

        The twins up to the failing one read the failing tick; those after it stop before it.
        """
        last = count if failure is not None else count - 1
        for index, outcome in enumerate(outcomes):
            limit = last - 1 if failure is not None and index > failure.index else last
            for tick in range(limit, -1, -1):
                if self._set(outcome, tick):
                    break

    def _persist_tick(self, outcomes, tick, twins):
        """Set the inputs of one tick for the first ``twins`` twins."""
        for outcome in outcomes[:twins]:
            self._set(outcome, tick)

    def _set(self, outcome, tick):
        """Persist the inputs of one tick on the twin's module; return whether it did."""
        block = outcome.block
        if not block.applied[tick]:
            return False
        values = {name: float(array[tick]) for name, array in block.inputs.items()}
        try:
            outcome.twin.module._set_inputs(values)
        except Exception:
            return False
        return True


def row_code(error, inlet=False):
    """Return the code in ``gm.errors.ROW_CODES`` of the exception that failed a row.

    ``inlet`` tells that the row failed on the limits of an inlet stream.
    """
    if inlet:
        return "invalid_inlet"
    code = error.code if isinstance(error, GeminiError) else None
    if code == "loop_not_converged":
        return "no_convergence"
    if code in ("no_convergence", "out_of_range"):
        return code
    if isinstance(error, ValidationError) and code in ("out_of_bounds", "invalid_value"):
        return "out_of_bounds"
    return "module_error"


def error_record(path, error, inlet=False):
    """Return the problem of the exception of a twin, with its row code.

    The path is the one the error names, the module that raised, else the path of the twin.
    """
    where = getattr(error, "path", None) if isinstance(error, GeminiError) else None
    return problem(where or path, row_code(error, inlet), error)


def _add_skips(skips, outcome, count):
    """Count, per tick, the reason a twin skipped it."""
    block = outcome.block
    for code, reason in enumerate(block.reasons, 1):
        for tick in np.flatnonzero(block.status[:count] == code):
            skips[tick].setdefault(outcome.twin.path, {})[reason] = 1
