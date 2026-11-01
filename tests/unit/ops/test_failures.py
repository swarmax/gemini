"""``FailedRows``: the failing rows of an eager array travel with the data, ``where`` drops them."""

import numpy as np
import pytest

from gemini import ops
from gemini.errors import PhysicsError
from gemini.ops.failures import FailedRows, Failures, failures_of, marking

MESSAGE = "{path}: x = {x} m; expected x >= 0"


@ops.physics
def checked(x):
    """Double ``x``, which must not be negative."""
    ops.check(x >= 0, PhysicsError, MESSAGE, path="pipe", x=x)
    return x * 2.0


@ops.physics
def positive(x):
    """Return ``x``, which must be above 1."""
    ops.check(x > 1, PhysicsError, "{path}: x = {x}; expected x > 1", path="tube", x=x)
    return x


@ops.physics
def stopped_or_checked(x, stopped):
    """Return zero where stopped, else the checked value."""
    return ops.where(stopped, 0.0, checked(x))


@ops.physics
def constant(x):
    """Return a number and a list for a checked input."""
    ops.check(x >= 0, PhysicsError, MESSAGE, path="pipe", x=x)
    return 1.0, [x, None]


def failed_rows(value):
    """Return the failed rows of an array, and ``[]`` for a plain one."""
    failures = failures_of(value)
    return [] if failures is None else np.flatnonzero(failures.mask).tolist()


def test_a_failing_row_marks_the_results_and_the_clean_path_has_no_subclass():
    """Only the failing rows are marked, with the exact error of a row call."""
    with marking():
        marked = checked(np.array([1.0, -2.0, 3.0, -4.0]))
        clean = checked(np.array([1.0, 2.0]))
    assert type(marked) is FailedRows and failed_rows(marked) == [1, 3]
    assert type(clean) is np.ndarray and clean.tolist() == [2.0, 4.0]
    error = failures_of(marked).error(3)
    assert type(error) is PhysicsError and str(error) == "pipe: x = -4.0 m; expected x >= 0"
    assert marked.tolist() == [2.0, -4.0, 6.0, -8.0]


def test_without_marking_the_first_failing_row_raises_at_once():
    """A direct call keeps raising, as documented."""
    with pytest.raises(PhysicsError, match="x = -2.0 m"):
        checked(np.array([1.0, -2.0, -3.0]))


def test_marks_travel_through_ops_and_numpy_arithmetic_and_the_first_check_wins():
    """The lowest check number of each row survives, whichever operand it came from."""
    with marking():
        first = checked(np.array([1.0, -1.0, -1.0, 2.0]))
        second = positive(np.array([0.5, 0.5, 3.0, 3.0]))
        total = first + second * np.ones(4)
        reduced = np.stack([ops.sqrt(second), np.exp(first)], axis=1)
        shifted = ops.maximum(first, 0.0) + 1.0
        inverse = second + first
    assert failed_rows(total) == [0, 1, 2] and failed_rows(inverse) == [0, 1, 2]
    assert failed_rows(shifted) == [1, 2]
    assert failed_rows(reduced) == [0, 1, 2] and reduced.shape == (4, 2)
    assert "pipe" in str(failures_of(total).error(1)) and "tube" in str(failures_of(total).error(0))
    assert [str(failures_of(inverse).error(row))[:4] for row in (0, 1, 2)] == [
        "tube",
        "pipe",
        "pipe",
    ]


def test_where_keeps_only_the_failures_of_the_selected_branch():
    """A row that a stopped condition selects away from the checked branch does not fail."""
    x = np.array([-1.0, -1.0, 2.0])
    with marking():
        value = stopped_or_checked(x, np.array([True, False, False]))
        none = stopped_or_checked(x, np.array([True, True, False]))
        condition = ops.where(checked(x) > 0, 1.0, 2.0)
    assert failed_rows(value) == [1] and value[[0, 2]].tolist() == [0.0, 4.0]
    assert type(none) is np.ndarray
    assert failed_rows(condition) == [0, 1]


def test_numbers_and_lists_of_a_failing_function_become_arrays_of_the_rows():
    """A literal result holds every row, so the failing rows are marked in it too."""
    with marking():
        number, items = constant(np.array([1.0, -1.0]))
    assert type(number) is FailedRows and failed_rows(number) == [1]
    assert failed_rows(items[0]) == [1] and items[1].shape == (2,) and np.isnan(items[1]).all()


def test_a_row_that_already_failed_is_not_checked_again():
    """The earlier check owns the row, as a ``Failed`` argument does."""

    @ops.physics
    def later(value):
        ops.check(value < 10, PhysicsError, "later: value = {value}", value=value)
        return value

    with marking():
        first = checked(np.array([-1.0, 1.0, 1.0]))
        result = later(first + np.array([0.0, 20.0, 0.0]))
    assert failed_rows(result) == [0, 1]
    assert str(failures_of(result).error(0)).startswith("pipe")
    assert str(failures_of(result).error(1)).startswith("later")


def test_an_inline_check_raises_the_first_row_with_the_failures_of_all():
    """Outside a physics function the check raises, noting every row it fails."""
    x = np.array([1.0, -2.0, -3.0])
    with marking(), pytest.raises(PhysicsError, match="x = -2.0 m") as raised:
        ops.check(x >= 0, PhysicsError, MESSAGE, path="pipe", x=x)
    failures = raised.value.failures
    assert failures.mask.tolist() == [False, True, True]
    assert "x = -3.0 m" in str(failures.error(2))


def test_failures_merge_by_check_number_and_restrict_to_rows():
    """Merging keeps the lower number per row; ``only`` forgets the other rows."""
    first = Failures.at(np.array([True, True, False]), lambda row: f"first {row}")
    second = Failures.at(np.array([True, False, True]), lambda row: f"second {row}")
    merged = second.merged(first)
    assert [merged.error(row) for row in range(3)] == ["first 0", "first 1", "second 2"]
    assert first.only(np.array([False, True, False])).mask.tolist() == [False, True, False]


def test_slicing_a_column_keeps_the_marks_and_a_copy_too():
    """A column of rows is still the rows; an array of another length is not."""
    with marking():
        marked = checked(np.array([1.0, -1.0]))
        columns = np.stack([marked, marked], axis=1)
    assert failed_rows(columns[:, 0]) == [1] and failed_rows(columns.copy()) == [1]
    assert failed_rows(columns[:1]) == []
