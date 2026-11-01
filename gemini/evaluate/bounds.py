"""The declared limits of every output a run recorded."""

import numpy as np
import pandas as pd

from gemini._utils.strings import join_path
from gemini.modules.declarations import Output
from gemini.types.quantities import Temperature
from gemini.types.shapes import check, measure

_OUTSIDE = {
    "ge": np.less,
    "gt": np.less_equal,
    "le": np.greater,
    "lt": np.greater_equal,
}
"""For each limit of ``Declaration.limits``, the comparison that a violating value satisfies."""


_TEMPERATURE = Output(Temperature)
"""The declaration whose limits judge the temperature of a port."""


def _outside(values, limits):
    """Return how many values violate any of the ``limits``; a missing value never does."""
    array = values.to_numpy(dtype=float)
    violated = np.zeros(array.shape, dtype=bool)
    for key, limit in limits.items():
        violated |= _OUTSIDE[key](array, limit)
    return int(violated.sum())


def _limits(outputs, field):
    """Return the limits of a column: an output's, or those of a port's absolute temperature."""
    if field in outputs:
        return outputs[field].limits()
    return _TEMPERATURE.limits() if field.endswith(".temperature") else {}


def bounds(plant, case, results):
    """Check that every recorded output is inside the limits its module declares.

    The limits are those of the output's declaration (``ge``, ``gt``, ``le``, ``lt`` from its
    quantity and its bounds, see ``Declaration.limits``), read from the module at the
    column's path. Boolean and text columns, outputs without a limit and the health columns are
    not judged.

    Parameters
    ----------
    plant : Module
        The plant that produced ``results``; a path of the results it lacks raises
        ``ValidationError``.
    case : Case
        The case of the run; the check does not read it.
    results : Results
        A finished run.

    Returns
    -------
    dict
        ``{name: "bounds", passed, value, limit}``: ``value`` is the number of values outside
        their limits, over all columns and ticks, and ``limit`` is 0. ``passed`` is ``None``,
        with a ``reason`` in ``value``, when no recorded output has a limit.
    """
    frame = results.to_frame()
    judged, violations = 0, 0
    for path, fields in results.names().items():
        outputs = plant.get_submodule(path).outputs(recurse=False)
        for field in fields:
            column = frame[join_path(path, field)]
            limits = _limits(outputs, field)
            if limits and pd.api.types.is_numeric_dtype(column) and column.dtype != bool:
                judged += 1
                violations += _outside(column, limits)
    limit = measure(0, "-")
    if not judged:
        reason = "no recorded output has a declared limit"
        return check("bounds", None, measure(None, "-", reason), limit)
    return check("bounds", violations == 0, measure(violations, "-"), limit)
