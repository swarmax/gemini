"""The error code of a row without an error."""

import numpy as np

NONE = np.uint32(np.iinfo(np.uint32).max)
"""The error code of a row without an error while the error pass runs.

NOTE(refactor): the pass keeps each code one less than the code of its check, as an unsigned
integer, so that no error is the largest value and "the lowest code wins" is one ``np.minimum``;
the public codes (``reached``, ``0`` for no error) are the checks' own.
"""
