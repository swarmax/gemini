"""Write what every example prints to ``tests/e2e/expected/``.

``python tests/fixtures/capture_example_outputs.py``. Review the diff: a changed number is a
changed result, and ``tests/e2e/test_examples.py`` holds what the test does with these files.
"""

import tempfile
from pathlib import Path

from tests.e2e.test_examples import EXAMPLES, TIMEOUT_S, expected_path, run_example


def main():
    """Run every example once from a new folder and store its output."""
    for path in EXAMPLES:
        with tempfile.TemporaryDirectory() as folder:
            completed = run_example(path, Path(folder), TIMEOUT_S)
        target = expected_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(completed.stdout, encoding="utf-8")


if __name__ == "__main__":
    main()
