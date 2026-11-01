"""``gm.evaluate.failures`` on a small run where two modules fail at some steps."""

import json

import numpy as np
import pytest

import gemini as gm
from tests.fixtures.engine_plants import TICKS, pair_frame, pair_plant


@pytest.fixture(scope="module")
def failed_run():
    """Run the pair: ``first`` fails at two steps, ``second`` at one, and one step lacks data."""
    frame = pair_frame(
        {("level", 3): -1.0, ("level", 5): -1.0, ("level2", 7): -1.0, ("pressure", 9): np.nan}
    )
    engine = gm.Engine(pair_plant(), on_error="record")
    return engine.replay(gm.Dataset.from_frame(frame))


def test_rows_are_grouped_by_module_and_code_with_the_most_frequent_first(failed_run):
    """Each group has its count, first and last step and the message of its first row."""
    found = gm.evaluate.failures(failed_run)
    groups = {(group["path"], group["code"]): group for group in found.groups}
    first = groups[("first", "out_of_range")]
    assert (first["count"], first["kind"]) == (2, "failed")
    assert first["first"] == TICKS[3].isoformat() and first["last"] == TICKS[5].isoformat()
    assert "level = -" in first["message"]
    assert groups[("second", "out_of_range")]["count"] == 1
    skipped = groups[("first", "missing_value")]
    assert skipped["kind"] == "skipped" and skipped["first"] == TICKS[9].isoformat()
    counts = [group["count"] for group in found.groups]
    assert counts == sorted(counts, reverse=True) and found.groups[0] is first
    assert found.total == len(failed_run.errors()) == 5


def test_the_json_and_the_table_hold_the_same_groups(failed_run):
    """``to_dict`` needs no encoder and ``to_frame`` has one row per group."""
    found = gm.evaluate.failures(failed_run)
    plain = found.to_dict()
    assert json.loads(json.dumps(plain, allow_nan=False)) == plain
    frame = found.to_frame()
    assert len(frame) == len(found) == len(plain["groups"])
    assert frame["count"].tolist() == [group["count"] for group in plain["groups"]]


def test_a_run_without_failures_has_no_group():
    """The report of a clean run is empty, and its table keeps the columns."""
    engine = gm.Engine(pair_plant(), on_error="record")
    found = gm.evaluate.failures(engine.replay(gm.Dataset.from_frame(pair_frame())))
    assert found.to_dict() == {"total": 0, "groups": []}
    assert found.to_frame().empty and "count" in found.to_frame().columns
