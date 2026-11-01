"""Result access, unit conversion, summaries, JSON views, slices and lossless files."""

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from gemini.engine.chunks import PathColumns, ResultChunk
from gemini.run.results import Results
from gemini.types import Health, ModuleResult, Values
from gemini.types.shapes import problem
from tests.fixtures.errors import raises


def result(**outputs):
    """Return a minimal module result with the given outputs."""
    return ModuleResult(outputs=Values(outputs), outlets=gm.types.Ports({}))


def commit(rows, time, path, outputs, health, dt, skips):
    """Commit one tick of one path: its outputs and health as columns of one entry."""
    table = PathColumns.of(
        result(**{name: np.array([value]) for name, value in outputs.items()}),
        health,
        np.ones(1, dtype=bool),
    )
    rows.commit(ResultChunk([time], [dt], {path: table}, [skips]))


def results():
    """Return two rows: one pump with power and electricity, one skip."""
    rows = Results()
    times = [datetime(2024, 1, 1, hour, tzinfo=timezone.utc) for hour in (0, 1)]
    health = Health(score=1, alarm=True, message="low")
    for time, power in zip(times, (1000.0, 3000.0)):
        commit(
            rows,
            time,
            "pump",
            dict(head=2e5, power_in=power),
            health,
            3600.0,
            {"pump": {"pump.fluid_in.p": 1}},
        )
    return rows


def test_empty_results_summary():
    """An empty finite run has an empty summary."""
    assert Results().energy_report() == {} and Results().summary() == {}
    assert Results().to_frame(table="energy").empty


def test_access_conversion_and_suggestions():
    """Fields are Series; known fields convert units; unknown names suggest a match."""
    rows = results()
    assert rows["pump"].head.tolist() == [2e5, 2e5]
    assert rows["pump"].get("head", unit="bar").tolist() == pytest.approx([2.0, 2.0])
    assert rows["pump"].get("head", unit="barg").tolist() == pytest.approx([2.0, 2.0])
    with raises(gm.errors.ValidationError, "unknown_name", match="did you mean 'pump'"):
        rows["pumps"]
    with raises(gm.errors.ValidationError, "unknown_name", match="did you mean 'head'"):
        rows["pump"].heads
    with pytest.raises(ValueError, match="for unit conversion"):
        rows["pump"].get("power_in", unit="kW")


def test_a_path_reads_one_output_or_port_field():
    """An output and a port field read by their path, as a plant's paths name them."""
    frame = results()
    assert frame["pump.head"].tolist() == [2e5, 2e5]
    with raises(gm.errors.ValidationError, "unknown_name"):
        frame["pump.nothing.T"]


def test_summary_integrates_energy_and_counts_alarms_and_skips():
    """Energy is power times dt; alarms and skip reasons are counted per module."""
    summary = results().to_frame(table="energy")
    row = summary.loc[("pump", "power_in")]
    assert row["energy_J"] == 4000.0 * 3600
    assert row["peak_W"] == 3000.0 and row["alarms"] == 2 and row["skipped"] == 2
    assert row["reasons"] == {"pump.fluid_in.p": 2}


def test_the_energy_report_is_the_table_as_plain_values():
    """The report is plain JSON: every number of the table is a value with its unit."""
    rows = results()
    report = rows.energy_report()
    json.dumps(report, allow_nan=False)
    entry = report["pump"]["power_in"]
    assert entry["energy"] == {"value": 4000.0 * 3600, "unit": "J"}
    assert entry["peak"] == {"value": 3000.0, "unit": "W"}
    assert entry["alarms"] == {"value": 2, "unit": "-"}
    assert entry["skipped"] == {"value": 2, "unit": "-"}
    assert entry["reasons"] == {"pump.fluid_in.p": 2}
    table = rows.to_frame(table="energy").loc[("pump", "power_in")]
    assert entry["hours"] == {"value": table["hours"], "unit": "h"}


def test_an_unknown_table_is_refused():
    """``to_frame`` names the tables it has."""
    with pytest.raises(gm.errors.ValidationError, match="expected 'series'"):
        results().to_frame(table="balance")


