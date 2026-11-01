"""``require_forward`` refuses a flow against its marked direction and records a trace check."""

import numpy as np
import pytest

from gemini.errors import PhysicsError
from gemini.modules._utils.flow import require_forward
from gemini.ops import Symbolic


def test_a_zero_or_forward_flow_passes():
    """Zero and positive flows are not an error."""
    assert require_forward("orc", "fluid_in.m_dot", 0.0) is None
    assert require_forward("orc", "fluid_in.m_dot", 12.5) is None


def test_a_reverse_flow_names_the_path_the_flow_and_the_unit():
    """The message carries where, which flow, its value and its unit."""
    with pytest.raises(PhysicsError, match=r"^orc: fluid_in.m_dot = -3.5 kg/s; expected >= 0"):
        require_forward("orc", "fluid_in.m_dot", -3.5)
    with pytest.raises(PhysicsError, match=r"^pump: dp = -1 Pa; expected >= 0"):
        require_forward("pump", "dp", -1, unit="Pa")


def test_an_array_of_rows_names_the_first_reverse_row():
    """Over rows the first failing row is reported."""
    with pytest.raises(PhysicsError, match=r"flow = -2.0 kg/s"):
        require_forward("orc", "flow", np.array([1.0, -2.0, -5.0]))
    assert require_forward("orc", "flow", np.array([1.0, 2.0])) is None


def test_a_traced_flow_records_the_check_instead_of_raising():
    """In a trace the check becomes a node, so the compiled run checks it per row."""
    recorded = []

    class Recorder(Symbolic):
        def __ge__(self, other):
            return self.record(type("Op", (), {"name": "ge"}), (self, other))

        def record(self, definition, operands, attributes=None):
            recorded.append((definition.name, attributes))
            return self

    require_forward("orc", "flow", Recorder())
    names = [name for name, _ in recorded]
    assert names[-1] == "check"
    assert recorded[-1][1]["error"] is PhysicsError
    assert recorded[-1][1]["values"]["name"] == "flow"
