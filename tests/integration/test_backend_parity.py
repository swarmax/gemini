"""Every backend in ``BACKENDS`` gives the same run: values, errors, skips, results and events.

Whole engine runs on a short window, one test per property, each comparing every backend with the
reference. Cheap module cases are the per-module tests that call ``assert_module_matches``;
``test_every_shipped_leaf_module_has_a_parity_test`` checks that none is missing. Adding a backend
means adding it to ``tests.fixtures.parity.BACKENDS``.
"""

import ast
import copy
import functools
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from gemini import ops
from gemini.engine.callbacks import AutoCheckpoint, Callback
from gemini.modules import ModuleDict, ModuleList
from gemini.types import Health
from tests.conftest import shipped_module_classes
from tests.fixtures import ROOT
from tests.fixtures.engine_plants import Booster, holder_plant, pair_frame, pair_plant
from tests.fixtures.engine_tank import ROW, TIME, tank
from tests.fixtures.parity import (
    BACKENDS,
    REFERENCE,
    assert_equal,
    assert_frames_match,
    assert_runs_match,
    on_each_backend,
    others,
    run_engine,
)

ROWS = 48
PLAIN_TYPES = {"float", "bool", "int", "str", "NoneType", "list"}


def _dataset(frame):
    return gm.Dataset.from_frame(frame, time_column="time")


def _faulted(frame):
    """Return ``frame`` with missing values, negative values and absurd values at fixed rows."""
    faulted = frame.copy()
    numeric = [
        column
        for column in faulted.columns
        if column != "time" and pd.api.types.is_numeric_dtype(faulted[column])
    ]
    rng = np.random.default_rng(7)
    for stride, start, value, count in ((2, 0, np.nan, 2), (4, 1, -1e7, 1), (6, 3, 1e12, 1)):
        for column in numeric[start::stride]:
            rows = faulted.index[rng.integers(0, len(faulted), count)]
            faulted.loc[rows, column] = value
    return faulted


@pytest.fixture(scope="module")
def window(fast_frame):
    """Return the clean short window of the doublet heat data."""
    return fast_frame.iloc[:ROWS]


@pytest.fixture(scope="module")
def faulted_window(window):
    """Return the window with faults."""
    return _faulted(window)


@pytest.fixture(scope="module")
def clean(shared_plant, window):
    """Return the snapshot of the clean replay on every backend."""
    return on_each_backend(
        lambda backend: run_engine(copy.deepcopy(shared_plant), _dataset(window))
    )


@pytest.fixture(scope="module")
def faulty(shared_plant, faulted_window):
    """Return the snapshot of the faulted replay on every backend."""
    return on_each_backend(
        lambda backend: run_engine(copy.deepcopy(shared_plant), _dataset(faulted_window))
    )


def test_a_run_with_the_backend_forced_explicitly_works_on_every_backend():
    """Forcing a backend around the whole call, tracing included, runs a replay."""
    frame = pd.DataFrame(
        {name: [value] * 2 for name, value in ROW.items()},
        index=pd.date_range(TIME, periods=2, freq="15min"),
    )

    def replay(backend):
        return gm.Engine(tank(), backend).replay(gm.Dataset.from_frame(frame)).to_frame()

    for backend, frame_of in on_each_backend(replay).items():
        assert frame_of["flow"].tolist() == [2.0, 2.0], backend


def test_replay_of_doublet_heat_is_the_same_run_on_every_backend(clean):
    """Frame, skips, errors, summary, inputs, hooks, result trees and events are equal."""
    assert_runs_match(clean)
    reference = clean[REFERENCE]
    assert len(reference.frame) == ROWS and not reference.errors
    assert all(reasons == [] for reasons in reference.breaks.values())


@pytest.fixture(scope="module")
def repeated(shared_plant, faulted_window):
    """Return, per backend, two runs of the same faulted input on fresh plants."""
    return on_each_backend(
        lambda backend: [
            run_engine(copy.deepcopy(shared_plant), _dataset(faulted_window)) for _ in range(2)
        ]
    )


