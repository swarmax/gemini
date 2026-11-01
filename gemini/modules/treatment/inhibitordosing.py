"""Scale or corrosion inhibitor injection at a commanded mass dose."""

from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.modules.treatment import _physics
from gemini.types import Fraction, MassFlow, Stream


class InhibitorDosing(Module):
    """Scale or corrosion inhibitor injection proportional to the treated mass flow.

    The dose is the commanded mass of product per mass of treated fluid, the usual field basis
    of inhibitor programmes (mg/kg, written ppm; accepted at the API as ``"10 ppm"``). Typical
    geothermal scale-inhibitor doses are a few to some tens of ppm of product (Gallup, 2009,
    "Production engineering in geothermal technology: A review", *Geothermics* 38, 326-334):

    - ``product_mass_flow = dose * inlet.m_dot``;
    - ``active_mass_flow = product_concentration * product_mass_flow``.

    The dosed product is not added to the stream: at ppm doses it changes the mass flow by less
    than any flowmeter resolves, and adding it would need a product inlet stream to keep the
    mass balance closed. The stream therefore passes unchanged (mass, temperature, pressure and
    fluid) and ``mass_balance`` closes exactly; the neglected mass is ``product_mass_flow``,
    a relative error equal to ``dose``. Dosing-pump power and injection-quill pressure loss are
    neglected. Cost is not modelled; multiply ``product_mass_flow`` by the product price.
    Reverse flow raises ``PhysicsError``.
    """

    def __init__(self):
        """Declare the product strength, ports, dose command and dosing rates."""
        super().__init__()

        # Parameters
        self.product_concentration = Parameter(Fraction, gt=0)

        # Inlets
        self.fluid_in = Inlet(Stream, kind="brine")
        self.chemical_in = Inlet(Stream, kind="chemical", drawn=True)

        # Controls
        self.dose = Control(Fraction)

        # Outputs
        self.active_mass_flow = Output(MassFlow)

        # Outlets
        self.fluid_out = Outlet(Stream, kind="brine")

    def forward(self, inlets):
        """Pass the treated stream through unchanged."""

        # Outlets
        inlet = inlets.fluid_in
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        product, _ = _physics.dosing_flows(self.dose, inlet.m_dot, self.product_concentration)
        outlet = inlet.with_(m_dot=inlet.m_dot + product)
        chemical_in = inlets.chemical_in.with_(m_dot=product, T=inlet.T)

        # Outputs
        product, active = _physics.dosing_flows(
            self.dose, inlets.fluid_in.m_dot, self.product_concentration
        )
        self.active_mass_flow = active

        outlets = dict(fluid_out=outlet, chemical_in=chemical_in)
        return outlets
