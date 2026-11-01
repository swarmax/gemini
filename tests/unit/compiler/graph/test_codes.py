"""The error code of a row without an error is the largest unsigned value."""

import numpy as np

from gemini.compiler.graph.codes import NONE


def test_no_error_is_the_largest_code_so_the_lowest_code_wins():
    """One ``np.minimum`` keeps the first check that failed, whatever else is no error."""
    assert NONE == np.iinfo(np.uint32).max
    assert np.minimum(np.uint32(3), NONE) == 3
