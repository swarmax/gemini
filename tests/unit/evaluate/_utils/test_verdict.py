"""The verdict of a list of checks."""

import pytest

from gemini.evaluate._utils.verdict import verdict


@pytest.mark.parametrize(
    "verdicts,expected",
    [([True, None], True), ([None, None], None), ([True, False, None], False), ([], None)],
)
def test_the_verdict_is_false_with_any_failure_and_true_only_with_a_pass(verdicts, expected):
    """False wins, then True, else undecided."""
    assert verdict(verdicts) is expected
