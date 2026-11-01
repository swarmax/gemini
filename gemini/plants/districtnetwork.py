"""A two-pipe network feeding parallel substations."""

from gemini.errors import ValidationError
from gemini.modules.container import ModuleList
from gemini.modules.declarations import Inlet, Outlet
from gemini.modules.piping import Mixer, Pipe, Splitter
from gemini.modules.pumps import CentrifugalPump
from gemini.plants._utils.wiring import mix_chain, split_chain
from gemini.plants.coolingsubstation import CoolingSubstation
from gemini.plants.heatingsubstation import HeatingSubstation
from gemini.plants.plant import Plant
from gemini.types import Power, Stream

SUBSTATIONS = {"heating": HeatingSubstation, "cooling": CoolingSubstation}
"""Substation class per network service."""


class DistrictNetwork(Plant):
    """A two-pipe network feeding ``consumers`` parallel substations.

    Flow order: ``pump``, ``supply_pipe``, ``splitters``, ``substations``, ``mixers``,
    ``return_pipe``. ``service`` is ``"heating"`` or ``"cooling"``, the substation class. The
    network pumps, splits, serves the substations in order, mixes the returns and passes the
    return pipe.

    A building block, not schedulable on its own: a run sets the pump frequency, each valve and
    each demand.
    """

    purpose = "both"

    def __init__(self, consumers=2, service="heating"):
        """Build a network of the given size; both are structural arguments."""
        super().__init__()
        if service not in SUBSTATIONS:
            raise ValidationError(
                f"service = {service!r}; expected 'heating' or 'cooling'", code="invalid_design"
            )
        if consumers < 1:
            raise ValidationError(f"consumers = {consumers}; expected >= 1", code="invalid_design")
        self._size = {"consumers": consumers, "service": service}

        # Modules
        self.pump = CentrifugalPump()
        self.supply_pipe = Pipe()
        self.splitters = ModuleList(Splitter() for _ in range(consumers - 1))
        self.substations = ModuleList(SUBSTATIONS[service]() for _ in range(consumers))
        self.mixers = ModuleList(Mixer() for _ in range(consumers - 1))
        self.return_pipe = Pipe()

        # Inlets
        self.supply_in = Inlet(Stream)
        self.power_in = Inlet(Power, kind="electricity")
        self.air_in = Inlet(Stream, kind="air")

        # Outlets
        self.return_out = Outlet(Stream)
        self.loss_out = Outlet(Power, kind="heat")

        # Connections
        self.connect("supply_in", "pump.fluid_in")
        self.connect("power_in", "pump.power_in")
        self.connect("air_in", "supply_pipe.air_in")
        self.connect("air_in", "return_pipe.air_in")
        self.connect("pump.fluid_out", "supply_pipe.fluid_in")
        self._connect_feed(consumers)
        self._connect_returns(consumers)
        self.connect("return_pipe.fluid_out", "return_out")
        for index in range(consumers):
            self.connect("power_in", f"substations.{index}.power_in")
            self.connect(f"substations.{index}.loss_out", "loss_out")
        self.connect("pump.loss_out", "loss_out")
        self.connect("supply_pipe.loss_out", "loss_out")
        self.connect("return_pipe.loss_out", "loss_out")

    def _connect_feed(self, consumers):
        """Divide the feed over the substations: each splitter serves one, the last what is left."""
        targets = [f"substations.{index}.supply_in" for index in range(consumers)]
        if consumers == 1:
            self.connect("supply_pipe.fluid_out", targets[0])
            return
        self.connect("supply_pipe.fluid_out", "splitters.0.fluid_in")
        split_chain(self, "splitters", targets)

    def _connect_returns(self, consumers):
        """Mix the returns of the substations in order and feed the return pipe."""
        ends = [f"substations.{index}.return_out" for index in range(consumers)]
        mix_chain(self, ends, "mixers", "return_pipe.fluid_in")
