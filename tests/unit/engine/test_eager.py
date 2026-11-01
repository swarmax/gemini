"""The eager executor: arrays when it can, rows when it must, the numbers of the compiler."""

import time

import numpy as np
import pytest

import gemini as gm
from gemini import ops
from gemini.compiler.executor import GraphExecutor
from gemini.engine.eager import EagerExecutor, _by_rows
from gemini.engine.executor import executor_for
from gemini.errors import PhysicsError
from gemini.modules import Module
from gemini.modules.declarations import Control, Inlet, Outlet, Output
from gemini.plants._utils.plan import Solve
from gemini.types import Stream
from tests.fixtures.engine_plants import (
    Booster,
    holder_plant,
    loop_plant,
    pair_frame,
    pair_plant,
)
from tests.fixtures.parity import assert_frames_match


def _run(plant, frame, compile):
    """Replay ``frame`` on ``plant`` and return the engine."""
    engine = gm.Engine(plant, on_error="record", compile=compile)
    engine.replay(gm.Dataset.from_frame(frame))
    return engine


@pytest.mark.parametrize(
    "make",
    [pair_plant, lambda: pair_plant(with_tank=True), holder_plant],
    ids=["pair", "stateful", "composite"],
)
def test_eager_and_compiled_runs_give_the_same_numbers_and_errors(make):
    """Rows that fail, rows that work and a stateful twin agree between the executors."""
    frame = pair_frame({("level", 4): -1.0, ("level", 7): 0.0, ("flow", 9): np.nan})
    eager, compiled = (_run(make(), frame, compile) for compile in (False, True))
    assert isinstance(eager._executor, EagerExecutor)
    assert isinstance(compiled._executor, GraphExecutor)
    assert len(compiled.results.errors()) >= 2
    assert_frames_match(eager.results.to_frame(), compiled.results.to_frame())
    assert eager.results.failures == compiled.results.failures
    assert eager.module_states == compiled.module_states


def _streams(rows=3):
    return {
        "fluid_in": gm.Stream(
            m_dot=gm.units.Quantity(np.full(rows, 1.0), "kg/s"),
            T=gm.units.Quantity(np.full(rows, 300.0), "K"),
            p=gm.units.Quantity(np.full(rows, 1e5), "Pa"),
            fluid=gm.WATER,
        )
    }


def test_rows_that_all_work_are_one_array_call(monkeypatch):
    """No row is called for real when the array call works."""
    monkeypatch.setattr(EagerExecutor, "_rows", None)
    executor = EagerExecutor()
    prepared = executor.prepare(Booster(), _streams(), {"level": np.array([1.0, 2.0, 3.0])}, False)
    evaluation = executor.evaluate(prepared, 3, {})
    assert not evaluation.failed.any() and evaluation.breaks == []
    assert evaluation.result.outputs["rise"].tolist() == [2.0, 4.0, 6.0]
    assert evaluation.result.row(1).outputs.rise == 4.0


@ops.physics
def _reciprocal(level):
    """Return ``1 / level`` of a positive level."""
    ops.check(level > 0, PhysicsError, "gate: level = {level}", level=level)
    return 1.0 / level


class Gate(Module):
    """A module that stops at zero level: the check sits in a branch ``where`` drops there."""

    def __init__(self):
        """Declare a level, an inlet, a rate and an outlet."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.level = Control(float)

        # Outputs
        self.rate = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Return the stream and the rate, zero when stopped."""

        # Outlets
        self.rate = ops.where(self.level == 0, 0.0, _reciprocal(self.level))
        return dict(fluid_out=inlets.fluid_in)


def _evaluations(module, levels):
    """Return the evaluation of the array call, and the one of the rows, of ``levels``."""
    executor = EagerExecutor()
    prepared = executor.prepare(module, _streams(len(levels)), {"level": np.array(levels)}, False)
    rows = executor._rows(prepared, len(levels), {})
    executor._rows = None
    return executor.evaluate(prepared, len(levels), {}), rows


def test_rows_that_fail_a_check_are_failed_rows_of_one_array_call():
    """A stopped row is dropped by ``where``, a failing one fails with the row call's error."""
    evaluation, rows = _evaluations(Gate(), [2.0, 0.0, -1.0, 4.0, -3.0])
    assert evaluation.failed.tolist() == rows.failed.tolist() == [False, False, True, False, True]
    assert evaluation.breaks == []
    for row in (2, 4):
        assert type(evaluation.error(row)) is type(rows.error(row)) is PhysicsError
        assert str(evaluation.error(row)) == str(rows.error(row))
    ok = ~evaluation.failed
    assert evaluation.result.outputs["rate"][ok].tolist() == [0.5, 0.0, 0.25]
    assert rows.result.outputs["rate"][ok].tolist() == [0.5, 0.0, 0.25]