def test_the_same_input_gives_the_same_numbers_on_every_backend(repeated):
    """Two runs of one input are bit-identical on a backend, and the backends agree."""
    for backend, (first, second) in repeated.items():
        pd.testing.assert_frame_equal(first.frame, second.frame, check_exact=True)
        assert first.skips == second.skips and first.errors == second.errors, backend
        assert first.states == second.states and first.events == second.events, backend
    reference = repeated[REFERENCE][0]
    for name, (first, _) in others(repeated):
        assert_frames_match(first.frame, reference.frame)


def test_faulted_rows_give_the_same_errors_and_skips(faulty):
    """Every error has the same class, message, module and tick; every skip the same count."""
    reference = faulty[REFERENCE]
    assert len(reference.errors) >= 3 and sum(map(len, reference.skips.values())) >= 3
    for name, outcome in others(faulty):
        assert_equal(outcome.errors, reference.errors, f"{name} errors")
        assert outcome.skips == reference.skips
        assert_frames_match(outcome.frame, reference.frame)
        assert_equal(outcome.steps, reference.steps, f"{name} steps")


def test_raise_stops_at_the_same_row_with_the_same_chained_error(shared_plant, faulted_window):
    """``on_error="raise"`` ends the run with the same ``RunError`` and cause on every backend."""
    outcomes = on_each_backend(
        lambda backend: run_engine(
            copy.deepcopy(shared_plant), _dataset(faulted_window), on_error="raise"
        )
    )
    reference = outcomes[REFERENCE]
    assert reference.failure[0] == "RunError" and reference.failure[2] == "PhysicsError"
    assert_runs_match(outcomes)


def test_a_stateful_twin_gives_the_same_states_and_results():
    """The reservoir twin carries its total next to the traced boosters on every backend."""
    outcomes = on_each_backend(
        lambda backend: run_engine(pair_plant(with_tank=True), pair_frame_dataset())
    )
    assert_runs_match(outcomes)
    assert outcomes[REFERENCE].states["tank"]["total"] > 0


def pair_frame_dataset(changes=None):
    """Return the dataset of the synthetic pair."""
    return gm.Dataset.from_frame(pair_frame(changes))


def test_a_composite_twin_gives_the_same_result_tree():
    """The duo's tree has its children and called order on every backend, rows failing included."""
    outcomes = on_each_backend(
        lambda backend: run_engine(holder_plant(), pair_frame_dataset({("level", 4): -1.0}))
    )
    assert_runs_match(outcomes)
    tree = outcomes[REFERENCE].steps[0]["trees"]["duo"]
    assert list(tree["children"]) == ["front", "back"] and tree["called"] == ["front", "back"]
    assert tree["children"]["back"]["outputs"].keys() == tree["children"]["front"]["outputs"].keys()
    assert len(outcomes[REFERENCE].errors) == 1


def _simulate(plant, frame):
    data = _dataset(frame)
    return on_each_backend(
        lambda backend: run_engine(
            copy.deepcopy(plant), data, "simulate", gm.engine.Clock.from_data(data)
        )
    )


@pytest.fixture(scope="module")
def simulated(shared_plant, window):
    """Return the clean simulation on every backend."""
    return _simulate(shared_plant, window)


@pytest.fixture(scope="module")
def simulated_faulty(shared_plant, faulted_window):
    """Return the simulation of the faulted window on every backend."""
    return _simulate(shared_plant, faulted_window)


def test_simulate_gives_the_same_run(simulated):
    """Root-bound simulation of the plant: results and tick views are equal."""
    assert_runs_match(simulated)
    assert len(simulated[REFERENCE].frame) == ROWS


def test_simulate_with_faults_gives_the_same_errors_and_skips(simulated_faulty):
    """A failing or incomplete step is recorded under the plant path the same way."""
    assert_runs_match(simulated_faulty)
    assert simulated_faulty[REFERENCE].errors or simulated_faulty[REFERENCE].skips


@pytest.fixture(scope="module")
def lived(shared_plant, window, tmp_path_factory):
    """Return, per backend, two overlapping live calls and the cumulative results."""
    folder = tmp_path_factory.mktemp("live")
    times = window.time

    def live(backend):
        engine, path = gm.Engine(copy.deepcopy(shared_plant), backend), folder / f"{backend}.json"
        first = engine.live(_dataset(window.iloc[:10]), path, now=times.iloc[9])
        second = engine.live(_dataset(window.iloc[5:20]), path, now=times.iloc[19])
        return first.to_frame(), second.to_frame(), engine.results.to_frame(), engine.position

    return on_each_backend(live)


