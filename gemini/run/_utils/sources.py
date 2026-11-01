"""The marginal cost of each heat and cold source of a plant at each step of a schedule.

A source costs ``price / efficiency + co2_price * emission`` per joule delivered, with the
efficiency of its module at the design values of the step. A price a source needs and the
assumptions lack raises ``missing_value``.
"""

import math

import numpy as np

from gemini._utils.strings import join_path
from gemini.errors import ValidationError
from gemini.physics import constants, dispatch
from gemini.run._utils import roles


class Costs:
    """The prices of a problem as the schedule reads them, for ``steps`` rows."""

    def __init__(self, assumptions, steps):
        """Keep ``assumptions`` and the number of rows of the demand."""
        self.assumptions = assumptions
        self.steps = steps

    def _price(self, carrier, path):
        """Return the price of ``carrier`` for the source at ``path``; none is ``missing_value``."""
        price = self.assumptions.price(carrier, required=False)
        if price is None:
            raise ValidationError(
                f"schedule: assumptions.prices.{carrier} = missing; expected a price, "
                f"which {path} needs",
                path=f"assumptions.prices.{carrier}",
                code="missing_value",
            )
        return price

    def _cost(self, carrier, path, efficiency, factor):
        """Return the marginal cost per joule delivered by ``path`` drawing ``carrier``."""
        co2 = self.assumptions.co2_cost() or 0.0
        cost = dispatch.marginal_cost(self._price(carrier, path), efficiency, co2, factor)
        return np.broadcast_to(cost, self.steps).astype(float)

    def electric(self, path, efficiency):
        """Return the cost of heat or cold made from grid electricity at ``efficiency``."""
        factor = self.assumptions.emission_factor() or 0.0
        return self._cost("electricity", path, efficiency, factor)

    def gas(self, path, efficiency):
        """Return the cost of heat made from grid gas at ``efficiency``."""
        return self._cost("gas", path, efficiency, dispatch.methane_emission_factor())


def pump_efficiency(doublet, brine_cooling, maximum_flow):
    """Return the heat a doublet gives per joule of pump electricity, at the maximum flow [-].

    Infinite for a pump whose power curve gives no power: its electricity then costs nothing.
    """
    frequency = float(constants.ESP_REFERENCE_FREQUENCY)
    power = doublet.esp.power_function(maximum_flow, frequency) / doublet.esp.motor_efficiency
    fluid = doublet.reservoir.fluid.properties(0, 0)
    heat = maximum_flow * fluid.rho_l * fluid.cp_l * brine_cooling
    return float(heat / power) if power > 0 else math.inf


def heat_pump_cop(module, heating, sink_outlet, source_outlet):
    """Return the COP of a heat pump at design outlet temperatures [K].

    The fraction is the parameter of the module's COP model: ``carnot_fraction``, or
    ``lorenz_fraction`` for a Lorenz machine. A plant states it, or the default of the parameter
    applies, whose source is ``refrigeration.DEFAULT_CARNOT_FRACTION``.

    NOTE(refactor): this is a design estimate at the setpoint and a source outlet. A Lorenz machine
    takes its fraction on the outlet temperatures, because the glides need the simulation.
    """
    fraction = module.lorenz_fraction if module.cop_model == "lorenz" else module.carnot_fraction
    return dispatch.heat_pump_cop(
        heating, fraction, module.minimum_temperature_lift, sink_outlet, source_outlet
    )


def cooler_setpoint(plant, path):
    """Return the supply setpoint [K] of the cooler that takes the condenser heat of ``path``."""
    target = plant.target_of(join_path(path, "sink_out"))
    cooler = target.rpartition(".")[0] if target else None
    name = join_path(cooler or path, "temperature_setpoint")
    setpoint = None if cooler is None else plant.input_value(name)
    if setpoint is None:
        raise ValidationError(
            f"schedule: {name} has no value; expected the setpoint of the cooler of the "
            f"compression chiller {path}, which sets its COP",
            path=name,
            code="invalid_design",
        )
    return setpoint


def drive_cost(heat_costs, thermal_cop):
    """Return the cost of a joule of cold from drive heat at the cheapest heat of the step.

    NOTE(refactor): the heat that drives a chiller is valued at the cheapest heat source of the
    step, because the chiller and the heat sources load together.
    """
    cheapest = np.minimum.reduce(heat_costs) if heat_costs else 0.0
    return cheapest / thermal_cop


def compression_cost(costs, plant, path, module):
    """Return the cost of cold from the compression chiller at ``path``."""
    source = roles.setpoint(plant, path)
    cop = heat_pump_cop(module, False, cooler_setpoint(plant, path), source)
    return costs.electric(path, cop)