def test_slice_and_lossless_files(tmp_path):
    """A slice keeps its own skips; saved results load with identical cells and summary."""
    rows = results()
    tail = rows.slice(1)
    assert len(tail) == 1 and tail.skip_counts == {"pump": {"pump.fluid_in.p": 1}}
    path = rows.to_npz(tmp_path / "results.npz")
    loaded = Results.from_npz(path)
    pd.testing.assert_frame_equal(loaded.to_frame(), rows.to_frame())
    pd.testing.assert_frame_equal(loaded.to_frame(table="energy"), rows.to_frame(table="energy"))


def with_units():
    """Return the two-row pump results with the units a plant would declare."""
    rows = results()
    rows.declared = {"pump": {"head": "Pa", "power_in": "W"}}
    return rows


def test_units_maps_every_column_to_its_unit():
    """``units[column]`` is the unit ``to_frame`` states for the column, ``-`` when undeclared."""
    rows = with_units()
    frame = rows.to_frame()
    assert rows.units == dict(frame.attrs["units"])
    assert rows.units["pump.head"] == "Pa" and rows.units["pump.power_in"] == "W"
    assert rows.units["pump.health_score"] == "-" and Results().units == {}


def test_names_lists_every_readable_field_by_path():
    """names() maps each path to its fields, in column order."""
    names = with_units().names()
    assert list(names) == ["pump"] and names["pump"][:2] == ["head", "power_in"]
    assert "health_score" in names["pump"] and Results().names() == {}


def test_get_returns_time_values_and_unit_as_json():
    """get() gives ISO times, plain values and the SI unit; windows are inclusive."""
    rows = with_units()
    series = rows.get("pump", "power_in")
    assert series == {
        "time": ["2024-01-01T00:00:00+00:00", "2024-01-01T01:00:00+00:00"],
        "value": [1000.0, 3000.0],
        "unit": "W",
    }
    json.dumps(series, allow_nan=False)
    late = rows.get("pump", "head", start="2024-01-01T01:00:00Z")
    assert late["time"] == ["2024-01-01T01:00:00+00:00"] and late["value"] == [2e5]
    assert rows.get("pump", "operating", end=datetime(2024, 1, 1, tzinfo=timezone.utc))[
        "value"
    ] == [True]
    assert rows.get("pump", "health_score")["unit"] == "-"
    with raises(gm.errors.ValidationError, "unknown_name", match="did you mean 'head'"):
        rows.get("pump", "heads")
    with raises(gm.errors.ValidationError, "unknown_name", match="did you mean 'pump'") as caught:
        rows.get("pumps", "head")
    assert caught.value.suggestions == ("pump",)


def test_summary_reports_min_max_mean_and_unit_per_numeric_field():
    """summary() covers numeric fields only, for one path and for a window."""
    rows = with_units()
    summary = rows.summary()
    assert summary["pump"]["power_in"] == {
        "min": {"value": 1000.0, "unit": "W"},
        "max": {"value": 3000.0, "unit": "W"},
        "mean": {"value": 2000.0, "unit": "W"},
    }
    assert "operating" not in summary["pump"] and "health_message" not in summary["pump"]
    late = rows.summary("pump", start="2024-01-01T01:00:00Z")
    assert late["pump"]["power_in"]["min"]["value"] == 3000.0
    json.dumps(summary, allow_nan=False)
    with raises(gm.errors.ValidationError, "unknown_name"):
        rows.summary("pumps")


def test_errors_list_failed_and_skipped_rows_with_their_codes():
    """Each row is a problem with its time; skips use missing_value."""
    rows = with_units()
    rows.commit(
        ResultChunk(
            [datetime(2024, 1, 1, 2, tzinfo=timezone.utc)],
            [3600.0],
            {},
            [{"pump": {"pump.fluid_in.p": 1}}],
            [(0, problem("pump", "module_error", "boom"))],
        )
    )
    errors = rows.errors()
    assert [row["code"] for row in errors] == ["missing_value"] * 2 + [
        "module_error",
        "missing_value",
    ]
    assert errors[2] == {
        "path": "pump",
        "code": "module_error",
        "message": "boom",
        "suggestions": [],
        "time": "2024-01-01T02:00:00+00:00",
    }
    assert errors[0]["message"] == "pump.fluid_in.p"
    assert {row["code"] for row in errors} <= set(gm.errors.ROW_CODES)
    json.dumps(errors, allow_nan=False)


