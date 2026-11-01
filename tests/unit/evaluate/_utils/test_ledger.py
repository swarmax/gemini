"""The sign check of the ledgers."""

import math

from gemini.evaluate._utils import ledger
from tests.fixtures.result_tables import make_results


def test_columns_select_by_path_and_field():
    """Only the wanted columns are in the frame."""
    results = make_results({"a": {"fuel": [1.0], "head": [2.0]}, "b": {"fuel": [3.0]}})
    frame = ledger.columns(results, lambda path, field: field == "fuel")
    assert list(frame.columns) == ["a.fuel", "b.fuel"]


def test_nonnegative_judges_the_smallest_value():
    """-1e-12 is within the tolerance; -2 is not; no column and no value are undecided."""
    ok = make_results({"a": {"fuel": [-1e-12, 4.0]}})
    frame = ledger.columns(ok, lambda path, field: True)
    assert ledger.nonnegative("x", frame, 1e-9, "W", "none")["passed"] is True
    bad = ledger.columns(make_results({"a": {"fuel": [-2.0]}}), lambda path, field: True)
    assert ledger.nonnegative("x", bad, 1e-9, "W", "none")["value"].value == -2.0
    empty = ledger.columns(ok, lambda path, field: False)
    assert ledger.nonnegative("x", empty, 1e-9, "W", "none")["value"].reason == "none"
    missing = ledger.columns(make_results({"a": {"fuel": [math.nan]}}), lambda p, f: True)
    assert ledger.nonnegative("x", missing, 1e-9, "W", "none")["passed"] is None
