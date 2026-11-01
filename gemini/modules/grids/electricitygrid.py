"""The public electricity grid: the plant's edge for bought and sold electricity."""

from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.modules.grids import _physics
from gemini.modules.module import Module
from gemini.physics import energy
from gemini.types import Power


class ElectricityGrid(Module):
    """Grid connection point: what the consumers draw and the generators give, within limits.

    Every consumer connects its ``power_in`` to ``power_out`` and every generator its ``power_out``
    to ``power_in``; both ports take any number of connections. Their balance is imported when
    positive and exported when negative, each up to its connection limit (``None`` means unlimited;
    ``_physics.net_exchange``). Consumption above the import limit is ``unserved_consumption`` (load
    to shed) and surplus generation above the export limit ``curtailed_generation``. Prices and
    emission factors live in the case. Assumptions: no reactive power, losses or
    demand charges.
    """

    def __init__(self):
        """Declare the connection limits, both sides and the exchange."""
        super().__init__()

        # Parameters
        self.import_limit = Parameter(Power | None, default=None, ge=0)
        self.export_limit = Parameter(Power | None, default=None, ge=0)

        # Inlets
        self.power_in = Inlet(Power, kind="electricity", many=True)

        # Outputs
        self.net_import = Output(Power)
        self.net_export = Output(Power)
        self.unserved_consumption = Output(Power)
        self.curtailed_generation = Output(Power)
        self.is_import_limited = Output(bool)
        self.is_export_limited = Output(bool)

        # Outlets
        self.power_out = Outlet(Power, kind="electricity", many=True)

    def forward(self, inlets):
        """Exchange electricity only: what leaves is what the consumers drew."""

        # Outputs
        exchange = _physics.net_exchange(
            energy.total_power(inlets.power_out),
            energy.total_power(inlets.power_in),
            self.import_limit,
            self.export_limit,
        )
        self.net_import = exchange.net_import
        self.net_export = exchange.net_export
        self.unserved_consumption = exchange.unserved_consumption
        self.curtailed_generation = exchange.curtailed_generation
        self.is_import_limited = self.unserved_consumption > 0
        self.is_export_limited = self.curtailed_generation > 0

        outlets = dict()
        return outlets
