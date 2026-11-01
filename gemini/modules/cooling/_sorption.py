"""What the absorption and adsorption machines share: circuit rates, outlets, outputs, capacity."""

from gemini import ops
from gemini.modules._utils.flow import require_forward
from gemini.modules.cooling import _physics
from gemini.physics import heat_transfer
from gemini.types.flows import Stream


def rates(path, inlets):
    """Return each inlet's heat capacity rate m_dot * cp [W/K]; reject negative flow."""
    rate_of = {}
    for port, stream in inlets.items():
        if not isinstance(stream, Stream):
            continue
        require_forward(path, f"{port}.m_dot", stream.m_dot)
        rate_of[port] = stream.heat_capacity_rate()
    return rate_of


def outlet_T(stream, rate, duty):
    """Return the outlet temperature [K] after adding ``duty`` [W] at capacity rate ``rate``."""
    return ops.where(duty == 0, stream.T, stream.T + heat_transfer.temperature_change(duty, rate))


def outlet_streams(inlets, values):
    """Return the generator, chilled and cooling streams at ``values``."""
    return (
        inlets.generator_in.with_(T=values["generator_out_T"]),
        inlets.chilled_in.with_(T=values["chilled_out_T"]),
        inlets.cooling_in.with_(T=values["cooling_out_T"]),
    )


def assign_outputs(module, inlets, outlets, values):
    """Set the outputs of the machine: its COP, whether it is capped and the driving difference.

    ``outlets`` are the generator, chilled and cooling streams that leave the machine.
    """
    generator_out, chilled_out, cooling_out = outlets
    module.cop = values["cop"]
    module.is_capped = values["is_capped"]
    module.driving_temperature_difference = _physics.characteristic_temperature_difference(
        heat_transfer.mean_temperature(inlets.generator_in.T, generator_out.T),
        heat_transfer.mean_temperature(inlets.cooling_in.T, cooling_out.T),
        heat_transfer.mean_temperature(inlets.chilled_in.T, chilled_out.T),
        module.rejection_coefficient,
        module.evaporator_coefficient,
    )


def evaporator_capacity(module, inlets, rates):
    """Return the evaporator duty [W] of the characteristic equation at these inlets."""
    return _physics.sorption_evaporator_capacity(
        inlets.generator_in.T,
        inlets.cooling_in.T,
        inlets.chilled_in.T,
        rates["generator_in"],
        rates["cooling_in"],
        rates["chilled_in"],
        slope=module.characteristic_slope,
        minimum_driving_difference=module.minimum_driving_difference,
        rejection_coefficient=module.rejection_coefficient,
        evaporator_coefficient=module.evaporator_coefficient,
        thermal_cop=module.thermal_cop,
        auxiliary_power_ratio=module.auxiliary_power_ratio,
    )
