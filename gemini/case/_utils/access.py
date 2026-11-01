"""Reading a value of the case: the value, or the error that names its path."""

import numpy as np

from gemini.errors import ValidationError


def require(root, path, prefix=""):
    """Return the value at ``path`` below ``root``, or raise saying the case must give it.

    ``prefix`` is the path of ``root`` in the case, so that an error names the whole path. A value
    that is absent raises ``missing_value``, or ``missing_assumption`` below ``assumptions``.
    """
    value = root
    for name in path.split("."):
        value = value.get(name) if isinstance(value, dict) else getattr(value, name, None)
        if value is None:
            full = f"{prefix}.{path}" if prefix else path
            code = "missing_assumption" if full.split(".")[0] == "assumptions" else "missing_value"
            raise ValidationError(
                f"{full} is missing; expected a value in the case (it has no default)",
                path=full,
                code=code,
            )
    return value


def series(case, path):
    """Return the value at ``path`` of ``case`` as an array on the steps of ``case.time``.

    A constant is repeated for every step; a profile is returned as stored.
    """
    value = require(case, path)
    return np.broadcast_to(value, (len(case.time.index),)).astype(float)
