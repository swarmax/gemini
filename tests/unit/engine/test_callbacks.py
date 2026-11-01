"""Event log observation, error reporting and automatic checkpoint intervals."""

import json

import numpy as np
import pandas as pd
import pytest
from pydantic_core import to_jsonable_python

import gemini as gm
from gemini.engine.callbacks import AutoCheckpoint, EventLog
from gemini.modules import Module
from gemini.modules.declarations import Control, Output
from gemini.types import Ports
from gemini.types.bindings import Binding, ModuleBindings


class Gauge(Module):
    """Leaf reporting its control; negative values fail."""

    def __init__(self):
        """Declare one control and one output."""
        super().__init__()

        # Controls
        self.level = Control(float)

        # Outputs
        self.value = Output(float)

    def forward(self, inlets):
        """Expose no fluid outlets."""

        outlets = dict()
        if self.level < 0:
            raise ValueError("negative level")
        self.value = self.level
        return outlets


def run(levels, *callbacks):
    """Replay a gauge over 15-minute rows with the given levels."""
    plant = Gauge()
    plant.bindings = {"": ModuleBindings(controls={"level": Binding(column="level", unit="-")})}
    index = pd.date_range("2024-01-01", periods=len(levels), freq="15min", tz="UTC")
    data = gm.Dataset.from_frame(pd.DataFrame({"level": levels}, index=index))
    return plant, gm.Engine(plant, callbacks=list(callbacks), on_error="record").replay(data)


def test_event_log_records_calls_in_order_without_hooks():
    """Run, forward and step events are logged in order; the plant never gets a hook."""
    events = EventLog()
    plant, _ = run([1.0, 2.0], events)
    kinds = [event["kind"] for event in events.events]
    assert kinds == ["run_start", "forward", "step_end", "forward", "step_end", "run_end"]
    forward = events.events[1]
    assert forward["inputs"] == {"level": 1.0} and forward["outputs"] == {"value": 1.0}
    assert not plant._hooks and not plant._pre_hooks


def test_event_log_serialises_a_stream_inlet_as_before():
    """A stream is logged with ``m_dot``, ``T``, ``p`` and its fluid, in that order."""
    stream = gm.Stream(
        m_dot=gm.units.Quantity(2, "kg/s"),
        T=gm.units.Quantity(300, "K"),
        p=gm.units.Quantity(1e5, "Pa"),
        fluid=gm.WATER,
    )
    logged = to_jsonable_python(dict(Ports({"fluid_in": stream})), fallback=str)
    assert list(logged["fluid_in"]) == ["m_dot", "T", "p", "fluid"]
    assert logged["fluid_in"] == {
        "m_dot": 2.0,
        "T": 300.0,
        "p": 100000.0,
        "fluid": gm.WATER.model_dump(mode="json"),
    }


def test_event_log_reports_recorded_errors_with_their_code(tmp_path):
    """A recorded module failure is logged before its step end with its row code."""
    events = EventLog(tmp_path / "events.jsonl")
    run([1.0, -1.0], events)
    lines = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    error = next(line for line in lines if line["kind"] == "error")
    assert error["module"] == "" and error["code"] == "module_error"
    assert error["message"] == "negative level"
    assert [line["kind"] for line in lines][-3:] == ["error", "step_end", "run_end"]


def test_event_log_serialises_unknown_values_as_text():
    """Logging never raises: unknown objects become strings and NaN stays a float."""
    events = EventLog()
    event = events.log("custom", value=object(), number=float("nan"))
    assert np.isnan(event["number"])
    assert events.events == [event]


def test_auto_checkpoint_intervals(tmp_path):
    """Integers of any type count steps, other values are durations; nonpositive counts fail."""
    assert AutoCheckpoint(tmp_path / "a", every=np.int64(2)).every == 2
    assert AutoCheckpoint(tmp_path / "a", every="1h").every == pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="every = 0"):
        AutoCheckpoint(tmp_path / "a", every=0)
    path = tmp_path / "auto.ckpt"
    run([1.0, 2.0, 3.0], AutoCheckpoint(path, every=np.int64(2)))
    assert len(gm.Engine.from_checkpoint(path).results) == 2
