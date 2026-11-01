"""Profile time semantics, physical-unit conversion and aggregation."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import gemini as gm
from gemini.errors import RunError, ValidationError
from gemini.types.profile import Profile
from tests.fixtures.errors import raises


def test_series_previous_and_resample():
    """Convert raw temperatures, hold prior samples and aggregate without filling gaps."""
    source = pd.Series(
        [10, 20],
        name="ambient",
        index=pd.to_datetime(["2024-01-01 00:00", "2024-01-01 01:00"]),
    )
    profile = Profile.from_series(source, "degC", tz="Europe/Oslo")
    assert profile.unit == "K" and profile.quantity == "temperature"
    assert profile.values == [283.15, 293.15]
    assert profile.index[0].hour == 23
    assert profile.at(profile.index[0] + timedelta(minutes=30)) == 283.15
    assert profile.at(profile.index[-1] + timedelta(days=1)) == 293.15
    with raises(RunError, "invalid_data", match="first sample"):
        profile.at(profile.index[0] - timedelta(seconds=1))
    series = profile.to_series()
    series.iloc[0] = 0
    assert profile.values[0] == 283.15
    clock = gm.engine.Clock.range("2024-01-01 00:00", "2024-01-01 03:00", "1h")
    constant = Profile.constant(10, unit="W", clock=clock)
    assert len(constant.resample(timedelta(hours=2), "mean")) == 2
    assert constant.resample(timedelta(hours=2), "sum").values == [20, 20]
    assert constant.resample(timedelta(hours=2), "first").values == [10, 10]
    for index, values in (
        (profile.index[::-1], profile.values),
        ([profile.index[0]] * 2, [1, 2]),
        (profile.index, [1]),
    ):
        with pytest.raises(ValueError):
            Profile(name="bad", quantity="power", unit="W", index=index, values=values)


def test_profiles_drive_scenario():
    """Dotted profile inputs drive an ordinary handwritten module without configuration."""
    from gemini.modules.heating.boiler import ElectricBoiler
    from gemini.types.bindings import Binding, ModuleBindings

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    clock = gm.engine.Clock.range(start, start + timedelta(hours=2), "1h")
    target = Profile.constant(320, unit="K", clock=clock)
    inlet = dict(m_dot=1, T=300, p=1e5)
    boiler = ElectricBoiler()
    boiler.set_params("", {"capacity": gm.units.Quantity(1e6, "W"), "efficiency": 0.9})
    boiler.bindings = {
        "": ModuleBindings(
            controls={"temperature_setpoint": Binding(column="temperature_setpoint", unit="K")},
            inlets={"fluid_in": {}},
        )
    }
    boiler.boundary = {"stream_defaults": {"": {"fluid_in": inlet}}}
    result = gm.simulate(
        boiler,
        plan=gm.Dataset.from_profiles({"temperature_setpoint": target}),
        clock=gm.engine.Clock.from_data(gm.Dataset.from_profiles({"temperature_setpoint": target})),
        on_error="raise",
    )
    assert len(result) == 3
    assert result.to_frame()["fluid_out.temperature"].tolist() == [320] * 3


def test_units_come_from_the_unit_table():
    """Every raw unit of a supported dimension converts; others name the dimensions."""
    source = pd.Series([36.0], index=pd.to_datetime(["2024-01-01"]), name="flow")
    profile = Profile.from_series(source, "t/h")
    assert (profile.quantity, profile.unit, profile.values) == ("mass_flow", "kg/s", [10.0])
    assert Profile.from_series(source, "°C").values == [309.15]
    with raises(ValidationError, "invalid_unit", match="'m'"):
        Profile.from_series(source, "m")


def test_resample_rejects_empty_bins():
    """An empty bin formerly surfaced as a nonfinite-value validation error."""
    source = pd.Series(
        [1.0, 2.0], index=pd.to_datetime(["2024-01-01 00:00", "2024-01-01 03:00"]), name="x"
    )
    profile = Profile.from_series(source, "W")
    with raises(RunError, "invalid_data", match="bin at 2024-01-01 01:00:00\\+00:00 is empty"):
        profile.resample(timedelta(hours=1), "mean")