def test_live_calls_give_the_same_new_rows_and_cumulative_results(lived):
    """Overlapping live calls process each tick once and agree on every backend."""
    reference = lived[REFERENCE]
    assert len(reference[1]) == 10 and len(reference[2]) == 20
    for name, outcome in others(lived):
        for part, expected in zip(outcome[:3], reference[:3]):
            assert_frames_match(part, expected)
        assert outcome[3] == reference[3]


def test_event_log_events_are_the_same_except_timing(faulty):
    """Forward events (children first), error events and step ends are equal, with errors."""
    reference = faulty[REFERENCE].events
    kinds = {event["kind"] for event in reference}
    assert {"run_start", "forward", "error", "step_end", "run_end"} <= kinds
    for name, outcome in others(faulty):
        assert_equal(outcome.events, reference, f"{name} events")


def test_a_composite_logs_its_children_before_itself_on_every_backend():
    """The events of a duo tick are front, back, then duo, the same everywhere."""
    outcomes = on_each_backend(lambda backend: run_engine(holder_plant(), pair_frame_dataset()))
    for outcome in outcomes.values():
        paths = [e["module_path"] for e in outcome.events if e["kind"] == "forward"][:3]
        assert paths == ["duo.front", "duo.back", "duo"]
    assert_equal(outcomes[BACKENDS[-1]].events, outcomes[REFERENCE].events, "events")


class Stop(Callback):
    """Interrupt the run after ``after`` results."""

    def __init__(self, after):
        """Remember when to stop."""
        self.after = after

    def on_step_end(self, engine, sample):
        """Raise an interrupt once enough ticks are committed."""
        if len(engine.results) == self.after:
            raise KeyboardInterrupt


@pytest.fixture(scope="module")
def resumed(shared_plant, window, tmp_path_factory):
    """Return, per backend, a run interrupted at tick 12, resumed, and the uninterrupted run."""
    folder = tmp_path_factory.mktemp("resume")
    short = _dataset(window.iloc[:24])

    def interrupted(backend):
        path = folder / f"{backend}.json"
        engine = gm.Engine(
            copy.deepcopy(shared_plant), backend, [AutoCheckpoint(path, every=5), Stop(12)]
        )
        with pytest.raises(KeyboardInterrupt):
            engine.replay(short)
        engine = gm.Engine.from_checkpoint(path)
        return engine.resume().to_frame(), engine.position, engine.module_states

    return {
        "resumed": on_each_backend(interrupted),
        "whole": on_each_backend(lambda backend: run_engine(copy.deepcopy(shared_plant), short)),
    }


def test_autocheckpoint_and_resume_equal_an_uninterrupted_run_on_every_backend(resumed):
    """A run interrupted and resumed gives the uninterrupted run, and the same on each backend."""
    for backend, (frame, position, states) in resumed["resumed"].items():
        whole = resumed["whole"][backend]
        assert_frames_match(frame, whole.frame)
        assert position == whole.position
        assert_equal(states, whole.states, f"{backend} states")
    for name, (frame, _, _) in others(resumed["resumed"]):
        assert_frames_match(frame, resumed["resumed"][REFERENCE][0])


def test_health_columns_are_the_same(faulty, clean):
    """Score, alarm, message and assessed flags of every twin are equal, with failing rows."""
    for outcomes in (clean, faulty):
        columns = [c for c in outcomes[REFERENCE].frame.columns if ".health" in c]
        assert any(name.endswith(".health_score") for name in columns)
        for name, outcome in others(outcomes):
            assert_frames_match(outcome.frame[columns], outcomes[REFERENCE].frame[columns])


def _leaf_types(tree, found):
    for section in ("outputs", "inputs"):
        found.update(type(value).__name__ for value in tree[section].values())
    for stream in (*tree["outlets"].values(), *tree["inlets"].values()):
        if not isinstance(stream, dict):
            found.add(type(stream).__name__)
            continue
        found.update(type(stream[field]).__name__ for field in ("m_dot", "T", "p"))
    for child in tree["children"].values():
        _leaf_types(child, found)
    return found


