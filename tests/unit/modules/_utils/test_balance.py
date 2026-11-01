"""Typed energy reporting and conservation diagnostics."""

import numpy as np
import pytest

from gemini.modules import Module
from gemini.modules._utils.balance import collect_flows, emissions, energy_balance, mass_balance
from gemini.modules.declarations import Inlet, Outlet
from gemini.modules.grids import GasGrid
from gemini.modules.heating import CHP, Boiler, ElectricBoiler
from gemini.modules.pumps import ESP, InjectionPump
from gemini.types import Power, Stream
from gemini.types.ports import Ports
from gemini.types.results import ModuleResult, Values
from gemini.units import Quantity
from tests.fixtures import si
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import STREAM_FIELDS, assert_close
from tests.fixtures.esp_design import ESP_MODULE
from tests.fixtures.reading import reading

GRID_GAS = with_values(GasGrid())._offered()["gas_out"]


class Radiator(Module):
    """Give the stream's heat to the surroundings."""

    def __init__(self):
        """Declare the ports."""
        super().__init__()

        # Inlets
        self.supply_in = Inlet(Stream)

        # Outlets
        self.return_out = Outlet(Stream)
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Cool the stream by 10 K."""

        # Outlets
        return_out = inlets.supply_in.with_(T=inlets.supply_in.T - 10)

        loss_out = inlets.supply_in.m_dot * 4217.4 * 10

        outlets = dict(return_out=return_out, loss_out=loss_out)
        return outlets


def boiler_of(fuel):
    """Return a boiler of ``fuel`` and the extra inlets a call of it takes."""
    if fuel == "electric":
        return (
            ElectricBoiler().set_params("", {"capacity": Quantity(1e6, "W"), "efficiency": 0.9}),
            {},
        )
    return Boiler().set_params("", {"capacity": Quantity(1e6, "W"), "efficiency": 0.9}), {
        "fuel_in": GRID_GAS
    }


@pytest.mark.parametrize("fuel", ["electric", "gas"])
def test_boiler_balance(fuel):
    """Electric and gas boilers conserve total modeled energy."""
    boiler, gas = boiler_of(fuel)
    result = boiler(
        fluid_in=Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(300, "K"), p=Quantity(1e6, "Pa")),
        temperature_setpoint=320,
        **gas,
    )
    assert mass_balance(boiler, result)["residual"] == 0
    assert energy_balance(boiler, result)["relative_residual"] < 1e-12
    assert collect_flows(result)["electricity" if fuel == "electric" else "fuel"] > 0


def test_unresolved_pump_work():
    """Isothermal pump electricity remains explicit unresolved work."""
    pump = InjectionPump().set_params("", {"pump_type": "unspecified", "efficiency": 0.8})
    result = pump(
        fluid_in=Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(300, "K"), p=Quantity(1e6, "Pa")),
        pressure_setpoint=2e6,
    )
    balance = energy_balance(pump, result)
    assert balance["unresolved_power"] == pytest.approx(result.outputs.power)
    assert balance["relative_thermal_residual"] < 1e-12


def test_esp_motor_efficiency_does_not_change_shaft_power():
    """Motor efficiency changes grid draw while shaft prediction stays fixed."""
    pump = si.set_params(
        ESP(),
        "",
        ESP_MODULE
        | {
            "stage_count": 10,
            "head_coefficients": [10, 0, 0, 0, 0, 0],
            "power_coefficients": [1, 0, 0, 0, 0, 0],
        },
    )
    inlet = Stream(m_dot=Quantity(30, "kg/s"), T=Quantity(300, "K"), p=Quantity(1e6, "Pa"))
    first = pump(frequency=60, fluid_in=inlet)
    pump.motor_efficiency = 0.5
    second = pump(frequency=60, fluid_in=inlet)
    assert second.outputs.power == first.outputs.power
    assert reading(second).electricity == 2 * first.outputs.power


def test_heat_leaving_through_a_port_closes_the_balance():
    """Heat that leaves through a port is an energy outflow, not a residual."""
    radiator = Radiator()
    result = radiator(
        supply_in=Stream(m_dot=Quantity(2, "kg/s"), T=Quantity(350, "K"), p=Quantity(1e6, "Pa"))
    )
    balance = energy_balance(radiator, result)
    assert balance["heat_loss"] == pytest.approx(2 * 4217.4 * 10)
    assert balance["relative_residual"] < 1e-12


GAS_FACTOR = 56.6 / 1e9
"""Natural-gas CO2 factor [kg/J] of the upstream GEMINI doublet example: 56.6 kg/GJ."""

GRID_FACTOR = 0.3 / 3.6e6
"""Grid-electricity CO2 factor [kg/J] of the upstream GEMINI doublet example: 0.3 kg/kWh."""


class GasHeatedInjection(Module):
    """Heat a return stream with a CHP and a boiler, then pump it into an injector."""

    def __init__(self):
        """Declare the three leaves and the plant ports."""
        super().__init__()

        # Modules
        self.chp = CHP().set_params(
            "",
            {
                "electric_capacity": Quantity(1e5, "W"),
                "electric_efficiency": 0.4,
                "thermal_efficiency": 0.45,
                "maximum_outlet_temperature": Quantity(363.15, "K"),
            },
        )
        self.boiler = Boiler().set_params("", {"capacity": Quantity(1e6, "W"), "efficiency": 0.9})
        self.pump = InjectionPump().set_params("", {"pump_type": "unspecified", "efficiency": 0.8})

        # Inlets
        self.return_in = Inlet(Stream)

        # Outlets
        self.injected = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream through CHP, boiler and pump in flow order."""

        # Modules
        heated = self.chp(fluid_in=inlets.return_in, fuel_in=GRID_GAS).outlets.fluid_out
        topped = self.boiler(fluid_in=heated, fuel_in=GRID_GAS).outlets.fluid_out
        pumped = self.pump(fluid_in=topped)

        # Outlets
        injected = pumped.outlets.fluid_out

        outlets = dict(injected=injected)
        return outlets


