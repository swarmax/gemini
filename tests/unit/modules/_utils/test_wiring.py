"""Stream-identity wiring traces leaf-to-leaf transfers and always removes its hooks."""

import gemini as gm
from gemini.modules import Filter, Module
from gemini.modules._utils.wiring import trace_wiring
from gemini.modules.declarations import Inlet, Outlet
from gemini.types import Stream
from tests.fixtures.designs import with_values
from tests.fixtures.errors import raises

STREAM = Stream(
    m_dot=gm.units.Quantity(10, "kg/s"),
    T=gm.units.Quantity(330, "K"),
    p=gm.units.Quantity(1e6, "Pa"),
)


class Train(Module):
    """Two filters in series."""

    def __init__(self):
        """Declare both filters and the train ports."""
        super().__init__()

        # Modules
        self.first = with_values(Filter())
        self.second = with_values(Filter())

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream through both filters."""

        # Modules
        first = self.first(fluid_in=inlets.fluid_in)
        second = self.second(fluid_in=first.outlets.fluid_out)

        # Outlets
        outlet = second.outlets.fluid_out

        outlets = dict(fluid_out=outlet)
        return outlets


def hook_counts(plant):
    """Return the number of hooks on every module."""
    return [(len(module._hooks), len(module._pre_hooks)) for module in plant.modules()]


def test_trace_reports_leaf_to_leaf_edges():
    """The second filter consumes exactly the stream the first produced."""
    assert trace_wiring(Train(), {"fluid_in": STREAM}) == {
        ("first", "fluid_out", "second", "fluid_in")
    }


def test_trace_removes_its_hooks_after_a_failure():
    """A failing call leaves no observers behind."""
    plant = Train()
    before = hook_counts(plant)
    with raises(gm.errors.ValidationError, "invalid_call", match="missing required inlet"):
        trace_wiring(plant, {})
    assert hook_counts(plant) == before
