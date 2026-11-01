"""The fixed point of a loop on the backends: the same iterates, early stops kept per row."""

import numpy as np
import pytest

from gemini.compiler.graph.fixedpoint import FixedPoint
from gemini.plants._utils import loops
from gemini.types import WATER, Stream


def test_a_fixed_point_gives_the_current_value_of_each_field_and_the_active_rows():
    """The columns are the iterates by carry index; ``active`` marks the rows left."""
    tear = loops.Tear(Stream(m_dot=1.0, T=300.0, p=1e5, fluid=WATER), None, None)
    found = FixedPoint([tear], np.array([False, True]))
    assert [found.column(index) for index in range(3)] == [1.0, 300.0, 1e5]
    assert found.column("active").tolist() == [False, True]


def test_the_iteration_of_a_graph_is_the_iteration_of_a_call():
    """One pass that halves the distance to 340 K converges at 340 K, rows and scalar alike."""

    def around(tears):
        images = [
            Stream._trusted(m_dot=1.0, T=0.5 * tear.fields["T"].tried + 170.0, p=1e5, fluid=WATER)
            for tear in tears
        ]
        return images, False

    tears = [loops.Tear(Stream._trusted(m_dot=1.0, T=300.0, p=1e5, fluid=WATER), None, None)]
    assert not np.any(loops.iterate(tears, 1e-9, 50, around))
    assert tears[0].fields["T"].current == pytest.approx(340.0, abs=1e-9)
