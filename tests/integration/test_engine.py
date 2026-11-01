"""Engine parity, state, callbacks, energy and restart guarantees."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from gemini import runtime
from gemini.engine import checkpoint
from gemini.engine.callbacks import AutoCheckpoint, Callback, EventLog
from gemini.modules.declarations import Control, Output
from gemini.ops import kernels
from gemini.run.results import Results
from gemini.types.bindings import Binding, DatedParams, ModuleBindings
from tests.fixtures.errors import raises
from tests.fixtures.frames import on_ports, path_frame
from tests.fixtures.old_names import RENAMED_NAMES

ROOT = Path(__file__).parents[2]
REFERENCE = ROOT / "tests/fixtures/engine_reference"


class Accumulator(gm.modules.Module):
    """Simple importable test integrator with a JSON state."""

    stateful = True

    def __init__(self):
        """Declare the accumulator's test state and ports."""
        super().__init__()

        # Controls
        self.rate = Control(float)

        # Outputs
        self.value = Output(float)

    def initial_state(self):
        """Start at zero."""
        return {"value": 0.0}

    def forward(self, inlets):
        """Expose a stateless rate observation."""

        outlets = dict()
        self.value = self.rate
        return outlets

    def step(self, state, dt, inlets):
        """Integrate with explicit state."""

        # Outputs
        state = {"value": state["value"] + self.rate * dt}
        result = self(inlets, rate=state["value"])

        return state, result


def _reference(name, actual):
    """Read a pickled pre-refactor frame at the column dtypes and time unit of ``actual``.

    The pickles hold nanosecond times and object text columns; pandas 3 builds results with
    microsecond times and its ``str`` text dtype. Values are compared unchanged.
    """
    old = pd.read_pickle(REFERENCE / name)
    old = old.rename(columns={"filter_hot": "filters.hot", "filter_return": "filters.cold"})
    old = on_ports(old.rename(columns=RENAMED_NAMES))
    for column in old:
        old[column] = old[column].astype(actual[column].dtype)
    if isinstance(old.index, pd.DatetimeIndex):
        old.index = old.index.as_unit(actual.index.unit)
    return old


@pytest.fixture
def setup(fresh_plant, reference_dataset):
    """Create a fresh plant and first-day measurements."""
    return fresh_plant, reference_dataset


def test_reference_replay_and_simulate(setup):
    """Preserve every pre-refactor output, including health fields and scenario diagnostics.

    NOTE(refactor): pandas' ordinary decimal parser changes a few chained scenario values at
    ~1e-15 relative to the old raw-unit CSV conversion path, hence the simulate tolerance.
    """
    plant, data = setup
    actual = path_frame(gm.Engine(plant, on_error="raise").replay(data))
    old = _reference("replay.pkl", actual)
    pd.testing.assert_frame_equal(actual[old.columns], old, check_names=False)
    clock = gm.engine.Clock.days(2024, 6, 7)
    raw = data.read(data.start, data.start)
    assumed = pd.DataFrame([raw.iloc[0].to_dict()] * 24, index=list(clock))
    result = gm.Engine(plant, on_error="raise").simulate(gm.Dataset.from_frame(assumed), clock)
    actual = path_frame(result)
    old = _reference("simulate.pkl", actual)
    pd.testing.assert_frame_equal(
        actual[old.columns].reset_index(drop=True),
        old.reset_index(drop=True),
        check_exact=False,
        rtol=1e-14,
        atol=0,
    )
    assert len(result) == 24
    for path, field in result._energy:
        total = (actual[path, field] * 3600).sum()
        assert result.to_frame(table="energy").loc[(path, field), "energy_J"] == pytest.approx(
            total
        )


