"""Where the data folder is: the one place that names ``inputs/``.

``inputs/`` sits next to the package in a source checkout and is not installed: a function of this
file that needs it raises ``RunError`` with code ``inputs_missing`` when it is absent, and only
then, so nothing fails at import time.
That error is why this file, alone among the topic files, imports ``gemini.errors``.
"""

from pathlib import Path

from gemini.errors import RunError

PACKAGE = Path(__file__).resolve().parents[1]
INPUTS = PACKAGE.parent / "inputs"


def _input(relative):
    """Return the path of ``relative`` below ``inputs/``; raise when there is no such folder."""
    if not INPUTS.is_dir():
        raise RunError(
            f"inputs: {relative} = not found; expected a source checkout of the repository, "
            "whose inputs folder is not installed",
            path=relative,
            code="inputs_missing",
        )
    return INPUTS / relative


def plant_values(name):
    """Return the path of the example values of plant ``name``; the file may not exist."""
    return _input(f"plants/{name}.json")


def doublet_heat(name):
    """Return the path of the measured data file ``name``."""
    return _input(f"doublet_heat/{name}")
