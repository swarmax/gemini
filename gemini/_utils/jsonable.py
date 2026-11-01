"""Turn the values GEMINI computes into plain JSON."""

import math
from collections.abc import Mapping
from datetime import date, datetime

import numpy as np
import pandas as pd
from pydantic import BaseModel


def to_plain(value):
    """Return ``value`` as plain JSON: NumPy to Python, NaN and infinity to ``None``.

    A Pydantic model becomes its JSON fields; mappings get text keys; lists, tuples, arrays and
    pandas series become lists; a time becomes ISO 8601 text; an object with a ``to_dict`` method,
    such as a ``Quantity``, becomes its dict. The result passes
    ``json.dumps(result, allow_nan=False)``. Anything else raises ``TypeError``.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (np.bool_, np.integer)):
        return value.item()
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, int):
        return value
    if isinstance(value, BaseModel):
        return to_plain(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray, pd.Series, pd.Index)):
        return [to_plain(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if callable(getattr(value, "to_dict", None)):
        return to_plain(value.to_dict())
    raise TypeError(f"to_plain: value = {value!r}; expected a JSON-like value")