def test_replay_can_skip_outputs(setup):
    """A no-output replay retains fluid execution without running diagnostics on empty values."""
    plant, data = setup
    first = data.window(end=data.start)
    with gm.modules.no_outputs():
        result = gm.Engine(plant, on_error="raise").replay(first)
    assert len(result) == 1
    fields = set(path_frame(result).columns.get_level_values("field"))
    assert "operating" in fields
    assert "power" not in fields


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_replay_of_example_data_skips_nothing_at_any_timestamp_resolution(
    fresh_plant, fast_frame, unit
):
    """Every twin runs on every tick of one example day, whatever the parsed time resolution.

    pandas 3 parses the example CSV times as microseconds; comparing them with nanosecond
    ``Timestamp.value`` once made every tick a gap, so replay silently skipped every twin.
    """
    frame = fast_frame.iloc[:96].copy()
    frame["time"] = frame["time"].dt.as_unit(unit)
    data = gm.Dataset.from_frame(frame, time_column="time")
    result = gm.Engine(fresh_plant, on_error="raise").replay(data)
    assert len(result) == 96
    assert result.skip_counts == {}
    assert result["doublet.esp"].head.notna().all()


class Interrupted(BaseException):
    """Model a scheduler cancellation without ordinary-error recovery."""


class StopAndSave(Callback):
    """Interrupt after a committed step and save from the error hook."""

    def __init__(self, path, count):
        """Remember the checkpoint destination and stop position."""
        self.path, self.count = path, count

    def on_step_end(self, engine, sample):
        """Cancel only once the requested result row exists."""
        if len(engine.results) == self.count:
            raise Interrupted("stop")

    def on_error(self, engine, error):
        """Save the completed boundary after cancellation."""
        engine.to_checkpoint(self.path)


@pytest.mark.parametrize("kind", ["replay", "simulate"])
def test_interrupt_resume(setup, tmp_path, kind):
    """Fresh-engine resume reproduces uninterrupted results and integration exactly."""
    plant, data = setup
    data = data.window(end=data.start + pd.Timedelta(hours=2, minutes=45))
    clock = gm.engine.Clock.from_data(data)
    args = [data] + ([clock] if kind == "simulate" else [])
    expected = getattr(gm.Engine(plant, on_error="raise"), kind)(*args)
    path = tmp_path / "run.ckpt"
    engine = gm.Engine(plant, callbacks=[StopAndSave(path, 5)], on_error="raise")
    with pytest.raises(Interrupted):
        getattr(engine, kind)(*args)
    checkpoint = json.loads(path.read_text())
    assert checkpoint["position"] == list(clock)[4].isoformat().replace("+00:00", "Z")
    loaded = gm.Engine.from_checkpoint(path)
    assert loaded.plant.state_dict() == plant.state_dict()
    actual = loaded.resume()
    pd.testing.assert_frame_equal(actual.to_frame(), expected.to_frame(), check_exact=True)
    pd.testing.assert_frame_equal(
        actual.to_frame(table="energy"), expected.to_frame(table="energy"), check_exact=True
    )
    assert loaded.resume() is actual


def test_live_idempotency(tmp_path):
    """New engine calls process only newly available timestamps; repeated now returns no rows."""
    plant = Accumulator()
    plant.bindings = {"": ModuleBindings(controls={"rate": Binding(column="rate", unit="-")})}
    frame = pd.DataFrame(
        {"rate": [1.0, 1.0]},
        index=pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC"),
    )
    data = gm.Dataset.from_frame(frame)
    path = tmp_path / "live.ckpt"
    first_now = data.start
    second_now = data.start + pd.Timedelta(minutes=15)
    out = gm.Engine(plant).live(data, path, now=first_now)
    assert len(out) == 1
    second = gm.Engine(plant).live(data, path, now=second_now)
    assert len(second) == 1
    assert not set(out.to_frame().index) & set(second.to_frame().index)
    engine = gm.Engine(plant)
    assert len(engine.live(data, path, now=second_now)) == 0
    assert len(engine.results) == 2
    assert len(gm.Engine.from_checkpoint(path).resume()) == 2


