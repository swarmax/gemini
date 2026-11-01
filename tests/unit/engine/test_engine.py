"""Engine argument checks, checkpoint state errors, windows and saved runtime settings."""

import pandas as pd
import pytest

import gemini as gm
from gemini import runtime
from gemini.modules import Module
from gemini.modules.declarations import Control, Output
from gemini.types.bindings import Binding, ModuleBindings
from tests.fixtures.errors import raises


class Precision(Module):
    """Leaf reporting whether the run uses float32 arithmetic."""

    def __init__(self):
        """Declare one control and one output."""
        super().__init__()

        # Controls
        self.level = Control(float)

        # Outputs
        self.float32 = Output(float)

    def forward(self, inlets):
        """Expose no fluid outlets."""

        outlets = dict()
        self.float32 = float(runtime.get_precision() == "float32")
        return outlets


@pytest.fixture
def setup():
    """Return a bound leaf plant and four 15-minute rows."""
    plant = Precision()
    plant.bindings = {"": ModuleBindings(controls={"level": Binding(column="level", unit="-")})}
    index = pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC")
    return plant, gm.Dataset.from_frame(pd.DataFrame({"level": [1.0] * 4}, index=index))


def test_arguments_and_checkpoint_states_are_validated(setup, tmp_path):
    """Bad policies, a missing plant and unresumable checkpoints fail explicitly."""
    plant, data = setup
    with pytest.raises(ValueError, match="on_error = 'ignore'"):
        gm.Engine(plant, on_error="ignore")
    with raises(gm.errors.ValidationError, "invalid_value", match="plant = NoneType"):
        gm.Engine(None)
    with raises(gm.errors.ValidationError, "unknown_name", match="did you mean 'numpy'"):
        gm.Engine(plant, backend="nunpy")
    engine = gm.Engine(plant)
    engine.replay(data)
    engine.to_checkpoint(tmp_path / "replay.ckpt")
    with raises(gm.errors.RunError, "checkpoint", match="run_kind = 'replay'; expected 'live'"):
        gm.Engine(plant).live(data, tmp_path / "replay.ckpt")
    loaded = gm.Engine.from_checkpoint(tmp_path / "replay.ckpt")
    loaded.position = None
    with raises(gm.errors.RunError, "checkpoint", match="no stored rows"):
        loaded.resume()
    loaded.clock = None
    with raises(gm.errors.RunError, "checkpoint", match="clock = None"):
        loaded.resume()


def test_replay_windows_data_and_an_explicit_clock(setup):
    """Start and end bound both the rows and an explicit clock inclusively."""
    plant, data = setup
    clock = gm.engine.Clock.from_data(data)
    result = gm.Engine(plant).replay(data, clock=clock, start=data.start, end=clock.ticks[1])
    assert len(result) == 2


def test_resume_and_live_apply_the_saved_runtime_settings(setup, tmp_path):
    """Precision and display units saved with a run apply again when it continues."""
    plant, data = setup
    path = tmp_path / "live.ckpt"
    with runtime.settings(precision="float32"):
        gm.Engine(plant).live(data.window(end=data.start), path, now=data.start)
    fresh = gm.Engine(plant).live(data, path, now=data.end)
    assert fresh[""].float32.tolist() == [1.0, 1.0, 1.0]
    assert runtime.get_precision() == "float64"


def test_a_checkpoint_keeps_the_eager_choice_of_the_run(setup, tmp_path):
    """An engine built with ``compile=False`` is restored with the eager executor."""
    from gemini.engine.eager import EagerExecutor

    plant, data = setup
    path = tmp_path / "eager.ckpt"
    gm.Engine(plant, compile=False).live(data.window(end=data.start), path, now=data.start)
    assert isinstance(gm.Engine.from_checkpoint(path)._executor, EagerExecutor)
