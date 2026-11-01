"""The run functions: the engine's results in one call, checkpoints and no retracing."""

import copy
import json
import sys

import pandas as pd
import pytest

import gemini as gm
from gemini.compiler.graph import graph_cache
from gemini.engine.callbacks import AutoCheckpoint, Callback
from gemini.errors import Cancelled, PhysicsError, RunError, ValidationError
from tests.fixtures.engine_plants import TICKS, pair_frame, pair_plant
from tests.fixtures.engine_tank import ROW, TIME, tank
from tests.fixtures.errors import raises
from tests.fixtures.parity import BACKENDS

ROWS = 8


def _rows():
    return gm.Dataset.from_frame(
        pd.DataFrame(
            {name: [value] * ROWS for name, value in ROW.items()},
            index=pd.date_range(TIME, periods=ROWS, freq="15min"),
        )
    )


def _pairs(changes=None):
    return gm.Dataset.from_frame(pair_frame(changes))


class Stop(Callback):
    """Cancel the run after ``count`` committed ticks."""

    def __init__(self, count):
        """Remember when to stop."""
        self.count = count

    def on_progress(self, engine, done, total):
        """Stop cleanly once ``count`` ticks of this call are committed."""
        if done == self.count:
            raise Cancelled("stop")


def _same(actual, expected):
    pd.testing.assert_frame_equal(actual.to_frame(), expected.to_frame(), check_exact=True)
    assert actual.errors() == expected.errors() and actual.skip_counts == expected.skip_counts


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_function_returns_what_its_engine_method_returns(backend):
    """The same arguments give the numbers of the engine, on every backend."""
    data = _pairs({("level", 4): -1.0})
    clock = gm.engine.Clock.from_data(data)
    _same(
        gm.simulate(tank(), plan=_rows(), backend=backend),
        gm.Engine(tank(), backend).simulate(_rows()),
    )
    window = dict(end=TICKS[8], clock=clock, only=["first"])
    _same(
        gm.replay(pair_plant(True), data, backend=backend, on_error="record", **window),
        gm.Engine(pair_plant(True), backend, on_error="record").replay(data, **window),
    )


def test_every_run_raises_by_default():
    """The default of the functions and of the engine is ``on_error="raise"``."""
    data = _pairs({("level", 4): -1.0})
    with raises(RunError, "step"):
        gm.replay(pair_plant(), data)
    with raises(RunError, "step"):
        gm.Engine(pair_plant()).replay(data)
    assert gm.replay(pair_plant(), data, on_error="record").errors()


def test_the_error_policy_and_callbacks_reach_the_engine():
    """``on_error`` raises as on the engine and a callback gets the engine as first argument."""
    seen = []

    class Watch(Callback):
        def on_run_end(self, engine):
            seen.append(type(engine))

    gm.replay(pair_plant(), _pairs(), callbacks=[Watch()])
    assert seen == [gm.Engine]
    with raises(RunError, "step"):
        gm.replay(pair_plant(), _pairs({("level", 4): -1.0}), on_error="raise")


def test_a_replay_goes_in_pieces_with_the_end_state():
    """``end_state`` is the ``state=`` of the next call; the pieces give the numbers of one run."""
    data = _pairs()
    whole = gm.replay(pair_plant(True), data)
    first = gm.replay(pair_plant(True), data, end=TICKS[5])
    second = gm.replay(pair_plant(True), data, state=first.end_state)
    assert len(first) + len(second) == len(whole)
    assert second.end_state == whole.end_state
    pd.testing.assert_frame_equal(
        pd.concat([first.to_frame(), second.to_frame()]), whole.to_frame(), check_exact=True
    )


def test_nothing_is_written_without_a_checkpoint(tmp_path, monkeypatch):
    """Without ``checkpoint`` a run leaves no file."""
    monkeypatch.chdir(tmp_path)
    gm.simulate(tank(), plan=_rows())
    gm.replay(pair_plant(), _pairs())
    assert list(tmp_path.iterdir()) == []


def test_checkpoint_every_needs_a_checkpoint():
    """``checkpoint_every`` without a path raises before the run."""
    with pytest.raises(ValidationError, match="checkpoint_every = 100") as caught:
        gm.simulate(tank(), plan=_rows(), checkpoint_every=100)
    assert caught.value.path == "checkpoint_every"
    with pytest.raises(ValidationError, match="checkpoint_every = '1h'"):
        gm.replay(pair_plant(), _pairs(), checkpoint_every="1h")


def test_a_run_that_never_started_writes_nothing(tmp_path):
    """A binding error comes before the first tick, so there is no run to resume."""
    frame = pair_frame().drop(columns="level")
    with raises(gm.errors.ValidationError, "missing_column"):
        gm.replay(pair_plant(), gm.Dataset.from_frame(frame), checkpoint=tmp_path / "run.ckpt")
    assert list(tmp_path.iterdir()) == []


def _run_simulate(**kwargs):
    return gm.simulate(tank(), plan=_rows(), **kwargs)


def _run_replay(**kwargs):
    return gm.replay(pair_plant(True), _pairs(), **kwargs)