def test_missing_data_dates_events_and_export(setup, tmp_path):
    """Missing observations skip only their twin; dated snapshots and event hooks remain active."""
    plant, data = setup
    frame = data.read(data.start, data.end).iloc[:12]
    frame.loc[frame.index[0], "doublet.esp.suction.p"] = np.nan
    module = plant.filters.hot
    module._param_history.append(
        DatedParams(
            valid_from=frame.index[1],
            params=module._params_at(None) | {"nominal_pressure_drop": 3200},
        )
    )
    events = EventLog(tmp_path / "events.jsonl")
    result = gm.Engine(plant, callbacks=[events], on_error="raise").replay(
        gm.Dataset.from_frame(frame)
    )
    assert result["doublet.esp"].head.notna().sum() == 11
    assert (
        result["filters.hot"].pressure_drop.iloc[1]
        > 1.99 * result["filters.hot"].pressure_drop.iloc[0]
    )
    assert result.skip_counts == {"doublet.esp": {"doublet.esp.suction.p": 1}}
    assert not any(m._hooks for m in plant.modules())
    assert (
        json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])["kind"] == "run_start"
    )
    path = result.to_npz(tmp_path / "results.npz")
    loaded = Results.from_npz(path)
    pd.testing.assert_frame_equal(loaded.to_frame(), result.to_frame())
    pd.testing.assert_frame_equal(loaded.to_frame(table="energy"), result.to_frame(table="energy"))
    assert loaded.errors() == result.errors()
    assert [row["code"] for row in result.errors()] == ["missing_value"]
    assert result.errors()[0]["path"] == "doublet.esp"


def test_autocheckpoint_and_callback_order(setup, tmp_path):
    """Callbacks observe committed positions; automatic snapshots resume only unfinished rows."""
    plant, data = setup
    calls = []

    class Observe(Callback):
        """Record lifecycle events."""

        def on_run_start(self, engine):
            """Observe run start."""
            calls.append("start")

        def on_step_start(self, engine, sample):
            """Observe step start."""
            calls.append("before")

        def on_step_end(self, engine, sample):
            """Observe committed position."""
            assert engine.position == sample.t
            calls.append("after")

        def on_run_end(self, engine):
            """Observe run end."""
            calls.append("end")

    path = tmp_path / "automatic.ckpt"
    engine = gm.Engine(plant, callbacks=[Observe(), AutoCheckpoint(path, every="1h")])
    actual = engine.replay(data.window(end="2024-06-07T01:00:00Z"))
    assert calls == ["start"] + ["before", "after"] * 5 + ["end"]
    loaded = gm.Engine.from_checkpoint(path)
    assert len(loaded.results) == 4
    pd.testing.assert_frame_equal(loaded.resume().to_frame(), actual.to_frame())


def test_error_policies_and_missing_columns(setup):
    """Invalid physics records module-specific errors or raises; absent columns fail together."""
    plant, data = setup
    frame = data.read(data.start, data.end).iloc[:2]
    frame.loc[frame.index[0], "doublet.esp.suction.p"] = -100
    result = gm.Engine(plant, on_error="record").replay(gm.Dataset.from_frame(frame))
    assert result.errors()[0]["path"] == "doublet.esp"
    assert result.errors()[0]["code"] == "invalid_inlet"
    assert result["filters.hot"].pressure_drop.notna().all()
    with raises(gm.errors.RunError, "step", match="doublet.esp"):
        gm.Engine(plant, on_error="raise").replay(gm.Dataset.from_frame(frame))
    with raises(
        gm.errors.ValidationError,
        "missing_column",
        match="suction.p, doublet.reservoir.production_rate",
    ) as caught:
        gm.Engine(plant).replay(
            gm.Dataset.from_frame(
                frame.drop(columns=["doublet.esp.suction.p", "doublet.reservoir.production_rate"])
            )
        )
    assert caught.value.code == "missing_column"


