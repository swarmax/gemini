"""Run every example as a user would and compare what it prints.

Each of the five files in ``examples/`` runs as a subprocess from an empty temporary folder,
without ``PYTHONPATH``, which proves it is standalone: its paths come from ``__file__``. Its
output is compared with ``tests/e2e/expected/`` line by line: the text exactly, the
numbers within ``RELATIVE``, ``ABSOLUTE`` or one unit of the last printed digit (1.5 units, so that
a difference of one is not lost to rounding), so a silent change in physics shows up.
``tests/fixtures/capture_example_outputs.py`` writes the expected files; a changed number there is
evidence of a numerical change, as a changed golden is.
"""

import os
import re
import subprocess
import sys

import pytest

from tests.fixtures import ROOT

pytestmark = pytest.mark.e2e
EXAMPLES = sorted((ROOT / "examples").glob("*.py"))
SLOW_EXAMPLES = ("hackathon.py",)
"""Slow because a search over six candidate plants is what it shows: minutes, above the session
budget of the development profile, so it runs with ``-m e2e`` alone and in the release profile."""
EXPECTED = ROOT / "tests/e2e/expected"
TIMEOUT_S = 900
"""Time budget per example: a hang guard, as the hackathon flow runs for minutes."""
RELATIVE = 1e-6
ABSOLUTE = 1e-6
"""Tolerances of a printed number; the absolute one is for the rounding noise of a balance."""
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:e[+-]?\d+)?(?![\w])")


def example_environment():
    """Return the environment of a user's shell."""
    env = {name: value for name, value in os.environ.items() if name != "PYTHONPATH"}
    return env | {"PYTHONIOENCODING": "utf-8"}


def run_example(path, folder, timeout):
    """Run one example from ``folder`` and return the finished process."""
    return subprocess.run(
        [sys.executable, str(path)],
        cwd=folder,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        env=example_environment(),
    )


def expected_path(path):
    """Return the file that holds the expected output of one example."""
    return EXPECTED / path.relative_to(ROOT / "examples").with_suffix(".txt")


def last_digit(text):
    """Return the value of one unit of the last printed digit of a number."""
    mantissa, _, exponent = text.partition("e")
    decimals = len(mantissa.partition(".")[2])
    return 10.0 ** (int(exponent or 0) - decimals)


def is_close(printed, expected):
    """Tell whether a printed number agrees with the expected text of it."""
    allowed = max(RELATIVE * abs(float(expected)), ABSOLUTE, 1.5 * last_digit(expected))
    return abs(float(printed) - float(expected)) <= allowed


def differences(printed, expected):
    """Return the lines of an output that differ from the expected output."""
    printed_lines, expected_lines = printed.splitlines(), expected.splitlines()
    found = [f"{len(printed_lines)} lines, expected {len(expected_lines)}"]
    if len(printed_lines) == len(expected_lines):
        found = []
    for line, reference in zip(printed_lines, expected_lines):
        numbers, references = NUMBER.findall(line), NUMBER.findall(reference)
        same_text = NUMBER.sub("#", line) == NUMBER.sub("#", reference)
        same_count = len(numbers) == len(references)
        if not (same_text and same_count and all(map(is_close, numbers, references))):
            found.append(f"{line!r}, expected {reference!r}")
    return found


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(path, marks=[pytest.mark.slow] if path.name in SLOW_EXAMPLES else [])
        for path in EXAMPLES
    ],
    ids=[str(path.relative_to(ROOT)) for path in EXAMPLES],
)
def test_example(path, tmp_path):
    """An example runs from an empty folder within its budget and prints the expected numbers."""
    completed = run_example(path, tmp_path, TIMEOUT_S)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip()
    expected = expected_path(path).read_text(encoding="utf-8")
    assert differences(completed.stdout, expected) == []


@pytest.mark.parametrize(
    ("printed", "same"),
    [
        ("Heat: 3.21 MW", True),
        ("Heat: 3.22 MW", True),
        ("Heat: 3.23 MW", False),
        ("Heat: 3.21 kW", False),
        ("Heat: 3.21 MW, twice", False),
    ],
)
def test_a_printed_number_may_move_by_one_last_digit(printed, same):
    """The text must match and a number may round the other way, no more."""
    assert (differences(printed, "Heat: 3.21 MW") == []) is same


def test_a_balance_may_differ_in_its_rounding_noise():
    """A residual near zero is compared absolutely, and a name holding a digit is text."""
    assert differences("d0 plant mass 9.1e-16", "d0 plant mass 3.8e-16") == []
    assert differences("line one\nline two", "line one") != []
