"""Pressure-holding (expansion) vessel that fixes the static pressure of a closed circuit."""

from gemini.modules.declarations import Control, Inlet, Outlet, Output
from gemini.modules.module import Module
from gemini.types import Pressure, PressureDifference, Stream


class PressurizationTank(Module):
    """Pressure-maintenance vessel holding a closed circuit at its pressure setpoint.

    An expansion vessel with a pressure-maintenance pump or compressor (EN 12828:2012+A1:2014,
    Heating systems in buildings: design for water-based heating systems; VDI 4708-1:2012,
    Pressurisation, venting, degassing) fixes the pressure of the circuit at its connection
    point, the neutral point, while the vessel takes up the thermal expansion of the circuit
    water. The outlet leaves at
    ``pressure_setpoint`` with the inlet flow, temperature and fluid; ``pressure_correction``
    (setpoint minus inlet pressure) is the pressure the station adds (positive) or relieves
    (negative) to re-anchor the circuit pressure, so a persistent large value flags a pressure
    profile around the loop that does not match the design.

    The model is steady and stateless: for an hourly or 15-minute twin the vessel holds the
    setpoint by design, and a water-volume state would need the circuit water volume and mean
    temperature, which change the vessel level but not the circuit pressures or temperatures.
    Make-up and spill flows and the station's pump electricity are not modelled (zero in steady
    operation), so mass and sensible energy pass unchanged. Any flow direction is accepted.
    """

    def __init__(self):
        """Declare the circuit ports, the pressure command and the correction output."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.pressure_setpoint = Control(
            Pressure, gt=0, description="Pressure the vessel holds the circuit at"
        )

        # Outputs
        self.pressure_correction = Output(
            PressureDifference, description="Pressure setpoint minus the inlet pressure"
        )

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Set the circuit pressure to the setpoint."""

        # Outlets
        outlet = inlets.fluid_in.with_(p=self.pressure_setpoint)

        # Outputs
        self.pressure_correction = outlet.p - inlets.fluid_in.p

        outlets = dict(fluid_out=outlet)
        return outlets
