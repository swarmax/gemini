"""One finite execution loop for assumed inputs, measured history and periodic live windows."""

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gemini import runtime
from gemini._utils.jsonable import to_plain
from gemini._utils.strings import close_matches, did_you_mean
from gemini._utils.time import to_timedelta, to_utc
from gemini.engine import checkpoint as storage
from gemini.engine import eager  # noqa: F401
from gemini.engine.clock import Clock
from gemini.engine.executor import executor_for
from gemini.engine.loader import Loader
from gemini.engine.runner import Runner
from gemini.engine.step import BindingPlan
from gemini.errors import RunError, ValidationError
from gemini.errors.base import check_on_error
from gemini.modules._utils import serialization
from gemini.modules.module import Module, class_path, import_class
from gemini.ops import kernels
from gemini.plants.plant import Plant
from gemini.run.dataset import as_dataset
from gemini.run.results import Results, declared_quantities, declared_units


def _live_ticks(position, start, end, step):
    """Return the ticks of a fixed grid in ``(position, end]``.

    The grid is anchored at the committed position, so it stays the same across live calls;
    the first call anchors it at the first supplied row.
    """
    step = to_timedelta(step)
    if position is None:
        return pd.date_range(to_utc(start), to_utc(end), freq=step)
    ticks = pd.date_range(to_utc(position), to_utc(end), freq=step)
    return ticks[ticks > pd.Timestamp(to_utc(position))]


def _plant_dict(plant):
    """Return what a checkpoint stores of ``plant``; a root that is no plant has its tree.

    A plant stores its plant dict and the state of every module, which holds what the case set
    for the run.
    """
    if isinstance(plant, Plant):
        return {"plant": plant.to_dict(), "state": plant.state_dict()}
    return serialization.tree_dict(plant)


def _rebuilt(cls, data):
    """Return the root ``_plant_dict`` stored, of class ``cls``."""
    if issubclass(cls, Plant):
        return cls.from_dict(data["plant"]).set_state_dict(data["state"])
    return serialization.tree_from_dict(cls, data)


