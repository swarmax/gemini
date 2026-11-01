"""The plant balance finds a module and a plant that do not close, and says by how much."""

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.modules import Module, Pipe
from gemini.modules.declarations import Inlet, Outlet
from gemini.runtime import settings
from gemini.types import Stream
from tests.fixtures.air import air
from tests.fixtures.balance import assert_plant_closes
from tests.fixtures.designs import with_values
from tests.fixtures.parity import BACKENDS

HOT = Stream(
    m_dot=gm.units.Quantity(2.0, "kg/s"),
    T=gm.units.Quantity(350.0, "K"),
    p=gm.units.Quantity(4e5, "Pa"),
)


class Leak(Module):
    """Lose a tenth of the stream without saying so."""

    def __init__(self):
        """Declare the ports."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass nine tenths of the flow."""
        outlets = dict(fluid_out=inlets.fluid_in.with_(m_dot=0.9 * inlets.fluid_in.m_dot))
        return outlets


class Line(Module):
    """One child between the two ports of the root."""

    def __init__(self, child):
        """Declare the child and the ports."""
        super().__init__()

        # Modules
        self.child = child

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream through the child."""
        passed = self.child(fluid_in=inlets.fluid_in)
        outlets = dict(fluid_out=passed.outlets.fluid_out)
        return outlets


def by_name(checks):
    """Return the checks by name."""
    return {check["name"]: check for check in checks}


def test_a_leak_fails_its_module_and_the_plant():
    """A tenth of the mass and of the enthalpy goes nowhere."""
    plant = Line(Leak())
    found = by_name(gm.evaluate.plant_balance(plant, None, plant(fluid_in=HOT)))
    assert list(found) == ["child mass", "child energy", "plant mass", "plant energy"]
    assert found["child mass"]["passed"] is False
    assert found["child mass"]["value"].value == pytest.approx(0.1)
    assert found["child energy"]["passed"] is False
    assert found["plant mass"]["value"].value == pytest.approx(0.1)
    assert to_plain(found["plant mass"]["limit"]) == {"value": 1e-6, "unit": "-"}


def test_a_loss_that_reaches_no_edge_module_fails_the_plant_only():
    """The pipe closes through ``loss_out``; the root sees heat that reaches no edge module."""

    class Lost(Line):
        def forward(self, inlets):
            passed = self.child(fluid_in=inlets.fluid_in, air_in=air(283.15))
            outlets = dict(fluid_out=passed.outlets.fluid_out)
            return outlets

    pipe = with_values(Pipe()).set_params(
        "",
        {
            "length": gm.units.Quantity(500, "m"),
            "inner_diameter": gm.units.Quantity(0.1, "m"),
            "elevation_change": gm.units.Quantity(0, "m"),
            "heat_transfer_coefficient": gm.units.Quantity(5.0, "W/m2/K"),
        },
    )
    plant = Lost(pipe)
    found = by_name(gm.evaluate.plant_balance(plant, None, plant(fluid_in=HOT)))
    assert found["child energy"]["passed"] is True
    assert found["plant mass"]["passed"] is True
    assert found["plant energy"]["passed"] is False


def test_a_closed_line_passes():
    """A stream that leaves as it came closes at the module and at the root."""

    class Same(Leak):
        def forward(self, inlets):
            outlets = dict(fluid_out=inlets.fluid_in)
            return outlets

    plant = Line(Same())
    assert len(assert_plant_closes(plant, plant(fluid_in=HOT))) == 4


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_finished_run_is_checked_under_any_backend(backend):
    """The columns of a run are arrays: a backend of scalars checks them the same."""
    plant = Line(Leak())
    run = plant(fluid_in=HOT)
    expected = gm.evaluate.plant_balance(plant, None, run)
    with settings(backend=backend):
        assert gm.evaluate.plant_balance(plant, None, run) == expected