def test_plant_only_checkpoint(setup, tmp_path):
    """A configured engine can save before its first run, including fitted design overrides."""
    plant, _ = setup
    plant.heat_exchanger.set_params("", {"thermal_conductance": gm.units.Quantity(123456, "W/K")})
    engine = gm.Engine(plant)
    path = tmp_path / "design.ckpt"
    engine.to_checkpoint(path)
    other = gm.Engine.from_checkpoint(path)
    assert other.plant.state_dict() == plant.state_dict()
    assert other.plant.bindings == plant.bindings
    assert len(other.resume()) == 0


def test_stateful_measured_and_integrated(tmp_path):
    """Measured state resets each tick; unbound state integrates and survives checkpoints."""
    plant = Accumulator()
    plant.bindings = {"": ModuleBindings(controls={"rate": Binding(column="rate", unit="-")})}
    frame = pd.DataFrame(
        {"rate": [1, 1, 1], "observed": [10, 20, 30]},
        index=pd.date_range("2024-01-01", periods=3, freq="1s", tz="UTC"),
    )
    data = gm.Dataset.from_frame(frame)
    engine = gm.Engine(plant, on_error="raise")
    assert engine.replay(data)[""].value.tolist() == [1, 2, 3]
    path = tmp_path / "state.ckpt"
    with pytest.raises(Interrupted):
        gm.Engine(plant, callbacks=[StopAndSave(path, 1)]).replay(data)
    assert gm.Engine.from_checkpoint(path).resume()[""].value.tolist() == [1, 2, 3]
    plant.bindings[""].state = {"value": Binding(column="observed", unit="-")}
    assert engine.replay(data)[""].value.tolist() == [11, 21, 31]
    assert engine.module_states[""] == {"value": 30}


def test_empty_live_and_checkpoint_results_file(setup, tmp_path):
    """An empty live window is resumable and the results file is an .npz with exact cells."""
    plant, data = setup
    path = tmp_path / "empty.ckpt"
    assert len(gm.Engine(plant).live(data, path, now="2024-01-01")) == 0
    assert len(gm.Engine.from_checkpoint(path).resume()) == 0
    engine = gm.Engine(plant)
    expected = engine.replay(data.window(end=data.start))
    path = tmp_path / "fallback.ckpt"
    engine.to_checkpoint(path)
    assert json.loads(path.read_text())["results_file"].endswith(".npz")
    pd.testing.assert_frame_equal(
        gm.Engine.from_checkpoint(path).resume().to_frame(), expected.to_frame()
    )


def test_failed_checkpoint_publication_keeps_previous(setup, tmp_path, monkeypatch):
    """Failure before the manifest rename leaves a fully readable previous generation."""
    plant, data = setup
    engine = gm.Engine(plant)
    engine.replay(data.window(end=data.start))
    path = tmp_path / "atomic.ckpt"
    engine.to_checkpoint(path)
    previous = path.read_bytes()

    def fail(source, destination):
        """Model a filesystem failure during atomic publication."""
        raise OSError("simulated rename failure")

    monkeypatch.setattr(checkpoint.os, "replace", fail)
    engine.replay(data)
    with pytest.raises(OSError, match="rename"):
        engine.to_checkpoint(path)
    assert path.read_bytes() == previous
    assert len(gm.Engine.from_checkpoint(path).resume()) == 1


def accumulator(frame):
    """Return an accumulator bound to a ``rate`` column and the matching dataset."""
    plant = Accumulator()
    plant.bindings = {"": ModuleBindings(controls={"rate": Binding(column="rate", unit="-")})}
    return plant, gm.Dataset.from_frame(frame)