def test_to_dict_is_plain_json_with_units():
    """to_dict() holds the time axis, every series with its unit, errors and the end state."""
    rows = with_units()
    rows.end_state = {"position": "2024-01-01T01:00:00+00:00", "module_states": {}}
    data = rows.to_dict()
    json.dumps(data, allow_nan=False)
    assert data["series"]["pump"]["head"] == {"value": [2e5, 2e5], "unit": "Pa"}
    assert data["duration"] == {"value": [3600.0, 3600.0], "unit": "s"} and len(data["time"]) == 2
    assert data["end_state"] == rows.end_state and len(data["errors"]) == 2


def test_files_and_bytes_keep_units_end_state_and_every_cell(tmp_path):
    """A saved or serialised result loads with the same frame, units, errors and end state."""
    rows = with_units()
    rows.end_state = {"position": "2024-01-01T01:00:00+00:00", "module_states": {"a": {"x": 0.1}}}
    for loaded in (
        Results.from_npz(rows.to_npz(tmp_path / "plain")),
        Results.from_bytes(rows.to_bytes()),
    ):
        pd.testing.assert_frame_equal(loaded.to_frame(), rows.to_frame())
        assert loaded.declared == rows.declared and loaded.end_state == rows.end_state
        assert loaded.errors() == rows.errors() and loaded.skip_counts == rows.skip_counts
        assert loaded.get("pump", "head") == rows.get("pump", "head")
    assert (tmp_path / "plain.npz").exists()


def test_an_archive_needs_no_pickle(tmp_path):
    """Every array of the archive loads with allow_pickle=False, and garbage is refused."""
    path = with_units().to_npz(tmp_path / "results.npz")
    with np.load(path, allow_pickle=False) as archive:
        assert "metadata" in archive.files
        assert all(archive[name].dtype != object for name in archive.files)
    with pytest.raises(gm.errors.ValidationError, match="results archive") as caught:
        Results.from_bytes(b"not an archive")
    assert caught.value.code == "invalid_format"
    old = tmp_path / "old.csv"
    old.write_text("time\n")
    with pytest.raises(gm.errors.ValidationError, match="results archive"):
        Results.from_npz(old)


def test_slices_keep_units_and_end_state():
    """The new rows of a live call read like the whole."""
    rows = with_units()
    rows.end_state = {"position": None, "module_states": {}}
    tail = rows.slice(1)
    assert tail.declared == rows.declared and tail.end_state == rows.end_state
    assert tail.get("pump", "head")["unit"] == "Pa" and len(tail.errors()) == 1


def with_quantities():
    """Return the two-row pump results with the quantities a plant would declare."""
    rows = with_units()
    rows.quantities = {"pump": {"head": "pressure_difference", "power_in": "power"}}
    return rows


UNITS = {"power": "kW", "pressure": "bar"}


def test_get_converts_on_the_way_out_and_says_the_unit():
    """A map from quantity to unit reaches the field through its family."""
    rows = with_quantities()
    assert rows.get("pump", "power_in", units=UNITS)["value"] == [1.0, 3.0]
    assert rows.get("pump", "power_in", units=UNITS)["unit"] == "kW"
    assert rows.get("pump", "head", units=UNITS) == {
        "time": rows.get("pump", "head")["time"],
        "value": [2.0, 2.0],
        "unit": "bar",
    }
    assert rows.get("pump", "health_score", units=UNITS)["unit"] == "-"
    assert rows.get("pump", "power_in")["value"] == [1000.0, 3000.0]


