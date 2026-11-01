"""The gas grid: the plant's edge for bought gas."""

from gemini.modules.declarations import Outlet, Parameter
from gemini.modules.module import Module
from gemini.physics import gas
from gemini.types import Fraction, Stream
from gemini.types.fluid import grid_gas


class GasGrid(Module):
    """Gas grid: bought gas of ``composition``, which the plant states.

    ``gas_out`` is offered at normal conditions, without flow, and the taker returns what it burns:
    a burner on ``gas_out``, or a ``GasMakeup`` for the shortfall of the co-produced gas.
    """

    def __init__(self):
        """Declare the grid gas composition and the outlet."""
        super().__init__()

        # Parameters
        self.composition = Parameter(
            dict[str, Fraction],
            structural=True,
            description="Mole or mass fractions of the gas components by name",
        )

        # Outlets
        self.gas_out = Outlet(Stream, kind="gas", offered=True, drawn=True)

    def _offer(self, inlets):
        """Offer the grid gas at normal conditions."""
        offered = Stream._si(
            m_dot=0.0,
            T=gas.NORMAL_TEMPERATURE,
            p=gas.NORMAL_PRESSURE,
            fluid=grid_gas(self.composition),
        )
        return {"gas_out": offered}

    def forward(self, inlets):
        """Nothing but what the taker draws leaves the grid."""

        outlets = dict()
        return outlets
