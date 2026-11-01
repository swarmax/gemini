"""Two-phase flash separator splitting geofluid into saturated steam and brine."""

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet, Output
from gemini.modules.module import Module
from gemini.modules.power import _physics
from gemini.types import STEAM, Fraction, Pressure, Stream, Temperature


class Separator(Module):
    """Flash separator: pressurised geofluid flashes to the separator pressure and splits.

    The inlet liquid enthalpy is the IAPWS-IF97 region 1 enthalpy at the inlet temperature,
    evaluated at the inlet pressure or, when that is below the saturation pressure of the
    inlet temperature, at that saturation pressure. The inlet temperature is therefore that of
    the liquid before it flashes, for example the reservoir temperature: adiabatic well flow
    and throttling are isenthalpic. Flashing to ``pressure_setpoint`` gives the steam fraction
    x = (h_in - h_f) / h_fg (DiPippo 2016, Geothermal Power Plants, 4th ed., section 5.2).
    ``gas`` leaves as dry saturated steam (``Fluid`` kind ``steam``) and ``liquid`` as saturated
    brine, both at the setpoint pressure and saturation temperature; a subcooled inlet
    (h_in <= h_f) does not flash and the liquid keeps the inlet temperature.

    Assumptions: pure-water properties (salts and non-condensable gases are ignored), perfect
    phase separation (no carry-over), adiabatic vessel without pressure loss. The liquid keeps
    the inlet fluid composition unchanged: salt concentration by flashing and the
    partitioning of dissolved gas are not modelled. Valid for inlet temperatures of 273.15 K
    to 623.15 K and setpoints of 611.213 Pa to 16.529 MPa.

    NOTE(refactor): the energy audit of ``energy_balance`` uses sensible enthalpy
    ``m_dot * cp_l * T`` and cannot represent the latent heat carried by the steam, so its
    residual is not meaningful for this module. The model is closed in IF97 enthalpies:
    m_in h_in = m_gas h_g + m_liquid h_f, which the unit tests check.
    """

    def __init__(self):
        """Declare the separator inlet, pressure control, outputs and phase outlets."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream, kind="brine")

        # Controls
        self.pressure_setpoint = Control(
            Pressure, gt=0, description="Pressure the geofluid flashes to"
        )

        # Outputs
        self.steam_fraction = Output(
            Fraction, description="Share of the inlet mass flow that flashes to steam"
        )
        self.saturation_temperature = Output(
            Temperature, description="Saturation temperature at the separator pressure"
        )

        # Outlets
        self.liquid_out = Outlet(Stream, kind="brine")
        self.gas_out = Outlet(Stream, kind="gas")

    def forward(self, inlets):
        """Flash the inlet to the setpoint pressure and split it into brine and steam."""

        # Outlets
        inlet = inlets.fluid_in
        state = self._flash(inlet)

        liquid = inlet.with_(
            m_dot=state.liquid_flow, T=state.liquid_temperature, p=self.pressure_setpoint
        )
        gas = inlet.with_(
            m_dot=state.steam_flow,
            T=state.saturation_temperature,
            p=self.pressure_setpoint,
            fluid=STEAM,
        )

        # Outputs
        self.steam_fraction = state.steam_fraction
        self.saturation_temperature = state.saturation_temperature

        outlets = dict(liquid_out=liquid, gas_out=gas)
        return outlets

    def _flash(self, inlet):
        """Return the ``_physics.flash_state`` of the inlet at the setpoint pressure."""
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        if inlet.fluid.kind == "steam":
            raise PhysicsError(
                f"{self.path}: inlet.fluid.kind = 'steam'; expected a liquid geofluid"
            )
        ops.check(
            self.pressure_setpoint <= inlet.p,
            PhysicsError,
            "{path}: pressure_setpoint = {setpoint} Pa; expected at most the inlet pressure "
            "{p} Pa",
            path=self.path,
            setpoint=self.pressure_setpoint,
            p=inlet.p,
        )
        return _physics.flash_state(inlet.m_dot, inlet.T, inlet.p, self.pressure_setpoint)
