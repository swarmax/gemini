"""The sign check shared by the energy and the mass ledgers."""

import numpy as np

from gemini._utils.strings import join_path
from gemini.types.shapes import check, measure


def columns(results, wanted):
    """Return the result columns for which ``wanted(path, field)`` holds, as a frame."""
    frame = results.to_frame()
    names = [
        join_path(path, field)
        for path, fields in results.names().items()
        for field in fields
        if wanted(path, field)
    ]
    return frame[names]


def nonnegative(name, values, tolerance, unit, absent):
    """Judge that every value is finite-or-missing and at least ``-tolerance`` in ``unit``."""
    limit = measure(tolerance, unit)
    if values.shape[1] == 0:
        return check(name, None, measure(None, unit, absent), limit)
    array = values.to_numpy(dtype=float)
    if np.isnan(array).all():
        return check(name, None, measure(None, unit, "every value is missing"), limit)
    smallest = float(np.nanmin(array))
    passed = bool(smallest >= -tolerance and not np.isinf(array).any())
    return check(name, passed, measure(smallest, unit), limit)
