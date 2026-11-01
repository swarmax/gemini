"""Flow splitter dividing one stream into two branches."""

from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet
from gemini.modules.module import Module
from gemini.physics import separation
from gemini.types import Fraction, Stream


class Splitter(Module):
    """Ideal tee dividing a feed into two branches at the commanded mass-flow split.

    ``branch2_out`` carries ``split_fraction * m_dot`` and ``branch1_out`` the rest; both keep the
    feed temperature, pressure and fluid. The tee has no pressure loss or heat exchange (put a
    ``Pipe`` or ``Valve`` in a branch for those), so mass and energy close to rounding. The
    commanded split stands for whatever sets it in the plant (balancing valves, branch
    resistances); the splitter does not solve a hydraulic network. Reverse flow (``m_dot < 0``)
    raises ``PhysicsError``: a reversed splitter is a ``Mixer``.
    """

    def __init__(self):
        """Declare the feed, the split command and both branch outlets."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.split_fraction = Control(Fraction)

        # Outlets
        self.branch1_out = Outlet(Stream)
        self.branch2_out = Outlet(Stream)

    def forward(self, inlets):
        """Divide the feed mass flow between the two branches."""

        # Outlets
        fluid_in = inlets.fluid_in
        require_forward(self.path, "fluid_in.m_dot", fluid_in.m_dot)
        first_flow, second_flow = separation.split_flow(fluid_in.m_dot, self.split_fraction)
        branch1_out = fluid_in.with_(m_dot=first_flow)
        branch2_out = fluid_in.with_(m_dot=second_flow)

        outlets = dict(branch1_out=branch1_out, branch2_out=branch2_out)
        return outlets
