"""The plant's edge for bought chemicals."""

from gemini.modules.declarations import Outlet
from gemini.modules.module import Module
from gemini.physics import gas
from gemini.types import Stream


class ChemicalGrid(Module):
    """Where a chemical product enters the plant.

    ``chemical_out`` is offered without flow at normal conditions and the dosing module returns what
    it takes, so the dosed amount is read from the port. The product price is
    ``assumptions.finance.opex.chemical`` of the case.
    """

    def __init__(self):
        """Declare the outlet."""
        super().__init__()

        # Outlets
        self.chemical_out = Outlet(Stream, kind="chemical", offered=True, drawn=True)

    def _offer(self, inlets):
        """Offer the product at normal conditions, with the module's fluid."""
        offered = Stream._si(
            m_dot=0.0, T=gas.NORMAL_TEMPERATURE, p=gas.NORMAL_PRESSURE, fluid=self.fluid
        )
        return {"chemical_out": offered}

    def forward(self, inlets):
        """Nothing but what the dosing draws leaves."""

        outlets = dict()
        return outlets