class Engine:
    """Run a plant on a finite clock, retaining all state needed for explicit checkpoint/resume.

    An engine belongs to one plant and one thread: plants and engines are not shared across
    threads, so each worker loads its own plant and builds its own engine. ``backend`` names the
    backend that evaluates the run (``"numpy"`` over arrays, ``"python"`` row by row); every
    backend gives the same numbers.
    """

    def __init__(self, plant, backend="numpy", callbacks=None, on_error="raise", compile=True):
        """Configure the plant to run, its backend, lifecycle callbacks and the error policy.

        With the default ``on_error="raise"`` an ordinary error ends the run; with ``"record"``
        it becomes a row of ``results.errors()`` and the run continues. With ``compile=True`` the
        plant runs through the compiler when ``gemini.compiler`` is imported; ``compile=False``
        runs it eagerly, as a direct call does.
        """
        if not isinstance(plant, Module):
            raise ValidationError(
                f"Engine: plant = {type(plant).__name__}; expected a plant or module"
            )
        check_on_error(on_error)
        kernels.get(backend)
        self.plant = plant
        self.backend = backend
        self.callbacks = list(callbacks or [])
        self.on_error = on_error
        self.results = None
        self.dataset = None
        self.clock = None
        self.run_kind = None
        self.position = None
        self.only = None
        self.module_states = {}
        self.runtime_state = runtime.state()
        self._dataset_fingerprint = None
        self._max_gap = None
        self._in_step = False
        self.compile = compile
        self._executor = executor_for(plant, compile)
        self.graph_breaks = {}
        self.step_results = {}

    def simulate(self, profile, clock=None):
        """Evaluate the plant on assumed, root-bound inputs and return ``Results``.

        ``profile`` is a ``Dataset`` or a DataFrame with a timezone-aware UTC index and one
        column per binding ``column`` (or per input path), in the units of the bindings. Without
        ``clock`` the ticks are those of the profile.
        """
        dataset = as_dataset(profile)
        clock = clock if clock is not None else Clock.from_data(dataset)
        return self._run("simulate", dataset, clock)

    def replay(self, data, start=None, end=None, state=None, clock=None, only=None):
        """Evaluate measured equipment boundaries and return ``Results``.

        ``data`` is a ``Dataset`` or a DataFrame as in ``simulate``; ``start`` and ``end`` select
        a window. Observation ticks are inferred unless ``clock`` is given. ``state`` is the
        ``end_state`` of a former run: stateful modules continue from it and ticks up to its
        position are not evaluated, so two consecutive replays give the numbers of one.
        ``results.end_state`` holds the state after the last tick.
        """
        dataset = as_dataset(data)
        if start is not None or end is not None:
            dataset = dataset.window(start, end)
            if clock is not None:
                clock = clock.window(start, end)
        if clock is None:
            clock = Clock.from_data(dataset)
        return self._run("replay", dataset, clock, only=only, state=state)

    def live(self, source, checkpoint=None, step=None, now=None, sink=None):
        """Process newly available ticks once, then save; an external scheduler calls again.

        Returns only this call's new rows. The engine and checkpoint retain cumulative results.
        An existing checkpoint contributes the committed position, results, module states, clock
        step and runtime settings, and must have been saved for a plant of the same class; without
        ``checkpoint`` the engine continues from its own committed position. Without ``step`` the
        ticks are the new rows; a call with fewer than two rows reuses the checkpointed step for
        its final interval. The checkpoint commits before sink delivery; external sinks should
        upsert by timestamp.
        """
        dataset = as_dataset(source)
        if checkpoint is not None and Path(checkpoint).exists():
            self._restore_live(checkpoint)
        elif checkpoint is not None or self.run_kind != "live":
            self._start_live()
        now = to_utc(now) if now is not None else datetime.now(timezone.utc)
        clock = self._live_clock(dataset, step, now)
        offset = len(self.results)
        with self._saved_settings():
            self._run("live", dataset, clock, continuing=True)
        if checkpoint is not None:
            self.to_checkpoint(checkpoint)
        fresh = self.results.slice(offset)
        if sink is not None and len(fresh):
            sink(fresh)
        return fresh

    def _start_live(self):
        """Forget any earlier run: the next live call starts from the first row."""
        self.position = None
        self.results = Results()
        self.module_states = {}
        self.clock = None
        self.runtime_state = runtime.state()

    def _restore_live(self, path):
        """Take the run state of a live checkpoint saved for this engine's plant class."""
        checkpoint = storage.from_file(path)
        if checkpoint.run_kind != "live":
            raise RunError(
                f"{path}: run_kind = {checkpoint.run_kind!r}; expected 'live'", code="checkpoint"
            )
        supplied = class_path(type(self.plant))
        if checkpoint.plant_class != supplied:
            raise RunError(
                f"{path}: plant_class = {checkpoint.plant_class!r}; expected the supplied "
                f"plant's {supplied!r}",
                code="checkpoint",
            )
        self._restore(checkpoint, Path(path).parent)

    def _live_clock(self, dataset, step, now):
        """Return the unprocessed ticks up to ``now`` and the newest supplied row."""
        if not len(dataset):
            return Clock([])
        end = min(now, dataset.end)
        if step is not None:
            return Clock(_live_ticks(self.position, dataset.start, end, step), step)
        clock = Clock.from_data(dataset.window(end=end))
        if self.position is None:
            return clock
        if len(clock) < 2 and self.clock is not None:
            clock = Clock(clock.ticks, self.clock.step)
        return clock.after(self.position)

    def _saved_settings(self):
        """Return a context applying the precision and display units saved for this run.

        The default fluid is not re-applied: it only seeds newly built modules and streams,
        and the plant, built before the run, already carries its fluids.
        """
        values = dict(self.runtime_state)
        values.pop("default_fluid", None)
        return runtime.settings(**values)

    def _remaining(self, clock):
        """Return the ticks of ``clock`` after the committed position."""
        return clock.after(self.position) if self.position is not None else clock

    def _notify(self, method, *args):
        for callback in self.callbacks:
            getattr(callback, method)(self, *args)

    def _run(self, kind, dataset, clock, only=None, continuing=False, max_gap=None, state=None):
        """Run the unfinished ticks of ``clock``; ``max_gap`` overrides the Loader default."""
        plant = self.plant
        plant._check_design()
        if not continuing:
            self.runtime_state = runtime.state()
        plan = BindingPlan(plant, dataset, kind, only, self.on_error)
        if not continuing:
            self._begin(state)
        self.results.declared = declared_units(plant)
        self.results.quantities = declared_quantities(plant)
        self.run_kind = kind
        self.dataset = dataset
        self.clock = clock
        if not continuing or kind == "live" or self._dataset_fingerprint is None:
            self._dataset_fingerprint = dataset.fingerprint()
        self.only = list(only) if only is not None else None
        self.graph_breaks = {}
        remaining = self._remaining(clock)
        loader = Loader(
            dataset,
            remaining.ticks,
            columns=sorted(plan.columns),
            max_gap=max_gap,
            durations=remaining.durations,
        )
        self._max_gap = loader.max_gap
        try:
            with runtime.settings(backend=self.backend):
                self._notify("on_run_start")
                Runner(self, plan, loader.arrays()).run()
                self._notify("on_run_end")
        except BaseException as exc:
            self._in_step = False
            self._notify("on_error", exc)
            raise
        finally:
            self.results.end_state = self._end_state()
        return self.results

    def _begin(self, state):
        """Start empty results, from the module states and position of ``state`` when given."""
        self.results = Results()
        self.module_states, self.position = {}, None
        if state is None:
            return
        self._check_state(state)
        self.module_states = deepcopy(state["module_states"])
        position = state["position"]
        self.position = to_utc(position) if position is not None else None

    def _check_state(self, state):
        """Require the shape ``end_state`` has: a position and the states of known modules."""
        if not (
            isinstance(state, Mapping)
            and {"position", "module_states"} <= state.keys()
            and isinstance(state["module_states"], Mapping)
        ):
            raise ValidationError(
                "Engine.replay: state = "
                f"{type(state).__name__}; expected the end_state of a former run "
                "({position, module_states})",
                path="state",
            )
        known = {path for path, _ in self.plant.named_modules()}
        unknown = sorted(set(state["module_states"]) - known)
        if unknown:
            raise ValidationError(
                f"Engine.replay: state.module_states = {unknown[0]!r}; expected a module path "
                f"of this plant{did_you_mean(unknown[0], known)}",
                path="state.module_states",
                code="unknown_name",
                suggestions=close_matches(unknown[0], known),
            )

    def _end_state(self):
        """Return the position and module states as plain JSON: the input of ``state=``."""
        return to_plain({"position": self.position, "module_states": self.module_states})

    def to_checkpoint(self, path):
        """Save at a step boundary; before the first run the checkpoint holds no results."""
        if self._in_step:
            raise RunError(
                f"{path}: called inside a step; expected a completed step", code="checkpoint"
            )
        checkpoint = storage.Checkpoint(
            run_kind=self.run_kind,
            plant_class=class_path(type(self.plant)),
            plant=_plant_dict(self.plant),
            module_states=self.module_states,
            clock=self.clock.describe() if self.clock is not None else None,
            position=self.position,
            dataset_fingerprint=self._dataset_fingerprint,
            only=self.only,
            on_error=self.on_error,
            backend=self.backend,
            compile=self.compile,
            runtime=self.runtime_state,
        )
        storage.to_file(path, checkpoint, self.results, self._unfinished_rows(), self._max_gap)

    def _unfinished_rows(self):
        """Return the rows a resumed simulation or replay still reads, or None.

        Rows up to ``max_gap`` before the position stay because a held previous row may still
        supply the next ticks. Live checkpoints store no rows: every call supplies its own.
        """
        if self.run_kind not in {"simulate", "replay"} or self.dataset is None:
            return None
        if self.position is None or self._max_gap is None:
            return self.dataset
        if self.clock is None or not len(self._remaining(self.clock)):
            return None
        return self.dataset.window(start=self.position - self._max_gap)

    @classmethod
    def from_checkpoint(cls, path, callbacks=None):
        """Restore a plant, dataset handle, finite schedule, states and completed results."""
        checkpoint = storage.from_file(path)
        plant = _rebuilt(import_class(checkpoint.plant_class), checkpoint.plant)
        engine = cls(plant, checkpoint.backend, callbacks, checkpoint.on_error, checkpoint.compile)
        engine._restore(checkpoint, Path(path).parent)
        return engine

    def _restore(self, checkpoint, folder):
        """Assign the saved run state; the plant, callbacks and error policy stay unchanged."""
        self.run_kind = checkpoint.run_kind
        self.position = checkpoint.position
        self.module_states = checkpoint.module_states
        self.only = checkpoint.only
        self.runtime_state = checkpoint.runtime or runtime.state()
        self.clock = Clock.reopen(checkpoint.clock) if checkpoint.clock is not None else None
        self._dataset_fingerprint = checkpoint.dataset_fingerprint
        self.dataset = None
        self._max_gap = None
        if checkpoint.remaining_data_file:
            self.dataset, self._max_gap = storage.from_rows(folder / checkpoint.remaining_data_file)
        self.results = (
            Results.from_npz(folder / checkpoint.results_file)
            if checkpoint.results_file
            else Results()
        )

    def resume(self):
        """Continue strictly after the saved position, or return stored results when finished."""
        if self.run_kind is None:
            return self.results if self.results is not None else Results()
        if self.clock is None:
            raise RunError(
                f"{self.run_kind} checkpoint: clock = None; expected a clock", code="checkpoint"
            )
        remaining = self._remaining(self.clock)
        if not len(remaining):
            return self.results
        if self.dataset is None:
            raise RunError(
                f"{self.run_kind} checkpoint: {len(remaining)} unfinished ticks and no stored "
                "rows; expected the rows saved with an unfinished simulation or replay",
                code="checkpoint",
            )
        with self._saved_settings():
            return self._run(
                self.run_kind,
                self.dataset,
                self.clock,
                only=self.only,
                continuing=True,
                max_gap=self._max_gap,
            )