@pytest.mark.parametrize("count", [10, 13])
def test_resume_keeps_held_rows_when_the_clock_is_finer_than_the_data(tmp_path, count):
    """Bug E-engine-001: resume lost the held row, or refused to resume after the last row."""
    index = pd.date_range("2024-01-01", periods=4, freq="1h", tz="UTC")
    plant, data = accumulator(pd.DataFrame({"rate": [1.0, 2.0, 3.0, 4.0]}, index=index))
    clock = gm.engine.Clock.range("2024-01-01T00:00Z", "2024-01-01T04:00Z", "15min")
    expected = gm.Engine(plant, on_error="raise").simulate(data, clock)
    path = tmp_path / "run.ckpt"
    with pytest.raises(Interrupted):
        gm.Engine(plant, callbacks=[StopAndSave(path, count)], on_error="raise").simulate(
            data, clock
        )
    actual = gm.Engine.from_checkpoint(path).resume()
    pd.testing.assert_frame_equal(actual.to_frame(), expected.to_frame(), check_exact=True)


def test_live_step_grid_stays_anchored_between_calls(tmp_path):
    """Bug E-engine-006: a later call with off-grid rows kept the first call's 15-minute grid."""
    path = tmp_path / "live.ckpt"
    first = pd.DataFrame(
        {"rate": [1.0, 1.0]},
        index=pd.DatetimeIndex(["2024-01-01 00:00", "2024-01-01 00:15"], tz="UTC"),
    )
    plant, data = accumulator(first)
    gm.Engine(plant).live(data, path, step="15min", now="2024-01-01T00:15Z")
    second = pd.DataFrame(
        {"rate": [2.0, 2.0]},
        index=pd.DatetimeIndex(["2024-01-01 00:22", "2024-01-01 00:37"], tz="UTC"),
    )
    fresh = gm.Engine(plant).live(
        gm.Dataset.from_frame(second), path, step="15min", now="2024-01-01T01:00Z"
    )
    assert [t.strftime("%H:%M") for t in fresh.to_frame().index] == ["00:30"]


def test_live_single_row_call_reuses_the_checkpointed_step(tmp_path):
    """Bug E-engine-007: one new row per live call was integrated over one hour, not 15 minutes."""
    path = tmp_path / "live.ckpt"
    index = pd.date_range("2024-01-01", periods=3, freq="15min", tz="UTC")
    plant, data = accumulator(pd.DataFrame({"rate": [1.0, 1.0, 1.0]}, index=index))
    gm.Engine(plant).live(data.window(end=index[1]), path, now=index[1])
    fresh = gm.Engine(plant).live(data.window(start=index[2]), path, now=index[2])
    assert fresh[""].value.tolist() == [2700.0]


def test_live_keeps_the_callers_error_policy_and_plant(tmp_path):
    """Bug E-engine-008: restoring a live checkpoint replaced on_error and the supplied plant."""
    path = tmp_path / "live.ckpt"
    index = pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC")
    plant, data = accumulator(pd.DataFrame({"rate": [1.0, 1.0]}, index=index))
    gm.Engine(plant).live(data, path, now=index[0])
    engine = gm.Engine(plant, on_error="raise")
    engine.live(data, path, now=index[1])
    assert engine.on_error == "raise"
    assert engine.plant is plant
    with raises(gm.errors.RunError, "checkpoint", match="plant_class = .*Accumulator"):
        gm.Engine(NotANumber()).live(data, path, now=index[1])


class NotANumber(gm.modules.Module):
    """Leaf whose output is always NaN."""

    def __init__(self):
        """Declare one control and one output."""
        super().__init__()

        # Controls
        self.rate = Control(float)

        # Outputs
        self.value = Output(float)

    def forward(self, inlets):
        """Expose no fluid outlets."""

        outlets = dict()
        self.value = float("nan")
        return outlets


class Boom(Callback):
    """Fail after the first committed step."""

    def on_step_end(self, engine, sample):
        """Raise an ordinary error from a callback."""
        raise ValueError("boom")


