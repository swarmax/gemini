"""The plant's edge for discarded flows."""

from gemini.modules import WasteGrid
from gemini.types import Stream
from gemini.units import Quantity
from tests.fixtures.equivalence import assert_module_matches

BLOWDOWN = Stream(m_dot=Quantity(0.4, "kg/s"), T=Quantity(350.0, "K"), p=Quantity(2e5, "Pa"))


def test_the_discarded_flows_end_at_the_port():
    """The port holds what arrives, from any number of modules."""
    result = WasteGrid()(waste_in=[BLOWDOWN, BLOWDOWN.with_(m_dot=0.1)])
    assert [stream.m_dot for stream in result.inlets.waste_in] == [0.4, 0.1]
    assert WasteGrid()().inlets.waste_in == []


def test_traced_call_matches_one_call_per_row():
    """A leaf with nothing to compute traces."""
    assert_module_matches(WasteGrid(), [{}, {}])