def test_output_python_types_are_plain_and_the_same_on_every_backend(clean):
    """Floats, booleans and lists are Python objects, never NumPy scalars, on every backend."""
    found = {}
    for name, outcome in clean.items():
        found[name] = set()
        for step in outcome.steps:
            for tree in step["trees"].values():
                _leaf_types(tree, found[name])
        assert found[name] <= PLAIN_TYPES, found[name]
    assert {"float", "bool", "list"} <= found[REFERENCE]
    assert all(types == found[REFERENCE] for types in found.values())


def test_optional_outputs_are_none_on_every_backend():
    """A declared ``X | None`` output is ``None`` for a stopped booster and a float otherwise."""
    outcomes = on_each_backend(
        lambda backend: run_engine(pair_plant(), pair_frame_dataset({("level", 3): 0.0}))
    )
    for outcome in outcomes.values():
        shares = [step["trees"]["first"]["outputs"]["share"] for step in outcome.steps]
        assert shares[3] is None and all(type(s) is float for s in shares[:3])
    assert_runs_match(outcomes)


@functools.cache
def _calls_assert_module_matches(path):
    tree = ast.parse(path.read_text())
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "assert_module_matches"
        for node in ast.walk(tree)
    )


def _mirror(cls):
    """Return the unit test file that mirrors the source file of ``cls``."""
    *folders, name = cls.__module__.split(".")
    return ROOT / "tests/unit" / Path(*folders[1:]) / f"test_{name}.py"


def _stateless_leaf_classes():
    """Return the shipped leaf classes with no state; stateful ones go through the engine case."""
    classes = []
    for cls in shipped_module_classes():
        if issubclass(cls, (ModuleList, ModuleDict)):
            continue
        module = cls()
        if module.is_leaf and not module.states():
            classes.append(cls)
    return classes


@pytest.fixture(scope="module")
def leaves():
    """Return the shipped stateless leaf classes."""
    return _stateless_leaf_classes()


def test_every_shipped_leaf_module_has_a_parity_test(leaves):
    """Its mirrored test file calls ``assert_module_matches``, which runs every backend."""
    missing = [cls.__name__ for cls in leaves if not _calls_assert_module_matches(_mirror(cls))]
    assert not missing, f"no assert_module_matches test for {missing}"
    assert len(leaves) > 25


def test_health_score_columns_are_float_on_every_backend_for_scores_of_exactly_0_and_1(
    monkeypatch,
):
    """A diagnostic returning the literals 1 and 0 gives a float column, like any other score."""

    def health(self, result, measured):
        error = ops.abs(result.outputs.rise - measured["rise"])
        return Health(score=ops.where(error < 1.0, 1, 0), alarm=error > 5e4, message="rise")

    monkeypatch.setattr(Booster, "health", health)
    exact = {("rise", row): 2 * (0.1 + 1.2 * row / 11) for row in range(0, 12, 2)}
    outcomes = on_each_backend(lambda backend: run_engine(pair_plant(), pair_frame_dataset(exact)))
    for outcome in outcomes.values():
        scores = outcome.frame["first.health_score"]
        assert scores.dtype == "float64" and set(scores) == {0.0, 1.0}
    assert_runs_match(outcomes)


def test_column_dtypes_are_the_same_on_every_backend(clean, faulty, simulated, simulated_faulty):
    """Every column of every whole run has the same dtype as the reference's."""
    for runs in (clean, faulty, simulated, simulated_faulty):
        for name, outcome in others(runs):
            assert outcome.frame.dtypes.tolist() == runs[REFERENCE].frame.dtypes.tolist(), name
            assert outcome.summary.dtypes.tolist() == runs[REFERENCE].summary.dtypes.tolist()


@pytest.mark.slow
def test_the_example_runner_sets_the_backend_of_the_engine_and_the_functions(tmp_path):
    """An example under ``run_example.py`` runs on the named backend at either level."""
    script = tmp_path / "probe.py"
    script.write_text(
        "import inspect\n"
        "import gemini as gm\n"
        "for function in (gm.Engine, gm.simulate, gm.replay, gm.live):\n"
        "    print(inspect.signature(function).parameters['backend'].default)\n"
    )
    env = os.environ | {"GEMINI_EXAMPLE_BACKEND": "python", "PYTHONPATH": str(ROOT)}
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tests/fixtures/run_example.py"), str(script)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.stdout.split() == ["python"] * 4, completed.stderr
