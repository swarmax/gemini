"""Degasser separating a share of the free gas from the liquid, with a pressure loss."""

from gemini.modules._utils.cost import Equipment
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.modules.treatment import _physics
from gemini.types import Fraction, Pressure, PressureDifference, Stream


class Degasser(Equipment, Module):
    """Degasser that removes a share of the inlet free gas and applies a pressure loss.

    The inlet free gas is ``fluid.gas_mass_fraction * m_dot``; the share
    ``separation_efficiency`` of it leaves through ``gas``, the rest stays in ``liquid``:

    - ``gas.m_dot = eta * x * inlet.m_dot`` with ``eta = separation_efficiency`` and
      ``x = inlet.fluid.gas_mass_fraction``;
    - ``liquid.m_dot = inlet.m_dot - gas.m_dot``;
    - the liquid gas mass fraction is ``(1 - eta) * x / (1 - eta * x)``, so the free gas left
      in the liquid is conserved.

    Both outlets leave at the vessel pressure, ``outlet_pressure`` when set, otherwise
    ``nominal_pressure_drop`` below the inlet pressure, and at the inlet temperature: no
    dissolved-gas exsolution, no latent or expansion heat. ``separation_efficiency`` is a lumped
    vessel performance figure; residence time, level and gas solubility (Henry's law) are not
    modelled, so dissolved CO2 stays in the liquid. Reverse flow scales both outlets, because the
    split is linear in mass flow.

    The ``gas`` stream's ``m_dot`` is the separated gas mass flow at vessel pressure and
    temperature. Its ``fluid`` is a ``kind="gas"`` fluid with the inlet's ``gas_composition``, with
    the ``cp_l`` of the liquid: the sensible audit values every stream at ``cp_l``, which the
    degasser therefore closes exactly, and the gas enthalpy at ``cp_l`` is an audit convention. An
    inlet fluid without a composition gives the gas the liquid outlet's fluid: its liquid
    properties then do not describe the gas.

    NOTE(refactor): ``separation_efficiency`` is structural: it sets the gas fraction of the liquid
    outlet's ``Fluid``, which is static during a trace, so a trace reads it as a plain number.
    NOTE(refactor): the 0.149 bar default loss comes from Sep_Pin/Sep_Pout in the example.
    NOTE(refactor): the default ``separation_efficiency = 0`` reproduces the former liquid-only
    model exactly for every fluid (zero gas flow, liquid unchanged but for the pressure loss);
    the example brine carries no free gas either. Separation efficiency is vessel specific and has
    no industry-typical value; set it from design data or a measured gas flow.
    """

    equipment_kind = "degasser"

    def __init__(self):
        """Declare degasser design data, inlet and split outlets."""
        super().__init__()

        # Parameters
        self.outlet_pressure = Parameter(Pressure | None, default=None)
        self.nominal_pressure_drop = Parameter(
            PressureDifference, default=_physics.DEFAULT_DEGASSER_DROP, ge=0
        )
        self.heat_transfer_coefficient = Parameter(float, default=0, ge=0)
        self.separation_efficiency = Parameter(Fraction, default=0, structural=True)

        # Inlets
        self.fluid_in = Inlet(Stream, kind="brine")

        # Outputs
        self.pressure_drop = Output(PressureDifference, soft_sensor=True)

        # Outlets
        self.liquid_out = Outlet(Stream, kind="brine")
        self.gas_out = Outlet(Stream, kind="gas")

    def forward(self, inlets):
        """Split the separated free gas from the liquid at the vessel pressure."""

        # Outlets
        inlet = inlets.fluid_in
        pressure = (
            self.outlet_pressure
            if self.outlet_pressure is not None
            else inlet.p - self.nominal_pressure_drop
        )
        liquid_flow, gas_flow, remaining = _physics.degasser_split(
            inlet.m_dot, inlet.fluid.gas_mass_fraction, self.separation_efficiency
        )
        liquid = inlet.with_(
            m_dot=liquid_flow, p=pressure, fluid=inlet.fluid.with_gas_fraction(remaining)
        )
        gas = liquid.with_(m_dot=gas_flow, fluid=inlet.fluid.free_gas())

        # Outputs
        self.pressure_drop = inlet.p - liquid.p

        outlets = dict(liquid_out=liquid, gas_out=gas)
        return outlets

    def capex(self, finance):
        """Return the cost of the degasser, a fixed item."""
        return self.capex_of(finance, 1)
