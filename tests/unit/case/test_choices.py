"""``gm.case.Range`` and ``Choices``."""

import gemini as gm
from gemini.units import Quantity
from tests.fixtures.errors import raises


def test_a_range_of_counts_and_a_range_of_lengths():
    """Counts stay numbers; lengths are metres."""
    counts = gm.case.Range(1, 3)
    assert (counts.min, counts.max, counts.unit) == (1, 3, None)
    depth = gm.case.Range(Quantity(2, "km"), Quantity(3500, "m"))
    assert (depth.min, depth.max, depth.unit) == (2000.0, 3500.0, "m")
    assert depth.to_dict()["min"] == {"value": 2000.0, "unit": "m"}
    assert gm.case.Range.from_dict(depth.to_dict()) == depth


def test_min_above_max_is_out_of_bounds():
    """``min <= max``."""
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        gm.case.Range(3, 1)


def test_a_range_of_two_kinds_is_invalid_unit():
    """A count and a length do not make a range."""
    with raises(gm.errors.ValidationError, "invalid_unit"):
        gm.case.Range(1, Quantity(5, "m"))


def test_the_choices_are_counts_of_doublets_and_a_depth():
    """Doublets are whole numbers from 1; depth is a range of lengths."""
    choices = gm.case.Choices(
        doublets=gm.case.Range(1, 3), depth=gm.case.Range(Quantity(2000, "m"), Quantity(3500, "m"))
    )
    assert choices.to_dict()["doublets"] == {"min": 1, "max": 3}
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        gm.case.Choices(doublets=gm.case.Range(0, 3))
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        gm.case.Choices(doublets=gm.case.Range(1.5, 3))
    with raises(gm.errors.ValidationError, "invalid_unit"):
        gm.case.Choices(depth=gm.case.Range(1, 3))
