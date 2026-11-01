"""Building or process cooling demand on a chilled-water circuit, with latent load."""

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.modules.declarations import Boundary, Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import heat_transfer, psychrometrics
from gemini.types import (
    WATER,
    Fraction,
    MassFlow,
    Power,
    Pressure,
    Stream,
    Temperature,
    TemperatureDifference,
)


class CoolingGrid(Module):
    """Cooling consumer that warms the chilled-water supply by the sensible and latent loads.

    The circuit's mass flow is imposed by the supply stream, so the return temperature follows
    from the heat taken from the building:

    T_limit = min(maximum_return_temperature, indoor_temperature)
    Q_available = m_dot cp max(0, T_limit - T_supply)
    Q_sensible = min(sensible_cooling_demand, Q_available)
    Q_latent = min(latent_cooling_demand, Q_available - Q_sensible)  if T_supply <= T_dew - margin
    Q_latent = 0                                                     otherwise
    T_return = T_supply + (Q_sensible + Q_latent) / (m_dot cp)

    The dew point ``T_dew`` of the indoor air comes from ``psychrometrics.dew_point`` (Hyland and
    Wexler 1983 saturation pressure, ASHRAE Handbook - Fundamentals 2017, chapter 1). Moisture
    condenses on a coil only when its surface is below the dew point; the coil surface is warmer
    than the water, so dehumidification needs a supply at least ``dew_point_margin`` below the
    dew point (the coil apparatus dew point approach, ASHRAE Handbook - HVAC Systems and
    Equipment 2020, chapter 23, "Air-cooling and dehumidifying coils"). Otherwise the latent
    load is unmet, as with chilled beams or radiant ceilings run above the dew point. The water
    cannot return warmer than the indoor air that heats it, hence the indoor temperature in
    ``T_limit``.

    When the available capacity is short, the sensible load is served first: room thermostats
    control the dry-bulb temperature and humidity drifts. The latent heat (condensation of the
    removed vapour) enters the water like the sensible heat, so the heat on its ports is their sum;
    the condensate drains on the air side and the water mass flow is unchanged.

    On a closed loop ``return_temperature``, ``return_pressure`` and the control ``flow`` set the
    return water: ``return_out`` is offered before the other modules run, and the loads met are
    those the rise of the water up to the return temperature takes. Bind the demand to
    a ``gm.data.from_csv`` column. Without them the return follows from the loads, as in a
    substation. Unmet loads are reported, never an error.

    Simplifications: steady state, constant fluid properties (the inlet ``cp``), no pressure
    drop, no coil characteristic beyond the return limit and the dew-point test, and loads
    given as boundaries instead of computed from the air side. The model conserves mass and is
    first-law closed: the sensible enthalpy rise of the stream equals the heat on its ports. Valid
    for chilled water or glycol with nonnegative flow and indoor air from 173.15 K to 473.15 K
    with a relative humidity in (0, 1].
    """

    def __init__(self):
        """Declare the consumer's limits, indoor conditions, loads and absorbed heat."""
        super().__init__()
        self.fluid = WATER

        # Parameters
        self.maximum_return_temperature = Parameter(Temperature | None, default=None)
        self.dew_point_margin = Parameter(TemperatureDifference, ge=0)
        self.return_temperature = Parameter(
            Temperature | None,
            default=None,
            structural=True,
            case="demand.cooling.return_temperature",
        )
        self.maximum_supply_temperature = Parameter(
            Temperature | None, default=None, case="demand.cooling.supply_temperature"
        )
        self.return_pressure = Parameter(Pressure | None, default=None)

        # Inlets
        self.supply_in = Inlet(Stream, kind="chilled_water")

        # Controls
        self.flow = Control(MassFlow | None, default=None, ge=0)

        # Boundaries
        self.sensible_cooling_demand = Boundary(Power, ge=0)
        self.latent_cooling_demand = Boundary(Power, ge=0)
        self.indoor_temperature = Boundary(Temperature)
        self.indoor_relative_humidity = Boundary(Fraction, gt=0)

        # Outputs
        self.unmet_sensible = Output(Power)
        self.unmet_latent = Output(Power)
        self.surplus = Output(Power)
        self.dew_point = Output(Temperature)
        self.is_unmet = Output(bool)

        # Outlets
        self.return_out = Outlet(Stream, kind="chilled_water", offered=True)

    def forward(self, inlets):
        """Return the supply stream warmed by the absorbed building heat."""

        # Outlets
        supply_in = inlets.supply_in
        if self.return_temperature is None:
            sensible, latent = self._met_loads(supply_in)
            return_out = supply_in.with_(T=self._warmed_temperature(supply_in, sensible + latent))
            surplus = 0.0
        else:
            return_out = self._offer(inlets)["return_out"]
            sensible, latent = self._met_loads(supply_in, return_out)
            surplus = self._available(supply_in, return_out) - sensible - latent

        # Outputs
        self.unmet_sensible = self.sensible_cooling_demand - sensible
        self.unmet_latent = self.latent_cooling_demand - latent
        self.surplus = surplus
        self.dew_point = psychrometrics.dew_point(
            self.indoor_temperature, self.indoor_relative_humidity
        )
        self.is_unmet = ops.logical_or(self.unmet_sensible > 0, self.unmet_latent > 0)

        outlets = dict(return_out=return_out)
        return outlets

    def _loop_start(self, port, entering):
        """Start a building loop at the warmest return temperature."""
        return min(self.maximum_return_temperature, self.indoor_temperature)

    def _offers(self):
        """Offer only on a closed loop; otherwise the outlet follows from the inlet."""
        return self.return_temperature is not None

    def _offer(self, inlets):
        """Offer the return water of a closed loop, at the fixed temperature and the given flow."""
        if self.return_temperature is None or self.return_pressure is None or self.flow is None:
            raise ValidationError(
                f"{self.path}: return_temperature, return_pressure and flow are needed to offer "
                "return_out; expected all three on a closed loop",
                code="invalid_design",
            )
        offered = Stream(
            m_dot=self.flow, T=self.return_temperature, p=self.return_pressure, fluid=self.fluid
        )
        return {"return_out": offered}

    def _warmed_temperature(self, supply_in, absorbed):
        """Return the return temperature [K] after the building gave ``absorbed`` [W] to it."""
        warmed = ops.minimum(
            self._return_limit(),
            supply_in.T
            + heat_transfer.temperature_change(absorbed, supply_in.heat_capacity_rate()),
        )
        return ops.where(absorbed == 0, supply_in.T, warmed)

    def _available(self, supply_in, return_out=None):
        """Return the cold [W] the water takes up to its return limit."""
        return heat_transfer.setpoint_duty(
            supply_in.heat_capacity_rate(), self._return_limit(return_out) - supply_in.T
        )

    def _met_loads(self, supply_in, return_out=None):
        """Return the met sensible and latent loads [W]; the rise of the water on a closed loop."""
        ops.check(
            supply_in.m_dot >= 0,
            PhysicsError,
            "{path}: supply_in.m_dot = {m_dot} kg/s; expected >= 0",
            path=self.path,
            m_dot=supply_in.m_dot,
        )
        available = self._available(supply_in, return_out)
        dew_point = psychrometrics.dew_point(self.indoor_temperature, self.indoor_relative_humidity)
        dry = supply_in.T > dew_point - self.dew_point_margin
        return heat_transfer.sensible_latent_loads(
            available, self.sensible_cooling_demand, self.latent_cooling_demand, dry
        )

    def _return_limit(self, return_out=None):
        """Return the warmest return temperature [K]: the fixed one, the parameter or indoor air."""
        if self.return_temperature is not None and return_out is not None:
            return return_out.T
        return ops.minimum(self.maximum_return_temperature, self.indoor_temperature)