@pytest.mark.parametrize("load", [0.2, 1.0])
def test_emissions_charge_fuel_and_net_grid_electricity(load):
    """Fuel is charged in full; CHP electricity offsets the 60 kW pump before the grid."""
    plant = GasHeatedInjection()
    plant._set_inputs(
        {
            "chp.load_fraction": load,
            "boiler.temperature_setpoint": 343.15,
            "pump.pressure_setpoint": 50e5,
        }
    )
    result = plant(
        return_in=Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(313.15, "K"), p=Quantity(2e5, "Pa"))
    )
    flows = collect_flows(result)
    pump_power = 10 / 1000 * 48e5 / 0.8
    assert flows["electricity"] == pytest.approx(pump_power)
    assert flows["electricity_generated"] == pytest.approx(load * 1e5)
    grid = {0.2: pump_power - 2e4, 1.0: 0.0}[load]
    expected = flows["fuel"] * GAS_FACTOR + grid * GRID_FACTOR
    assert emissions(result, GAS_FACTOR, GRID_FACTOR) == pytest.approx(expected, rel=1e-12)


def test_emissions_without_energy_outputs_are_zero():
    """A leaf that burns and draws nothing emits nothing."""
    result = Boiler().set_params("", {"capacity": Quantity(1e6, "W"), "efficiency": 0.9})(
        fluid_in=Stream(m_dot=Quantity(10, "kg/s"), T=Quantity(350, "K"), p=Quantity(2e5, "Pa")),
        fuel_in=GRID_GAS,
        temperature_setpoint=340,
    )
    assert emissions(result, GAS_FACTOR, GRID_FACTOR) == 0


def _stack_streams(streams):
    if not isinstance(streams[0], Stream):
        return np.array(streams)
    return Stream._si(
        **{field: np.array([getattr(s, field) for s in streams]) for field in STREAM_FIELDS},
        fluid=streams[0].fluid,
    )


def _stack_results(results):
    """Return one result whose outputs and streams are arrays over the rows of ``results``."""
    first = results[0]
    return ModuleResult(
        outputs=Values(
            {name: np.array([r.outputs[name] for r in results]) for name in first.outputs}
        ),
        inlets=Ports({n: _stack_streams([r.inlets[n] for r in results]) for n in first.inlets}),
        outlets=Ports({n: _stack_streams([r.outlets[n] for r in results]) for n in first.outlets}),
        inputs={name: np.array([r.inputs[name] for r in results]) for name in first.inputs},
    )


def _assert_balances_match(module, results, expected_keys):
    stacked = _stack_results(results)
    for audit in (mass_balance, energy_balance):
        per_row = [audit(module, result) for result in results]
        together = audit(module, stacked)
        for key in expected_keys[audit]:
            assert_close(together[key], [row[key] for row in per_row], f"{audit.__name__}.{key}")
    flows = [collect_flows(result) for result in results]
    for key, values in collect_flows(stacked).items():
        assert_close(values, [row[key] for row in flows], key)
    per_row = [emissions(result, 0.2, 0.4) for result in results]
    assert_close(emissions(stacked, 0.2, 0.4), per_row, "emissions")


BALANCE_KEYS = {
    mass_balance: ("in", "out", "residual", "relative_residual"),
    energy_balance: ("in", "out", "residual", "relative_residual", "thermal_residual", "losses"),
}


@pytest.mark.parametrize("fuel", ["electric", "gas"])
def test_balances_match_on_stacked_boiler_results(fuel):
    """Audits and emissions on array-valued results equal the audits per row."""
    boiler, gas = boiler_of(fuel)
    results = [
        boiler(
            fluid_in=Stream(
                m_dot=Quantity(m_dot, "kg/s"), T=Quantity(300, "K"), p=Quantity(1e6, "Pa")
            ),
            temperature_setpoint=setpoint,
            **gas,
        )
        for m_dot, setpoint in [(10, 320), (2, 310), (0.5, 300)]
    ]
    _assert_balances_match(boiler, results, BALANCE_KEYS)


def test_balances_match_on_stacked_radiator_results():
    """Heat on a port, with a residual of either sign, audits per row."""
    radiator = Radiator()
    results = [
        radiator(
            supply_in=Stream(
                m_dot=Quantity(m_dot, "kg/s"), T=Quantity(350, "K"), p=Quantity(3e5, "Pa")
            )
        )
        for m_dot in (0.0, 1.5, 12.0)
    ]
    _assert_balances_match(radiator, results, BALANCE_KEYS)
