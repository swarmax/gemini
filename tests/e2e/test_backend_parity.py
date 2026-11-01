"""Every example prints the same output on every backend in ``BACKENDS``.

Each example runs once per backend through ``tests/fixtures/run_example.py``, which reads the
backend from ``GEMINI_EXAMPLE_BACKEND`` and enters ``gm.runtime.settings`` before running the
script with ``runpy``. Standard output must be equal line by line once the lines that report a
duration and the temporary working directory are removed. Adding a backend means adding it to
``tests.fixtures.parity.BACKENDS``.
"""

import re

import pytest

from tests.e2e.test_examples import EXAMPLES, SLOW_EXAMPLES, TIMEOUT_S, run_example
from tests.fixtures import ROOT
from tests.fixtures.parity import BACKENDS, REFERENCE, others

pytestmark = [pytest.mark.e2e, pytest.mark.slow]
WRAPPER = ROOT / "tests/fixtures/run_example.py"
TIMING = re.compile(r"\b(elapsed|took|duration|wall[- ]?time|runtime)\b|\d\s*(ms|seconds)\b", re.I)


def _run(path, backend, folder):
    """Run one example under ``backend`` in ``folder`` and return its standard output."""
    folder.mkdir()
    completed = run_example(path, folder, TIMEOUT_S, runner=WRAPPER, GEMINI_EXAMPLE_BACKEND=backend)
    assert completed.returncode == 0, f"{backend}: {completed.stderr}"
    return completed.stdout.replace(str(folder), "<cwd>")


def _stable_lines(output):
    return [line for line in output.splitlines() if not TIMING.search(line)]


COMPARED = [path for path in EXAMPLES if path.name not in SLOW_EXAMPLES]
"""A slow example runs on the reference backend only: on Python it outlasts ``TIMEOUT_S``."""


@pytest.mark.parametrize("path", COMPARED, ids=[str(path.relative_to(ROOT)) for path in COMPARED])
def test_example_output_is_the_same_on_every_backend(path, tmp_path):
    """The printed numbers, tables and messages agree with the reference backend's."""
    outputs = {
        backend: _stable_lines(_run(path, backend, tmp_path / backend)) for backend in BACKENDS
    }
    assert outputs[REFERENCE]
    for backend, lines in others(outputs):
        assert lines == outputs[REFERENCE], f"{backend} against {REFERENCE}"
