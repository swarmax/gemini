"""Single-effect water/LiBr absorption chiller or heat pump driven by hot water."""

from typing import Literal

from gemini import ops
from gemini.modules._utils.cost import Equipment
from gemini.modules.cooling import _physics, _sorption
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import heat_transfer, refrigeration
from gemini.types import (
    Dimensionless,
    Power,
    Ratio,
    Stream,
    Temperature,
    TemperatureDifference,
    ThermalConductance,
)


class AbsorptionUnit(Equipment, Module):
    """Single-effect water/LiBr absorption chiller or heat pump driven by hot water.

    Three circuits: ``generator_in`` carries the driving hot water (the geothermal heat),
    ``chilled_in`` the evaporator water and ``cooling_in`` the cooling water of absorber and
    condenser. In ``chiller`` mode the useful duty is the evaporator duty and
    ``temperature_setpoint`` is the chilled outlet temperature; in ``heat_pump`` mode
    (absorption heat pump type I) the useful duty is the absorber plus condenser heat and the
    setpoint is the cooling-circuit outlet temperature. ``capacity`` caps the useful duty.

    The available evaporator duty follows the characteristic equation (Hellmann, Schweigler and
    Ziegler 1999; Kuehn and Ziegler 2005) Q_E = s * (ddt - ddt_min) with
    ddt = t_G - a * t_AC + r * t_E at the arithmetic mean circuit temperatures in degC, solved
    in closed form from the inlet temperatures
    (``_physics.sorption_evaporator_capacity``). The delivered evaporator duty is the
    smallest of that, the setpoint request and the capacity. Q_G = Q_E / thermal_cop, the
    solution pump electricity is auxiliary_power_ratio * Q_E and Q_AC = Q_G + Q_E +
    electricity, so the model is first-law closed. Below ``minimum_driving_temperature`` at the
    generator inlet the unit is off.
    ``is_capped`` is true whenever the delivered duty falls short of the setpoint request,
    whether capacity, the characteristic equation or the driving temperature limits it.

    Assumptions: constant thermal COP (Herold, Radermacher and Klein 2016, Absorption Chillers
    and Heat Pumps, 2nd ed., give about 0.7 for single-effect water/LiBr machines, the default),
    no pressure loss, no casing heat loss, constant liquid heat capacity per stream; the unit
    throttles to the request without changing its COP. Validity: the characteristic
    coefficients ``characteristic_slope``, ``minimum_driving_difference``,
    ``rejection_coefficient`` (a) and ``evaporator_coefficient`` (r) are fitted to one machine at
    near-rated circuit flows (ideal Duehring form a = 1 + B, r = B with B about 1.1 to 1.2);
    driving hot water of about 70 to 120 degC, cooling water of 20 to 40 degC and chilled water
    above 4 degC. Crystallisation limits are not modelled.
    """

    equipment_kind = "absorption_chiller"

    def __init__(self):
        """Declare absorption machine design data, its three circuits and performance."""
        super().__init__()

        # Parameters
        self.mode = Parameter(Literal["chiller", "heat_pump"])
        self.capacity = Parameter(Power, gt=0)
        self.characteristic_slope = Parameter(ThermalConductance, gt=0)
        self.minimum_driving_difference = Parameter(TemperatureDifference)
        self.rejection_coefficient = Parameter(Dimensionless)
        self.evaporator_coefficient = Parameter(Dimensionless)
        self.thermal_cop = Parameter(Ratio, default=_physics.ABSORPTION_THERMAL_COP, gt=0)
        self.auxiliary_power_ratio = Parameter(Ratio)
        self.minimum_driving_temperature = Parameter(
            Temperature, default=_physics.ABSORPTION_MINIMUM_DRIVING_TEMPERATURE
        )

        # Inlets
        self.generator_in = Inlet(Stream, kind="hot_water")
        self.chilled_in = Inlet(Stream, kind="chilled_water")
        self.cooling_in = Inlet(Stream, kind="hot_water")
        self.power_in = Inlet(Power, kind="electricity")

        # Controls
        self.temperature_setpoint = Control(Temperature)

        # Outputs
        self.cop = Output(Ratio | None)
        self.driving_temperature_difference = Output(TemperatureDifference)
        self.is_capped = Output(bool)

        # Outlets
        self.generator_out = Outlet(Stream, kind="hot_water")
        self.chilled_out = Outlet(Stream, kind="chilled_water")
        self.cooling_out = Outlet(Stream, kind="hot_water")

    def forward(self, inlets):
        """Cool the generator and chilled circuits and heat the cooling circuit."""

        # Outlets
        values = self._performance(inlets)
        generator_out, chilled_out, cooling_out = _sorption.outlet_streams(inlets, values)

        # Outputs
        _sorption.assign_outputs(self, inlets, (generator_out, chilled_out, cooling_out), values)

        outlets = dict(
            generator_out=generator_out,
            chilled_out=chilled_out,
            cooling_out=cooling_out,
            power_in=values["electricity"],
        )
        return outlets

    def capex(self, finance):
        """Return the cost of the absorption unit from its capacity."""
        return self.capex_of(finance, self.capacity)

    def _performance(self, inlets):
        """Return the duties [W], COP and outlet temperatures [K] of one operating point."""
        generator_in, chilled_in, cooling_in = (
            inlets.generator_in,
            inlets.chilled_in,
            inlets.cooling_in,
        )
        rates = _sorption.rates(self.path, inlets)
        if self.mode == "chiller":
            useful_ratio = 1.0
            requested = heat_transfer.setpoint_duty(
                rates["chilled_in"], chilled_in.T - self.temperature_setpoint
            )
        else:
            useful_ratio = _physics.sorption_rejection_ratio(
                self.thermal_cop, self.auxiliary_power_ratio
            )
            requested = heat_transfer.setpoint_duty(
                rates["cooling_in"], self.temperature_setpoint - cooling_in.T
            )
        evaporator, is_capped = _physics.sorption_delivered_duty(
            requested, self._available_duty(inlets, rates), self.capacity, useful_ratio
        )
        generator, electricity, rejection = _physics.sorption_duties(
            evaporator, self.thermal_cop, self.auxiliary_power_ratio
        )
        useful = evaporator if self.mode == "chiller" else rejection
        return {
            "cop": ops.where(
                evaporator != 0, refrigeration.coefficient_of_performance(useful, generator), None
            ),
            "useful_duty": useful,
            "generator_duty": generator,
            "evaporator_duty": evaporator,
            "absorber_condenser_duty": rejection,
            "electricity": electricity,
            "is_capped": is_capped,
            "generator_out_T": _sorption.outlet_T(generator_in, rates["generator_in"], -generator),
            "chilled_out_T": _sorption.outlet_T(chilled_in, rates["chilled_in"], -evaporator),
            "cooling_out_T": _sorption.outlet_T(cooling_in, rates["cooling_in"], rejection),
        }

    def _available_duty(self, inlets, rates):
        """Return the evaporator duty [W] the characteristic equation allows at these inlets."""
        capacity = _sorption.evaporator_capacity(self, inlets, rates)
        return ops.where(inlets.generator_in.T < self.minimum_driving_temperature, 0.0, capacity)
