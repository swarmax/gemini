"""A price, a revenue or an emission factor of the case, as the run reads it."""

import numpy as np

from gemini.case._utils.access import require
from gemini.errors import ValidationError


def level(case, path, count):
    """Return the value at ``path`` of ``case``: a float, or an array of ``count`` steps.

    A constant is returned as it is; a profile must have one value per tick of the run, or
    ``invalid_value`` names the path. An absent value raises ``missing_assumption``.
    """
    value = require(case, path)
    if np.ndim(value) == 0:
        return float(value)
    if len(value) != count:
        raise ValidationError(
            f"{path} has {len(value)} values; expected {count}, one per step of the run",
            path=path,
            code="invalid_value",
        )
    return np.asarray(value, dtype=float)