def test_event_log_never_changes_results_and_always_detaches(tmp_path):
    """Bugs E-engine-004/005: NaN outputs became errors; an aborted run left hooks attached."""
    plant = NotANumber()
    plant.bindings = {"": ModuleBindings(controls={"rate": Binding(column="rate", unit="-")})}
    index = pd.date_range("2024-01-01", periods=2, freq="15min", tz="UTC")
    data = gm.Dataset.from_frame(pd.DataFrame({"rate": [1.0, 1.0]}, index=index))
    for events in (EventLog(), EventLog(tmp_path / "events.jsonl")):
        result = gm.Engine(plant, callbacks=[events]).replay(data)
        assert result.errors() == []
        assert result[""].value.isna().all()
    assert "NaN" in (tmp_path / "events.jsonl").read_text()
    with pytest.raises(ValueError, match="boom"):
        gm.Engine(plant, callbacks=[EventLog(), Boom()]).replay(data)
    assert not plant._hooks and not plant._pre_hooks


def accumulated(rows=6):
    """Return an accumulator with a constant rate and that many 15-minute rows."""
    index = pd.date_range("2024-01-01", periods=rows, freq="15min", tz="UTC")
    return accumulator(pd.DataFrame({"rate": [1.0] * rows}, index=index))


def test_a_dataframe_runs_like_a_dataset():
    """A DataFrame with a timezone-aware index is the run input of simulate and replay."""
    plant, data = accumulated()
    frame = data.to_frame()
    replayed = gm.Engine(plant).replay(frame)
    pd.testing.assert_frame_equal(replayed.to_frame(), gm.Engine(plant).replay(data).to_frame())
    simulated = gm.Engine(plant).simulate(frame)
    assert simulated[""].value.tolist() == replayed[""].value.tolist()
    with raises(gm.errors.RunError, "invalid_data", match="timezone-aware"):
        gm.Engine(plant).replay(frame.tz_localize(None))


def test_a_run_input_without_the_bound_columns_lists_them_all():
    """The error names every missing column, carries a close match and the code missing_column."""
    plant, data = accumulated()
    plant.bindings[""].controls["speed"] = Binding(column="speed", unit="-")
    plant.bindings[""].controls["rat"] = Binding(column="rat", unit="-")
    with pytest.raises(gm.errors.ValidationError, match="rat, speed") as caught:
        gm.Engine(plant).replay(data)
    assert isinstance(caught.value, gm.errors.ValidationError)
    assert caught.value.code == "missing_column"
    assert caught.value.to_dict()["suggestions"] == ["rate"]


def test_nan_rows_are_row_errors_and_the_run_continues():
    """A NaN in a bound column skips that tick with the code missing_value; later ticks run."""
    plant, data = accumulated(4)
    frame = data.to_frame()
    frame.loc[frame.index[1], "rate"] = np.nan
    results = gm.Engine(plant).replay(frame)
    assert len(results) == 4 and results[""].value.isna().tolist() == [False, True, False, False]
    (row,) = results.errors()
    assert row["code"] == "missing_value" and row["path"] == ""
    assert row["time"] == "2024-01-01T00:15:00+00:00"
    assert row["code"] in gm.errors.ROW_CODES


def test_two_consecutive_replays_give_the_numbers_of_one(tmp_path):
    """Starting a replay from a former end_state continues the integration exactly."""
    plant, data = accumulated(8)
    whole = gm.Engine(plant).replay(data)
    first = gm.Engine(plant).replay(data, end=data.start + pd.Timedelta(minutes=45))
    assert len(first) == 4 and first.end_state["position"] == "2024-01-01T00:45:00+00:00"
    state = Results.from_bytes(first.to_bytes()).end_state
    second = gm.Engine(accumulator(data.to_frame())[0]).replay(data, state=state)
    assert len(second) == 4
    both = pd.concat([first.to_frame(), second.to_frame()])
    pd.testing.assert_frame_equal(both, whole.to_frame(), check_exact=True)
    assert second.end_state == whole.end_state
    json.dumps(whole.end_state, allow_nan=False)
    path = first.to_npz(tmp_path / "first")
    windowed = gm.Engine(plant).replay(
        data, start=data.start + pd.Timedelta(minutes=60), state=Results.from_npz(path).end_state
    )
    pd.testing.assert_frame_equal(windowed.to_frame(), second.to_frame(), check_exact=True)