def test_an_inline_check_leaves_out_its_rows_and_the_others_stay_on_arrays():
    """A check in ``forward`` raises, per its rows: the array call runs again on the rest."""
    module = Booster()
    executor = EagerExecutor()
    prepared = executor.prepare(module, _streams(), {"level": np.array([1.0, -1.0, 2.0])}, False)
    rows = executor._rows(prepared, 3, {})
    executor._rows = None
    evaluation = executor.evaluate(prepared, 3, {})
    assert evaluation.failed.tolist() == rows.failed.tolist() == [False, True, False]
    assert str(evaluation.error(1)) == str(rows.error(1)) and "level = -1.0" in str(rows.error(1))
    assert evaluation.result.outputs["rise"][[0, 2]].tolist() == [2.0, 4.0]
    assert evaluation.breaks == []


def test_an_array_call_that_cannot_run_falls_back_to_the_rows_and_says_why(monkeypatch):
    """What no row can be blamed for makes the rows the reference; ``breaks`` keeps the reason."""
    module = Booster()
    monkeypatch.setattr(Booster, "forward", lambda self, inlets: 1 / int(self.level == 1.0))
    executor = EagerExecutor()
    prepared = executor.prepare(module, _streams(), {"level": np.array([1.0, 1.0, 2.0])}, False)
    evaluation = executor.evaluate(prepared, 3, {})
    assert evaluation.failed.all()
    assert evaluation.breaks[0][0] == module.path
    assert "array call raised" in evaluation.breaks[0][1]


def test_stateless_modules_are_called_once_on_arrays():
    """A stateless leaf takes the array path; state, hooks and the Python backend take rows."""
    module = Booster()
    assert not _by_rows(module)
    module.register_forward_pre_hook(lambda module, inlets: None)
    assert _by_rows(module)
    assert _by_rows(pair_plant(with_tank=True))
    with gm.runtime.settings(backend="python"):
        assert _by_rows(Booster())


def test_compile_false_or_no_compiler_runs_eager(monkeypatch):
    """Only a registered compiled executor is used, and only when asked for."""
    plant = pair_plant()
    assert isinstance(executor_for(plant, compile=True), GraphExecutor)
    assert isinstance(executor_for(plant, compile=False), EagerExecutor)
    monkeypatch.setattr("gemini.engine.executor._FACTORIES", {"eager": lambda plant: "eager"})
    assert executor_for(plant, compile=True) == "eager"


def test_the_compiler_returns_the_executor_of_a_plant():
    """``gm.compiler.compile`` shares the plant's graphs between executors."""
    plant = pair_plant()
    first, second = gm.compiler.compile(plant), gm.compiler.compile(plant)
    assert first.cache is second.cache


def test_a_plant_with_a_loop_runs_on_arrays_with_the_numbers_of_its_rows(monkeypatch):
    """No row is called for real, and each row has the tear it has alone."""
    ring = loop_plant()
    assert not _by_rows(ring)
    executor = EagerExecutor()
    inputs = {"warmer.target": np.linspace(310.0, 350.0, 5)}
    prepared = executor.prepare(ring, {}, inputs, False)
    rows = executor._rows(prepared, 5, {})
    monkeypatch.setattr(EagerExecutor, "_rows", None)
    evaluation = executor.evaluate(prepared, 5, {})
    assert evaluation.breaks == [] and not evaluation.failed.any()
    found = evaluation.result.children["carrier"].inlets.fluid_in.T
    assert found.tolist() == rows.result.children["carrier"].inlets.fluid_in.T.tolist()
    assert found[0] != found[4]


def test_a_plant_with_a_constraint_still_goes_by_rows():
    """A solve is brentq on one row at a time: the plant is called for each row."""
    plant = gm.plants.get("BoilerChpPlant")
    assert any(isinstance(item, Solve) for item in plant._compiled().items)
    assert _by_rows(plant)


def test_a_plant_with_a_loop_runs_on_arrays_eager_and_compiled_with_the_numbers_of_its_rows(
    monkeypatch,
):
    """Eager arrays, compiled arrays and row by row agree, and the array modes call no row."""
    ring = loop_plant()
    inputs = {"warmer.target": np.linspace(310.0, 350.0, 40)}
    eager, compiled = EagerExecutor(), gm.compiler.compile(ring)
    prepared = {
        "rows": eager.prepare(ring, {}, inputs, False),
        "eager": eager.prepare(ring, {}, inputs, False),
        "compiled": compiled.prepare(ring, {}, inputs, False),
    }
    by_rows = eager._rows(prepared["rows"], 40, {})
    monkeypatch.setattr(EagerExecutor, "_rows", None)
    started = time.perf_counter()
    arrays = {
        "eager": eager.evaluate(prepared["eager"], 40, {}),
        "compiled": compiled.evaluate(prepared["compiled"], 40, {}),
    }
    assert time.perf_counter() - started < 1.0
    expected = by_rows.result.children["carrier"].inlets.fluid_in.T
    for mode, evaluation in arrays.items():
        assert evaluation.breaks == [] and not evaluation.failed.any(), mode
        found = evaluation.result.children["carrier"].inlets.fluid_in.T
        assert found == pytest.approx(expected, rel=1e-9, abs=1e-9), mode
