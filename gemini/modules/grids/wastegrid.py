"""The plant's edge for discarded flows."""

from gemini.modules.declarations import Inlet
from gemini.modules.module import Module
from gemini.types import Stream


class WasteGrid(Module):
    """Where blowdown, sand and other discarded flows leave the plant.

    ``waste_in`` takes any number of connections. What leaves is read from the port; the disposal
    cost per kg is ``assumptions.finance.opex.waste_disposal`` of the case.
    """

    def __init__(self):
        """Declare the port of the discarded flows."""
        super().__init__()

        # Inlets
        self.waste_in = Inlet(Stream, kind="waste", many=True)

    def forward(self, inlets):
        """End the flows here."""

        outlets = dict()
        return outlets
