"""Configuration helpers for the plant composites, shared as fixtures."""

import pytest

CP = 4217.4
"""Heat capacity [J/kg/K] of the default fluid."""


def configure_heating_substation(substation, demand=1.5e5):
    """Fill a heating substation: 3 kg/s building loop, 20 kW/K exchanger, 30 degC floor."""
    substation.pump.set_params(
        "", {"flow": 3.0, "pressure_rise": 5e4, "loop_pressure": 3e5, "efficiency": 0.55}
    )
    substation.valve.set_params(
        "",
        {
            "flow_coefficient": {"value": 20, "unit": "m3/h/bar^0.5"},
            "characteristic": "equal_percentage",
            "rangeability": 50.0,
        },
    )
    substation.valve.opening = 0.8
    substation.heat_exchanger.set_params(
        "",
        {
            "thermal_conductance": 2e4,
            "hot_nominal_pressure_drop": 2e4,
            "cold_nominal_pressure_drop": 2e4,
            "hot_nominal_mass_flow": 2,
            "cold_nominal_mass_flow": 3,
            "arrangement": "counterflow",
            "fouling_threshold": 0.15,
        },
    )
    substation.consumer.set_params("", {"minimum_return_temperature": 303.15})
    substation.consumer.heat_demand = demand
    return substation


def configure_cooling_substation(substation, sensible=6e4, latent=1e4):
    """Fill a cooling substation: 4 kg/s building loop, 30 kW/K exchanger, 18 degC return limit."""
    substation.pump.set_params(
        "", {"flow": 4.0, "pressure_rise": 5e4, "loop_pressure": 3e5, "efficiency": 0.55}
    )
    substation.valve.set_params(
        "",
        {
            "flow_coefficient": {"value": 20, "unit": "m3/h/bar^0.5"},
            "characteristic": "equal_percentage",
            "rangeability": 50.0,
        },
    )
    substation.valve.opening = 1.0
    substation.heat_exchanger.set_params(
        "",
        {
            "thermal_conductance": 3e4,
            "hot_nominal_pressure_drop": 2e4,
            "cold_nominal_pressure_drop": 2e4,
            "hot_nominal_mass_flow": 4,
            "cold_nominal_mass_flow": 3,
            "arrangement": "counterflow",
            "fouling_threshold": 0.15,
        },
    )
    substation.consumer.set_params(
        "", {"maximum_return_temperature": 291.15, "dew_point_margin": 1.0}
    )
    substation._set_inputs(
        {
            "consumer.sensible_cooling_demand": sensible,
            "consumer.latent_cooling_demand": latent,
            "consumer.indoor_temperature": 297.15,
            "consumer.indoor_relative_humidity": 0.5,
        }
    )
    return substation


def configure_circulation_pump(pump):
    """Fill a circulation pump: 4 bar shut-off head, 75 % efficiency at 4 l/s, 90 % motor."""
    pump.set_params(
        "",
        {
            "head_coefficients": [4e5, 0.0, -1e9],
            "rated_frequency": 50,
            "best_efficiency": 0.75,
            "best_efficiency_flow": 0.004,
            "motor_efficiency": 0.9,
        },
    )
    pump.frequency = 50
    return pump


def configure_pipe(pipe):
    """Fill a 500 m DN100 pipe with U = 1 W/m2/K in 10 degC ground."""
    pipe.set_params(
        "",
        {
            "length": 500,
            "inner_diameter": 0.1,
            "elevation_change": 0,
            "heat_transfer_coefficient": 1.0,
            "roughness": 4.5e-5,
        },
    )
    return pipe


def configure_network(network, configure_substation):
    """Fill a network with equal shares for every substation."""
    configure_circulation_pump(network.pump)
    configure_pipe(network.supply_pipe)
    configure_pipe(network.return_pipe)
    count = len(network.substations)
    for index, splitter in enumerate(network.splitters):
        splitter.split_fraction = 1 / (count - index)
    for substation in network.substations:
        configure_substation(substation)
    return network


@pytest.fixture
def plants():
    """Return the configuration helpers of this folder by name."""
    return dict(
        heating_substation=configure_heating_substation,
        cooling_substation=configure_cooling_substation,
        circulation_pump=configure_circulation_pump,
        pipe=configure_pipe,
        network=configure_network,
    )
