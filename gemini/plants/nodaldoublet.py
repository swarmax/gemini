"""Doublet produced against a wellhead pressure and injected through a solved pump head."""

from gemini.modules.declarations import Boundary, Inlet, Outlet, Parameter
from gemini.modules.environment import Formation
from gemini.modules.pumps import ESP, InjectionPump
from gemini.modules.subsurface import InjectionReservoir, ProductionReservoir
from gemini.modules.wells import InjectionWell, ProductionWell
from gemini.plants.plant import Plant
from gemini.types import MassFlow, Power, Pressure, Stream


class NodalDoublet(Plant):
    """Production and injection limbs whose rate and pump head come from two constraints.

    The counterpart of the upstream GEMINI simulator's ``ProducerWell`` and ``InjectorWell``
    components. The first constraint finds the production rate within ``production_rates`` at
    which the reservoir, the well below the ESP, the ESP and the riser deliver the
    ``wellhead_pressure`` boundary. The second finds the setpoint of the injection pump, between
    its suction pressure and ``maximum_injection_pressure``, at which the injection well delivers
    the bottomhole pressure the receiving aquifer needs. When the column of brine delivers it
    already, the pump stays at its suction pressure: it adds no head and draws no electricity.

    A parent plant connects the two limbs through its surface equipment, as with ``Doublet``:
    the parent opens this plant and solves its constraints in its own order.

    Its ``injection_pump`` serves this one limb at a solved rate, so ``gm.study.size`` leaves it
    unsized: a plant that prices it states its ``nominal_flow`` and ``nominal_head``.

    A building block, not schedulable on its own: a run sets ``esp.frequency`` and
    ``wellhead_pressure``.
    """

    def __init__(self):
        """Declare the limbs, the solve brackets, the wellhead boundary and the constraints."""
        super().__init__()

        # Modules
        self.formation = Formation()
        self.reservoir = ProductionReservoir()
        self.well = ProductionWell()
        self.esp = ESP()
        self.riser = ProductionWell()
        self.injection_pump = InjectionPump()
        self.injector = InjectionWell()
        self.sink = InjectionReservoir()

        # Parameters
        self.production_rates = Parameter(
            tuple[MassFlow, MassFlow],
            description="Lowest and highest mass flow the production solve may use",
        )
        self.maximum_injection_pressure = Parameter(
            Pressure, description="Highest pressure the injection pump may deliver"
        )

        # Inlets
        self.return_in = Inlet(Stream)
        self.power_in = Inlet(Power, kind="electricity")

        # Boundaries
        self.wellhead_pressure = Boundary(
            Pressure, description="Pressure required at the production wellhead"
        )

        # Outlets
        self.supply_out = Outlet(Stream)

        # Connections
        self.connect("return_in", "injection_pump.fluid_in")
        self.connect("power_in", "esp.power_in")
        self.connect("power_in", "injection_pump.power_in")
        self.connect("injection_pump.fluid_out", "injector.wellhead_in")
        self.connect("injector.bottom_out", "sink.sandface_in")
        self.connect("reservoir.sandface_out", "well.bottom_in")
        self.connect("well.wellhead_out", "esp.fluid_in")
        self.connect("esp.fluid_out", "riser.bottom_in")
        self.connect("well.loss_out", "formation.heat_in")
        self.connect("riser.loss_out", "formation.heat_in")
        self.connect("injector.loss_out", "formation.heat_in")
        self.connect("riser.wellhead_out", "supply_out")

        # Constraints
        self.constrain(
            "riser.wellhead_out.p",
            equals="wellhead_pressure",
            by="reservoir.production_rate",
            bounds="production_rates",
        )
        self.constrain(
            "injector.bottom_out.p",
            at_least="sink.bottomhole_pressure",
            by="injection_pump.pressure_setpoint",
            bounds=("injection_pump.fluid_in.p", "maximum_injection_pressure"),
        )