@pytest.mark.parametrize("run", [_run_simulate, _run_replay])
def test_a_cancelled_run_resumes_to_the_numbers_of_one_run(run, tmp_path):
    """``checkpoint=`` keeps a cancelled run; ``gm.resume`` continues it to the same results."""
    path = tmp_path / "run.ckpt"
    whole = run()
    with pytest.raises(Cancelled):
        run(checkpoint=path, callbacks=[Stop(3)])
    assert json.loads(path.read_text())["position"] is not None
    resumed = gm.resume(path)
    _same(resumed, whole)
    assert resumed.end_state == whole.end_state


def test_a_failed_run_resumes_from_the_tick_before_it(tmp_path):
    """``on_error="raise"`` is saved: the resumed run fails at the same tick, not earlier."""
    path = tmp_path / "run.ckpt"
    data = _pairs({("level", 4): -1.0})
    with raises(RunError, "step"):
        gm.replay(pair_plant(), data, checkpoint=path, on_error="raise")
    assert json.loads(path.read_text())["position"].startswith(str(TICKS[3].date()))
    with raises(RunError, "step") as caught:
        gm.resume(path)
    assert isinstance(caught.value.__cause__, PhysicsError)


def test_resume_keeps_writing_to_the_same_file_and_the_saved_backend(tmp_path):
    """A resume stopped in turn continues from its own stop, and a finished run is stored."""
    path = tmp_path / "run.ckpt"
    backend = BACKENDS[0]
    whole = _run_replay()
    with pytest.raises(Cancelled):
        _run_replay(checkpoint=path, callbacks=[Stop(3)], backend=backend)
    assert gm.Engine.from_checkpoint(path).backend == backend
    with pytest.raises(Cancelled):
        gm.resume(path, callbacks=[Stop(2)])
    assert len(gm.Engine.from_checkpoint(path).results) == 5
    _same(gm.resume(path), whole)
    stored = gm.resume(path)
    _same(stored, whole)
    assert stored.end_state == whole.end_state


@pytest.mark.parametrize("every", [2, "30min"])
def test_checkpoint_every_writes_during_the_run(every, tmp_path):
    """The file exists before the run ends, with the ``AutoCheckpoint`` cadence."""
    path = tmp_path / "run.ckpt"
    seen = []

    class Watch(Callback):
        def on_step_end(self, engine, sample):
            if path.exists():
                seen.append(json.loads(path.read_text())["position"])

    gm.replay(pair_plant(), _pairs(), checkpoint=path, checkpoint_every=every, callbacks=[Watch()])
    assert len(set(seen)) > 1


def test_function_and_engine_checkpoints_are_one_format(tmp_path):
    """A file of either level is resumed by the other."""
    whole = _run_replay()
    by_function, by_engine = tmp_path / "function.ckpt", tmp_path / "engine.ckpt"
    with pytest.raises(Cancelled):
        _run_replay(checkpoint=by_function, callbacks=[Stop(3)])
    _same(gm.Engine.from_checkpoint(by_function).resume(), whole)

    class SaveAndStop(Stop):
        def on_error(self, engine, error):
            engine.to_checkpoint(by_engine)

    with pytest.raises(Cancelled):
        gm.Engine(pair_plant(True), callbacks=[SaveAndStop(3)]).replay(_pairs())
    _same(gm.resume(by_engine), whole)


def test_a_user_autocheckpoint_stays_available_through_callbacks(tmp_path):
    """``gm.resume`` takes callbacks, so a periodic save can be kept on a resumed run."""
    path = tmp_path / "run.ckpt"
    with pytest.raises(Cancelled):
        _run_replay(checkpoint=path, callbacks=[Stop(3)])
    gm.resume(path, callbacks=[AutoCheckpoint(path, every=2)])
    assert len(gm.Engine.from_checkpoint(path).results) == len(TICKS)


def test_live_starts_on_the_first_call_and_continues_from_the_file(tmp_path):
    """No object is kept between calls: the path carries the run, each tick runs once."""
    path = tmp_path / "live.ckpt"
    data = _pairs()
    first = gm.live(pair_plant(True), data, path, now=TICKS[3])
    assert path.exists() and len(first) == 4
    second = gm.live(pair_plant(True), data, path, now=TICKS[7])
    again = gm.live(pair_plant(True), data, path, now=TICKS[7])
    assert len(second) == 4 and len(again) == 0
    engine = gm.Engine(pair_plant(True))
    engine.live(data, now=TICKS[3])
    pd.testing.assert_frame_equal(
        second.to_frame(), engine.live(data, now=TICKS[7]).to_frame(), check_exact=True
    )


def test_live_needs_a_path():
    """Without a path nothing could carry the run to the next call."""
    with pytest.raises(ValidationError, match="checkpoint = None") as caught:
        gm.live(pair_plant(), _pairs(), None)
    assert caught.value.path == "checkpoint"


