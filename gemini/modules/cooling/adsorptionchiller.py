"""Silica-gel/water adsorption chiller driven by low-temperature hot water."""

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
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


class AdsorptionChiller(Equipment, Module):
    """Silica-gel/water adsorption chiller driven by hot water of 55 to 90 degC.

    Three circuits as in ``AbsorptionUnit``: ``generator_in`` carries the driving hot water that
    desorbs the bed, ``chilled_in`` the evaporator water and ``cooling_in`` the cooling water of
    the adsorbing bed and the condenser. The machine is a chiller only: ``temperature_setpoint``
    is the chilled outlet temperature and ``capacity`` caps the evaporator duty.

    Adsorption chillers run in batch cycles (two or more beds switching between adsorption and
    desorption); the model represents cycle-averaged duties over a step much longer than the
    cycle (minutes), so it suits 15-minute or hourly steps. Its characteristic map is the
    characteristic equation of the sorption machine, Q_E = s * (ddt - ddt_min) with
    ddt = t_G - a * t_AC + r * t_E at the mean circuit temperatures in degC, solved in closed form
    from the inlet temperatures (``_physics.sorption_evaporator_capacity``); its own
    coefficients are fitted to the adsorption machine. The delivered evaporator duty is the
    smallest of that, the setpoint request and the capacity. Q_G = Q_E / thermal_cop,
    electricity (pumps, valves and controls) is auxiliary_power_ratio * Q_E and
    Q_AC = Q_G + Q_E + electricity, so the model is first-law closed.
    ``is_capped`` is true whenever the delivered duty falls short of the setpoint request,
    whether capacity, the characteristic equation or the driving temperature limits it.

    Assumptions: constant cycle-averaged thermal COP, 0.55 by default: Wang and Oliveira (2006),
    "Adsorption refrigeration - an efficient way to make good use of waste heat and solar
    energy", Progress in Energy and Combustion Science 32, 424-458, report about 0.5 to 0.6 for
    commercial silica-gel/water chillers. No pressure loss, casing heat loss or cycle dynamics;
    constant liquid heat capacity per stream. Validity: driving hot water from
    ``minimum_driving_temperature`` (55 degC; below it the chiller is off) to
    ``maximum_driving_temperature`` (90 degC; above it the map is not valid and the call raises
    ``PhysicsError``), cooling water of 20 to 35 degC, chilled water above 5 degC, circuit
    flows near the rated flows of the fit.
    """

    equipment_kind = "adsorption_chiller"

    def __init__(self):
        """Declare adsorption chiller design data, its three circuits and performance."""
        super().__init__()
        # Parameters
        self.capacity = Parameter(Power, gt=0, description="Largest evaporator duty")
        self.characteristic_slope = Parameter(
            ThermalConductance,
            gt=0,
            description=(
                "Slope of the duty against the driving temperature difference in the characteristic"
                " map"
            ),
        )
        self.minimum_driving_difference = Parameter(
            TemperatureDifference,
            description=(
                "Smallest driving-to-chilled temperature difference at which the machine delivers"
            ),
        )
        self.rejection_coefficient = Parameter(
            Dimensionless,
            description="Slope of the heat rejection relation of the characteristic map",
        )
        self.evaporator_coefficient = Parameter(
            Dimensionless,
            description="Offset of the evaporator duty relation of the characteristic map",
        )
        self.thermal_cop = Parameter(
            Ratio,
            default=_physics.ADSORPTION_THERMAL_COP,
            gt=0,
            description="Thermal coefficient of performance: useful duty over driving heat",
        )
        self.auxiliary_power_ratio = Parameter(
            Ratio, description="Auxiliary electric power as a share of the useful duty"
        )
        self.minimum_driving_temperature = Parameter(
            Temperature,
            default=_physics.ADSORPTION_MINIMUM_DRIVING_TEMPERATURE,
            description="Lowest driving hot-water temperature at which the machine operates",
        )
        self.maximum_driving_temperature = Parameter(
            Temperature,
            default=_physics.ADSORPTION_MAXIMUM_DRIVING_TEMPERATURE,
            description="Highest driving hot-water temperature the machine accepts",
        )

        # Inlets
        self.generator_in = Inlet(Stream, kind="hot_water")
        self.chilled_in = Inlet(Stream, kind="chilled_water")
        self.cooling_in = Inlet(Stream, kind="hot_water")
        self.power_in = Inlet(Power, kind="electricity")

        # Controls
        self.temperature_setpoint = Control(
            Temperature, description="Outlet temperature the unit regulates the stream to"
        )

        # Outputs
        self.cop = Output(
            Ratio | None,
            description=(
                "Coefficient of performance: useful duty over driving energy; empty when the unit "
                "is off"
            ),
        )
        self.driving_temperature_difference = Output(
            TemperatureDifference,
            description="Driving hot-water temperature above its minimum operating temperature",
        )
        self.is_capped = Output(bool, description="True when the duty was limited by the capacity")

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
        """Return the cost of the adsorption chiller from its capacity."""
        return self.capex_of(finance, self.capacity)

    def _performance(self, inlets):
        """Return the duties [W], COP and outlet temperatures [K] of one operating point."""
        generator_in, chilled_in, cooling_in = (
            inlets.generator_in,
            inlets.chilled_in,
            inlets.cooling_in,
        )
        rates = _sorption.rates(self.path, inlets)
        requested = heat_transfer.setpoint_duty(
            rates["chilled_in"], chilled_in.T - self.temperature_setpoint
        )
        evaporator, is_capped = _physics.sorption_delivered_duty(
            requested, self._available_duty(inlets, rates), self.capacity, 1
        )
        generator, electricity, rejection = _physics.sorption_duties(
            evaporator, self.thermal_cop, self.auxiliary_power_ratio
        )
        return {
            "cop": ops.where(
                evaporator != 0,
                refrigeration.coefficient_of_performance(evaporator, generator),
                None,
            ),
            "generator_duty": generator,
            "evaporator_duty": evaporator,
            "adsorber_condenser_duty": rejection,
            "electricity": electricity,
            "is_capped": is_capped,
            "generator_out_T": _sorption.outlet_T(generator_in, rates["generator_in"], -generator),
            "chilled_out_T": _sorption.outlet_T(chilled_in, rates["chilled_in"], -evaporator),
            "cooling_out_T": _sorption.outlet_T(cooling_in, rates["cooling_in"], rejection),
        }

    def _available_duty(self, inlets, rates):
        """Return the evaporator duty [W] the characteristic map allows at these inlets."""
        driving_T = inlets.generator_in.T
        ops.check(
            self.minimum_driving_temperature < self.maximum_driving_temperature,
            ValidationError,
            "{path}: minimum_driving_temperature = {minimum} K; expected below "
            "maximum_driving_temperature = {maximum} K",
            path=self.path,
            minimum=self.minimum_driving_temperature,
            maximum=self.maximum_driving_temperature,
            code="invalid_design",
        )
        ops.check(
            ops.logical_or(
                inlets.generator_in.m_dot == 0, driving_T <= self.maximum_driving_temperature
            ),
            PhysicsError,
            "{path}: generator_in.T = {driving_T} K; expected at most "
            "maximum_driving_temperature = {maximum} K",
            path=self.path,
            driving_T=driving_T,
            maximum=self.maximum_driving_temperature,
        )
        capacity = _sorption.evaporator_capacity(self, inlets, rates)
        return ops.where(driving_T < self.minimum_driving_temperature, 0.0, capacity)
