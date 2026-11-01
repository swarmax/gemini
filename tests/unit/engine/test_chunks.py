"""Chunks of ticks: one code path for a row and a window, identical to a row-by-row build."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from gemini.engine.chunks import PathColumns, ResultChunk
from gemini.modules import Module
from gemini.modules.declarations import Output
from gemini.run.results import Results
from gemini.types import Health, ModuleResult, Ports, Ratio, Stream, Values
from gemini.types.shapes import problem
from tests.fixtures.errors import raises
from tests.fixtures.frames import path_frame

SIZE = 8
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
TIMES = [START + timedelta(hours=hour) for hour in range(SIZE)]
DURATIONS = [3600.0] * SIZE
NAN = float("nan")

PRESENT = {
    "pump": [1, 1, 1, 0, 0, 1, 1, 1],
    "twin": [0, 0, 1, 1, 1, 1, 1, 0],
    "tank": [1] * SIZE,
}
OUTPUTS = {
    "pump": {
        "head": np.array([2.0, 2.5, 3.0, 99.0, 99.0, 3.5, 4.0, 4.5]),
        "count": np.array([1, 2, 3, 0, 0, 4, 5, 6]),
        "flag": np.array([True, False, True, False, False, True, True, False]),
        "maybe": np.array([1.0, NAN, 2.0, 0.0, 0.0, NAN, 3.0, 4.0]),
        "items": [[1.0, 2.0], [], [3.0], None, None, [4.0], [5.0, 6.0], [7.0]],
        "label": ["a", "b", "c", "", "", "d", "e", "f"],
        "electricity": np.array([10.0, 11.0, 12.0, 0.0, 0.0, 13.0, 14.0, 15.0]),
    },
    "twin": {
        "flag": np.array([True, True, False, True, False, True, True, True]),
        "pressure_drop": np.array([5.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]),
    },
    "tank": {
        "level": np.arange(SIZE) * 0.5,
        "full": np.array([False, False, True, True, False, False, True, True]),
        "steps": np.arange(SIZE),
        "state": ["idle"] * 4 + ["fill"] * 4,
    },
}
FLOWS = {
    "pump": np.array([1.0, 0.0, 2.0, 0.0, 0.0, 3.0, 0.0, 4.0]),
    "twin": np.array([0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0]),
    "tank": np.zeros(SIZE),
}
HEALTH = {
    "pump": dict(
        assessed=np.ones(SIZE, dtype=bool),
        score=np.array([1.0, 0.9, 0.8, 0.0, 0.0, 0.7, 0.6, 0.5]),
        alarm=np.array([False, False, True, False, False, True, True, True]),
        message=np.array(["ok", "ok", "low", "", "", "low", "low", "low"]),
        metrics={"drift": np.array([0.0, 0.1, 0.2, 0.0, 0.0, 0.3, 0.4, 0.5])},
    ),
    "twin": dict(assessed=False, score=1.0, alarm=False, message="none", metrics={}),
    "tank": None,
}
SKIPS = [{}, {}, {}, {}, {"pump": {"pump.fluid_in.p": 1}}, {}, {}, {}]
ERRORS = [(3, problem("pump", "module_error", "boom"))]
CUTS = [[8], [1] * 8, [3, 5], [2, 2, 4], [4, 1, 3], [7, 1]]


def stream(flow):
    """Return a stream whose mass flow is the given scalar or array."""
    return Stream(
        m_dot=gm.units.Quantity(flow, "kg/s"),
        T=gm.units.Quantity(np.full_like(np.asarray(flow, dtype=float), 300.0), "K"),
        p=gm.units.Quantity(1e5, "Pa"),
    )


def element(values, row):
    """Return one row of a column as a plain Python value."""
    return values[row].item() if isinstance(values, np.ndarray) else values[row]


def column(values, rows):
    """Return the rows of a column: an array slice or a list."""
    return values[rows] if isinstance(values, np.ndarray) else [values[row] for row in rows]


def result_of(path, rows, plain):
    """Return the result and health of a path over ``rows``, plain values for one row."""
    take = (lambda values: element(values, rows[0])) if plain else (lambda v: column(v, rows))
    outputs = {name: take(values) for name, values in OUTPUTS[path].items()}
    if plain:
        outputs = {name: (None if value != value else value) for name, value in outputs.items()}
    flow = take(FLOWS[path])
    result = ModuleResult(outputs=Values(outputs), outlets=Ports({"out": stream(flow)}))
    spec = HEALTH[path]
    if spec is None:
        return result, None
    fields = {
        name: take(value) if isinstance(value, np.ndarray) else value
        for name, value in spec.items()
        if name != "metrics"
    }
    metrics = {name: take(value) for name, value in spec["metrics"].items()}
    return result, Health(**fields, metrics=metrics)


def chunk_of(start, stop):
    """Return the rows ``start:stop`` as one chunk of arrays."""
    rows = np.arange(start, stop)
    tables = {}
    for path in PRESENT:
        present = np.array(PRESENT[path], dtype=bool)[rows]
        if not present.any():
            continue
        result, health = result_of(path, rows, False)
        tables[path] = PathColumns.of(result, health, present)
    return ResultChunk(
        TIMES[start:stop],
        DURATIONS[start:stop],
        tables,
        SKIPS[start:stop],
        [(row - start, error) for row, error in ERRORS if start <= row < stop],
    )


def build_by_rows():
    """Return a Results committed one tick at a time, as a run with callbacks does."""
    return build_by_chunks([1] * SIZE)


def build_by_chunks(cuts):
    """Return a Results committed in chunks of the given sizes."""
    results = Results()
    start = 0
    for size in cuts:
        results.commit(chunk_of(start, start + size))
        start += size
    return results


def reference_frame(rows, times):
    """Return the table the former row-dict storage built: a list of rows to a DataFrame."""
    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(times, name="timestamp"))
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["module_path", "field"])
    return frame


def reference_cells(path, row):
    """Return the cells one path adds to a row dict, as the former ``Results.append`` did."""
    result, health = result_of(path, [row], True)
    cells = {(path, key): value for key, value in result.outputs.items()}
    cells[path, "operating"] = bool(FLOWS[path][row] != 0)
    if health is None:
        return cells
    cells[path, "health_assessed"] = health.assessed
    cells[path, "health_score"] = health.score
    cells[path, "health_alarm"] = health.alarm
    cells[path, "health_message"] = health.message
    cells.update({(path, "health_metric_" + key): value for key, value in health.metrics.items()})
    return cells


def reference_rows():
    """Return the row dicts of the former ``Results.append`` for the scenario."""
    rows = [{} for _ in range(SIZE)]
    for row in range(SIZE):
        for path in PRESENT:
            if PRESENT[path][row]:
                rows[row].update(reference_cells(path, row))
    return rows


def test_a_tick_by_tick_build_equals_the_former_row_dict_storage():
    """One-tick commits give the frame of the former row-dict storage."""
    frame = path_frame(build_by_rows())
    reference = reference_frame(reference_rows(), TIMES)
    pd.testing.assert_frame_equal(frame[reference.columns], reference)
    assert frame[("pump", "flag")].dtype == object
    assert frame[("pump", "count")].dtype == np.float64
    assert frame[("pump", "maybe")].dtype == np.float64
    assert frame[("tank", "full")].dtype == bool
    assert frame[("tank", "steps")].dtype == np.int64
    assert frame[("tank", "state")].dtype == pd.StringDtype(na_value=NAN)
    assert frame[("pump", "items")].dtype == object


@pytest.mark.parametrize("cuts", CUTS)
def test_chunks_equal_the_tick_by_tick_build(cuts):
    """One chunk or several give the same table, column order, dtypes and diagnostics."""
    expected, built = build_by_rows(), build_by_chunks(cuts)
    pd.testing.assert_frame_equal(built.to_frame(), expected.to_frame())
    pd.testing.assert_frame_equal(built.to_frame(table="energy"), expected.to_frame(table="energy"))
    assert built.skip_counts == expected.skip_counts and built.errors() == expected.errors()
    assert len(built) == SIZE and built._energy == expected._energy
    pd.testing.assert_series_equal(built["pump"].head, expected["pump"].head)


def test_save_load_and_slice_equal_the_row_by_row_build(tmp_path):
    """Saved files and slices are the same whichever way the results were committed.

    A loaded result takes further commits like any other.
    """
    expected, built = build_by_rows(), build_by_chunks([3, 5])
    loaded = Results.from_npz(built.to_npz(tmp_path / "chunks.npz"))
    pd.testing.assert_frame_equal(loaded.to_frame(), expected.to_frame())
    loaded.commit(ResultChunk([START + timedelta(hours=SIZE)], [3600.0], {}))
    assert len(loaded) == SIZE + 1 and len(loaded.to_frame()) == SIZE + 1
    for start in (2, 5):
        tail, reference = built.slice(start), expected.slice(start)
        pd.testing.assert_frame_equal(tail.to_frame(), reference.to_frame())
        assert tail.skip_counts == reference.skip_counts and tail.errors() == reference.errors()
        pd.testing.assert_frame_equal(
            tail.to_frame(table="energy"), reference.to_frame(table="energy")
        )


def test_list_columns_and_none_cells_follow_the_row_rules():
    """A list column with ``None`` and a float column given as a list with ``None`` infer alike."""
    first = ResultChunk(
        TIMES[:2],
        DURATIONS[:2],
        {"a": PathColumns(np.ones(2, dtype=bool), {"x": [1.0, None], "y": [None, None]})},
    )
    second = ResultChunk(
        TIMES[2:4],
        DURATIONS[2:4],
        {"a": PathColumns(np.array([True, False]), {"x": [3.0, 0.0], "y": [None, None]})},
    )
    results = Results()
    results.commit(first)
    results.commit(second)
    rows = [{("a", "x"): 1.0, ("a", "y"): None}, {("a", "x"): None, ("a", "y"): None}]
    rows += [{("a", "x"): 3.0, ("a", "y"): None}, {}]
    pd.testing.assert_frame_equal(path_frame(results), reference_frame(rows, TIMES[:4]))


def test_a_column_present_in_one_chunk_only_is_nan_in_the_others():
    """A field that appears in a later chunk takes the order of its first appearance."""
    first = ResultChunk(
        TIMES[:1], DURATIONS[:1], {"a": PathColumns(np.ones(1, dtype=bool), {"x": np.array([1.0])})}
    )
    second = ResultChunk(
        TIMES[1:2],
        DURATIONS[1:2],
        {
            "b": PathColumns(np.ones(1, dtype=bool), {"z": np.array([2])}),
            "a": PathColumns(np.ones(1, dtype=bool), {"x": np.array([3.0]), "y": np.array([4.0])}),
        },
    )
    results = Results()
    results.commit(first)
    results.commit(second)
    rows = [{("a", "x"): 1.0}, {("b", "z"): 2, ("a", "x"): 3.0, ("a", "y"): 4.0}]
    expected = reference_frame(rows, TIMES[:2])
    pd.testing.assert_frame_equal(path_frame(results), expected)
    assert list(path_frame(results).columns) == [("a", "x"), ("b", "z"), ("a", "y")]


def test_an_empty_chunk_and_an_all_skipped_chunk():
    """Chunks without any path add rows and skips but no columns."""
    results = Results()
    results.commit(ResultChunk(TIMES[:2], DURATIONS[:2], {}, [{"a": {"r": 1}}, {}]))
    frame = results.to_frame()
    assert frame.shape == (2, 0) and list(frame.columns) == []
    assert results.skip_counts == {"a": {"r": 1}}
    assert Results().to_frame().shape == (0, 0)


def test_a_chunk_with_a_wrong_length_is_refused():
    """Every column, mask, duration and skip list has one entry per tick."""
    columns = {"x": np.ones(3)}
    message = r"a\.x has 3 entries; expected one per tick \(2\)"
    with raises(gm.errors.ValidationError, "invalid_call", match=message):
        ResultChunk(TIMES[:2], DURATIONS[:2], {"a": PathColumns(np.ones(2, dtype=bool), columns)})
    with raises(gm.errors.ValidationError, "invalid_call", match="durations has 1 entries"):
        ResultChunk(TIMES[:2], DURATIONS[:1], {})


def test_a_scalar_health_and_result_broadcast_over_the_chunk():
    """Scalars broadcast; a list is a column, and operating is computed from the flows."""
    result = ModuleResult(
        outputs=Values({"power": 5.0, "tags": ["a", "b"]}),
        outlets=Ports({"out": stream(np.array([0.0, 1.0]))}),
    )
    health = Health(score=1, alarm=False, message="ok")
    table = PathColumns.of(result, health, np.ones(2, dtype=bool))
    assert table.columns["power"].tolist() == [5.0, 5.0]
    assert table.columns["tags"] == ["a", "b"]
    assert table.columns["operating"].tolist() == [False, True]
    assert table.columns["health_message"] == ["ok", "ok"]
    assert table.columns["health_assessed"].tolist() == [True, True]


def test_reading_between_commits_does_not_change_the_table():
    """A table read after each commit merges the stored chunks; the result is the same."""
    results = Results()
    start = 0
    for size in (2, 1, 3, 2):
        results.commit(chunk_of(start, start + size))
        start += size
        results.to_frame()
    expected = build_by_rows()
    pd.testing.assert_frame_equal(results.to_frame(), expected.to_frame())
    pd.testing.assert_frame_equal(results.slice(3).to_frame(), expected.slice(3).to_frame())


def test_rows_with_different_fields_fill_the_missing_cells_with_nan():
    """A field a later row adds, or an earlier row lacks, is NaN there, as in row dicts."""
    results, rows = Results(), []
    for row, names in enumerate((("a",), ("a", "b"), ("b",))):
        outputs = {name: np.array([float(row)]) for name in names}
        result = ModuleResult(outputs=Values(outputs), outlets=Ports({}))
        table = PathColumns.of(result, None, np.ones(1, dtype=bool))
        results.commit(ResultChunk(TIMES[row : row + 1], [3600.0], {"p": table}))
        rows.append({("p", name): float(row) for name in names} | {("p", "operating"): True})
    pd.testing.assert_frame_equal(path_frame(results), reference_frame(rows, TIMES[:3]))
    assert path_frame(results)[("p", "a")].isna().tolist() == [False, False, True]


def test_spread_puts_the_evaluated_rows_at_their_ticks():
    """Columns of the evaluated rows only move to their ticks; floats fill with NaN, lists None."""
    table = PathColumns(
        np.ones(2, dtype=bool),
        {
            "x": np.array([1.0, 2.0]),
            "n": np.array([5, 6]),
            "tags": ["a", "b"],
            "v": np.ones((2, 3)),
        },
    )
    spread = table.spread(np.array([1, 3]), 4)
    assert spread.present.tolist() == [False, True, False, True]
    assert spread.columns["x"][[1, 3]].tolist() == [1.0, 2.0] and np.isnan(spread.columns["x"][0])
    assert spread.columns["n"].dtype == np.int64 and spread.columns["n"][3] == 6
    assert spread.columns["tags"] == [None, "a", None, "b"] and spread.columns["v"].shape == (4, 3)
    assert table.spread(np.array([0, 1]), 2).columns["x"] is table.columns["x"]


def test_without_marks_ticks_absent_and_rows_cut_a_chunk():
    """``without`` keeps the columns; ``rows`` cuts times, columns, skips and errors alike."""
    chunk = chunk_of(0, SIZE)
    table = chunk.tables["pump"]
    assert table.without(np.array([0, 2])).present.tolist()[:3] == [False, True, False]
    assert table.without(np.array([], dtype=int)) is table
    cut = chunk.rows(3, 5)
    assert cut.times == TIMES[3:5] and cut.skips == SKIPS[3:5]
    assert cut.errors == [(0, ERRORS[0][1])] and len(cut.tables["pump"].present) == 2


class Share(Module):
    """A leaf with an optional ratio output and a plain float output."""

    def __init__(self):
        """Declare the outputs."""
        super().__init__()

        # Outputs
        self.share = Output(Ratio | None)
        self.plain = Output(float)

    def forward(self, inlets):
        """Expose no fluid outlets."""

        outlets = dict()
        return outlets


def test_a_declared_optional_float_output_reads_nan_as_none():
    """An ``X | None`` output with NaN is a list with ``None``, as a direct call's values are."""
    values = {"share": np.array([0.5, np.nan]), "plain": np.array([1.0, np.nan])}
    result = ModuleResult(
        outputs=Values._trusted(values, dict(Share()._outputs)), outlets=Ports({})
    )
    table = PathColumns.of(result, None, np.ones(2, dtype=bool))
    assert table.columns["share"] == [0.5, None]
    assert np.isnan(table.columns["plain"][1])