def test_a_state_of_another_plant_or_shape_is_refused():
    """end_state needs its two keys and module paths of this plant."""
    plant, data = accumulated()
    with pytest.raises(gm.errors.ValidationError, match="end_state of a former run"):
        gm.Engine(plant).replay(data, state={"position": None})
    state = {"position": None, "module_states": {"doublet.esp": {"value": 1.0}}}
    with pytest.raises(gm.errors.ValidationError, match="doublet.esp") as caught:
        gm.Engine(plant).replay(data, state=state)
    assert caught.value.code == "unknown_name"


class Progress(Callback):
    """Record the progress of a run and cancel it at a given number of ticks."""

    def __init__(self, cancel_at=None):
        """Remember when to cancel, if ever."""
        self.cancel_at = cancel_at
        self.seen = []

    def on_progress(self, engine, done, total):
        """Record the counts."""
        self.seen.append((done, total))

    def on_step_end(self, engine, sample):
        """Cancel once the requested number of ticks is committed."""
        if len(engine.results) == self.cancel_at:
            raise gm.errors.Cancelled(f"stopped after {self.cancel_at} ticks")


def test_progress_counts_the_ticks_of_the_run():
    """on_progress gets (done, total) after each committed tick."""
    plant, data = accumulated(5)
    progress = Progress()
    gm.Engine(plant, callbacks=[progress]).replay(data)
    assert progress.seen == [(done, 5) for done in range(1, 6)]


def test_cancelling_keeps_the_committed_ticks_readable():
    """A callback that raises Cancelled stops the run cleanly; its ticks and end state stay."""
    plant, data = accumulated()
    progress = Progress(cancel_at=3)
    engine = gm.Engine(plant, callbacks=[progress])
    with pytest.raises(gm.errors.Cancelled, match="stopped after 3 ticks") as caught:
        engine.replay(data)
    assert caught.value.code == "cancelled"
    assert len(engine.results) == 3 and progress.seen[-1] == (2, 6)
    assert engine.results[""].value.tolist() == [900.0, 1800.0, 2700.0]
    assert engine.results.end_state["position"] == "2024-01-01T00:30:00+00:00"
    rest = gm.Engine(plant).replay(data, state=engine.results.end_state)
    assert rest[""].value.tolist() == [3600.0, 4500.0, 5400.0]


def test_live_continues_in_memory_without_a_checkpoint():
    """Two live calls on one engine process each tick once, with no file written."""
    plant, data = accumulated()
    engine = gm.Engine(plant)
    first = engine.live(data.window(end=data.start + pd.Timedelta(minutes=30)), now=data.end)
    second = engine.live(data, now=data.end)
    assert len(first) == 3 and len(second) == 3 and len(engine.results) == 6
    whole = gm.Engine(plant).live(data, now=data.end)
    assert second[""].value.tolist() == whole[""].value.tolist()[3:]


def test_the_engine_applies_its_own_backend_to_the_run():
    """The backend named in the constructor is the one in force while the run executes."""
    seen = []

    class Watch(Callback):
        def on_step_start(self, engine, sample):
            seen.append(kernels.forced_name())

    plant, data = accumulated(2)
    for backend in ("python", "numpy"):
        with runtime.settings(backend="numpy" if backend == "python" else "python"):
            gm.Engine(plant, backend, [Watch()]).replay(data)
    assert seen == ["python", "python", "numpy", "numpy"]