def test_summary_and_to_dict_convert_too():
    """Statistics and series name the unit used; nothing stored changes."""
    rows = with_quantities()
    electricity = rows.summary(units=UNITS)["pump"]["power_in"]
    assert electricity["mean"] == {"value": 2.0, "unit": "kW"}
    series = rows.to_dict(units={**UNITS, "duration": "h"})
    assert series["series"]["pump"]["head"] == {"value": [2.0, 2.0], "unit": "bar"}
    assert series["duration"] == {"value": [1.0, 1.0], "unit": "h"}
    assert rows.summary()["pump"]["power_in"]["mean"] == {"value": 2000.0, "unit": "W"}


def test_to_frame_converts_and_lists_the_units():
    """Column names stay; ``attrs["units"]`` says the unit of each column."""
    rows = with_quantities()
    frame = rows.to_frame(units=UNITS)
    assert frame["pump.power_in"].tolist() == [1.0, 3.0]
    assert frame.attrs["units"]["pump.power_in"] == "kW"
    assert frame.attrs["units"]["pump.head"] == "bar"
    plain = rows.to_frame()
    assert plain["pump.power_in"].tolist() == [1000.0, 3000.0]
    assert plain.attrs["units"]["pump.power_in"] == "W"
    pd.testing.assert_index_equal(frame.columns, plain.columns)


def test_the_energy_report_converts_too():
    """The dict takes ``units``; the table has fixed columns and refuses them."""
    rows = with_quantities()
    entry = rows.energy_report(units={"energy": "kWh", "power": "kW"})["pump"]["power_in"]
    assert entry["energy"] == {"value": 4.0, "unit": "kWh"}
    assert entry["peak"] == {"value": 3.0, "unit": "kW"}
    with pytest.raises(gm.errors.ValidationError, match="without units"):
        rows.to_frame(UNITS, table="energy")


@pytest.mark.parametrize(
    "call",
    [
        lambda rows, units: rows.get("pump", "head", units=units),
        lambda rows, units: rows.summary(units=units),
        lambda rows, units: rows.to_dict(units=units),
        lambda rows, units: rows.to_frame(units=units),
        lambda rows, units: rows.energy_report(units=units),
    ],
)
def test_a_wrong_map_raises_on_every_view(call):
    """An unknown quantity and a unit that does not fit it are wrong input."""
    rows = with_quantities()
    with raises(gm.errors.ValidationError, "unknown_name"):
        call(rows, {"powr": "kW"})
    with raises(gm.errors.ValidationError, "invalid_unit"):
        call(rows, {"power": "bar"})


def test_quantities_survive_files_and_slices(tmp_path):
    """A loaded result and a live slice convert as the run did."""
    rows = with_quantities()
    loaded = Results.from_npz(rows.to_npz(tmp_path / "results.npz"))
    assert loaded.quantities == rows.quantities
    assert loaded.get("pump", "head", units=UNITS)["unit"] == "bar"
    assert rows.slice(1).get("pump", "head", units=UNITS)["unit"] == "bar"


def test_the_series_table_is_built_once_and_stays_the_callers(fast_run_results):
    """A second call reads the same table; what a caller writes to its copy stays there."""
    first = fast_run_results.to_frame()
    column = first.columns[0]
    first[column] = -1.0
    assert not (fast_run_results.to_frame()[column] == -1.0).all()
    assert fast_run_results._series is not None


def test_durations_are_the_ones_of_the_dictionary(fast_run_results):
    """The tick durations, without building the JSON of every column."""
    expected = fast_run_results.to_dict()["duration"]["value"]
    assert list(fast_run_results.durations) == expected


@pytest.fixture
def fast_run_results():
    """Return the results of a small run of two ticks."""
    plant = gm.Plant("Hot")
    plant.add(
        "HeatingGrid",
        name="users",
        params={"minimum_return_temperature": gm.units.Quantity(313.15, "K")},
    )
    plant.connect("in_port", "users.supply_in")
    plant.connect("users.return_out", "out_port")
    index = pd.date_range("2027-01-01", periods=2, freq="D", tz="UTC", name="time")
    columns = {
        "in_port.m_dot": 10.0,
        "in_port.T": 350.0,
        "in_port.p": 5e5,
        "users.heat_demand": 1e5,
    }
    return gm.simulate(plant, plan=pd.DataFrame(columns, index=index))