def test_resume_refuses_a_live_checkpoint_and_names_live(tmp_path):
    """A live checkpoint holds no rows; only ``gm.live`` continues it."""
    path = tmp_path / "live.ckpt"
    gm.live(pair_plant(), _pairs(), path, now=TICKS[3])
    with raises(RunError, "checkpoint", match="gm.live"):
        gm.resume(path)


def test_two_calls_on_one_plant_trace_once_and_match_two_fresh_plants(shared_plant, fast_dataset):
    """A new numeric value needs no new trace; the numbers are those of two fresh plants."""
    data = fast_dataset.window(end=fast_dataset.start + pd.Timedelta(hours=2))
    plant, other = copy.deepcopy(shared_plant), copy.deepcopy(shared_plant)
    graph_cache().clear()
    traces = graph_cache().traces
    first = gm.simulate(plant, plan=data)
    plant.heat_exchanger.thermal_conductance = 5e6
    second = gm.simulate(plant, plan=data)
    assert graph_cache().traces == traces + 1
    _same(first, gm.simulate(other, plan=data))
    other.heat_exchanger.thermal_conductance = 5e6
    _same(second, gm.simulate(copy.deepcopy(other), plan=data))
    assert (
        first.to_frame()["heat_exchanger.duty"].ne(second.to_frame()["heat_exchanger.duty"]).any()
    )


def test_a_structural_change_retraces():
    """A hook is a guard of the cache, so the next call traces again; no change does not."""
    module = pair_plant()
    gm.replay(module, _pairs())
    traces = graph_cache().traces
    gm.replay(module, _pairs())
    assert graph_cache().traces == traces
    module.first.register_forward_hook(lambda module, inlets, outlets: None)
    gm.replay(module, _pairs())
    assert graph_cache().traces > traces


def test_a_call_without_a_case_or_a_plan_is_refused():
    """A building block has no demand: it needs a plan."""
    with raises(ValidationError, "missing_value") as refused:
        gm.simulate(tank())
    assert refused.value.path == "case"


def test_a_case_schedules_when_there_is_no_plan():
    """The run input is the plan of the case, and a plan given runs the same."""
    from tests.unit.run.test_schedule import FULL, case_of, demand, plant_of_two

    plant = plant_of_two()
    case = case_of(demand(FULL, 0.5 * FULL))
    scheduled = gm.simulate(plant, case)
    given = gm.simulate(plant, case, gm.schedule(plant, case))
    pd.testing.assert_frame_equal(scheduled.to_frame(), given.to_frame())


def test_compile_false_reaches_the_engine(monkeypatch):
    """``compile`` of ``simulate`` is the argument of the engine that runs it."""
    seen = []

    class Recording(gm.Engine):
        def __init__(self, *arguments):
            seen.append(arguments[-1])
            super().__init__(*arguments)

    monkeypatch.setattr(sys.modules["gemini.run.simulate"], "Engine", Recording)
    gm.simulate(tank(), plan=_rows(), compile=False, on_error="record")
    assert seen == [False]


def _no_geotherm():
    """Return a plant whose doublet has a depth and neither value of its geotherm."""
    plant = gm.Plant("Waiting")
    plant.add("Doublet", "d0").set_params("", {"depth": {"value": 2500, "unit": "m"}})
    return plant


@pytest.mark.parametrize("on_error", ["raise", "record"])
def test_a_run_without_the_geotherm_of_a_doublet_names_the_path(on_error):
    """A run that cannot start raises before its first step, whatever ``on_error`` says."""
    index = pd.date_range("2027-01-01", periods=2, freq="h", tz="UTC", name="time")
    with raises(ValidationError, "missing_value", match="d0.gradient") as caught:
        gm.simulate(_no_geotherm(), plan=pd.DataFrame(index=index), on_error=on_error)
    assert caught.value.path == "d0.gradient"
    assert [item["path"] for item in caught.value.problems] == [
        "d0.gradient",
        "d0.surface_temperature",
    ]


def test_a_gradient_alone_leaves_the_surface_temperature_missing():
    """Each value that is still missing is named on its own."""
    plant = _no_geotherm()
    plant.set_params("d0", {"gradient": {"value": 30, "unit": "K/km"}})
    index = pd.date_range("2027-01-01", periods=2, freq="h", tz="UTC", name="time")
    with raises(ValidationError, "missing_value") as caught:
        gm.Engine(plant).simulate(pd.DataFrame(index=index))
    assert caught.value.path == "d0.surface_temperature"


def test_a_checkpoint_of_a_run_with_a_case_keeps_what_the_case_set(tmp_path):
    """The plant dict never holds the case's values, so the checkpoint stores the module state."""
    from tests.unit.run.test_schedule import FULL, case_of, demand, plant_of_two

    path = tmp_path / "run.ckpt"
    gm.simulate(plant_of_two(), case_of(demand(FULL, 0.5 * FULL)), checkpoint=path)
    restored = gm.Engine.from_checkpoint(path).plant
    assert restored.d0.gradient == pytest.approx(0.03)
    assert restored.users.return_temperature == pytest.approx(333.15)
    assert restored.d0.reservoir.fluid.density == 1030.0
