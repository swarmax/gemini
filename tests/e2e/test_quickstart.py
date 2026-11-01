"""The public quickstart acceptance path, one test per step."""

import pandas as pd
import pytest

import gemini as gm
from tests.fixtures.doublet_day import doublet_day

pytestmark = pytest.mark.e2e


@pytest.fixture
def plant():
    """Return the shared example plant, new for each test."""
    return gm.plants.example("DoubletHeatPlant")


@pytest.fixture
def df(dataset_path):
    """Return the committed dataset as a frame."""
    return pd.read_csv(dataset_path, parse_dates=["time"])


@pytest.fixture
def data(df):
    """Return the committed dataset as a ``Dataset``."""
    return gm.Dataset.from_frame(df, time_column="time")


def test_replay_and_resume(tmp_path, plant, df, data):
    """Replay writes a checkpoint and resume reads it back to the same length."""
    print(plant)
    res = gm.replay(plant, data, checkpoint=str(tmp_path / "replay.ckpt"))
    print(res.to_frame(table="energy"))
    assert len(res["doublet.esp"].power) == len(df)
    assert len(gm.resume(str(tmp_path / "replay.ckpt"))) == len(res) == len(df)


def test_calibrate_and_save_the_plant(tmp_path, plant, data):
    """A calibrated plant saves to JSON and loads back with the same state."""
    fit = gm.analysis.calibrate(
        plant, data, params=[plant.get("heat_exchanger.thermal_conductance")]
    )
    print(fit)
    plant.to_json(tmp_path / "my_plant.json")
    assert gm.Plant.from_json(tmp_path / "my_plant.json").state_dict() == plant.state_dict()


def test_simulate_profiles(plant):
    """A day of constant profiles simulates 24 hourly ticks."""
    clock, plan = doublet_day()
    sim = gm.simulate(plant, plan=plan, clock=clock)
    print(sim.to_frame(table="energy"))
    assert len(sim) == 24


def test_live_in_two_days(tmp_path, plant, df):
    """Live runs day one, then day two from the same checkpoint."""
    start = df["time"].iloc[0]
    second = start + pd.Timedelta(days=1)
    third = start + pd.Timedelta(days=2)
    day1 = df[df["time"] < second]
    day2 = df[(df["time"] >= second) & (df["time"] < third)]
    checkpoint = str(tmp_path / "live.ckpt")
    out1 = gm.live(plant, gm.Dataset.from_frame(day1, time_column="time"), checkpoint, now=second)
    out2 = gm.live(plant, gm.Dataset.from_frame(day2, time_column="time"), checkpoint, now=third)
    assert len(out1) == len(day1) and len(out2) == len(day2)
