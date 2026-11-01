"""ATES plant: free cooling while charging, heat pump while discharging, steps and balances."""

import pytest

import gemini as gm
from gemini.modules import Module, energy_balance, mass_balance
from gemini.modules.declarations import Inlet, Outlet, Output
from gemini.plants import ATESPlant
from gemini.types import Stream
from tests.fixtures.balance import assert_plant_closes
from tests.fixtures.designs import with_values
from tests.fixtures.reading import reading

CP = 4217.4
HOUR = 3600.0
SUMMER = Stream(
    m_dot=gm.units.Quantity(40.0, "kg/s"),
    T=gm.units.Quantity(290.15, "K"),
    p=gm.units.Quantity(3e5, "Pa"),
)
WINTER = SUMMER.with_(T=303.15)


def _season(plant, mode):
    """Command the storage and the two valves together."""
    plant.storage.mode = mode
    fraction = 1.0 if mode == "discharge" else 0.0
    plant.source_valve.split_fraction = fraction
    plant.load_valve.split_fraction = fraction


def _plant(mode="charge"):
    """Return a 30 kg/s ATES plant with a 1 MW/K exchanger and a 2 MW heat pump."""
    plant = with_values(ATESPlant())
    plant.storage.groundwater_flow = 30.0
    plant.storage.set_params(
        "",
        {
            "groundwater_pressure": gm.units.Quantity(3e5, "Pa"),
            "aquifer_temperature": gm.units.Quantity(284.15, "K"),
            "aquifer_thickness": gm.units.Quantity(30, "m"),
            "porosity": 0.3,
            "rock_volumetric_heat_capacity": gm.units.Quantity(2.0e6, "J/m3/K"),
            "ground_conductivity": gm.units.Quantity(2.5, "W/m/K"),
        },
    )
    _season(plant, mode)
    plant.pump.set_params(
        "",
        {
            "head_coefficients": [3e5, 0.0, -1e8],
            "rated_frequency": gm.units.Quantity(50, "Hz"),
            "best_efficiency": 0.7,
            "best_efficiency_flow": gm.units.Quantity(0.03, "m3/s"),
            "motor_efficiency": 0.9,
        },
    )
    plant.pump.frequency = 50
    plant.heat_exchanger.set_params(
        "",
        {
            "thermal_conductance": gm.units.Quantity(1e6, "W/K"),
            "hot_nominal_pressure_drop": gm.units.Quantity(3e4, "Pa"),
            "cold_nominal_pressure_drop": gm.units.Quantity(3e4, "Pa"),
            "hot_nominal_mass_flow": gm.units.Quantity(40, "kg/s"),
            "cold_nominal_mass_flow": gm.units.Quantity(30, "kg/s"),
        },
    )
    plant.heat_pump.set_params("", {"mode": "heating", "capacity": gm.units.Quantity(2e6, "W")})
    plant.heat_pump.temperature_setpoint = 313.15
    return plant


def _check_balances(plant, result):
    """Check that the audit closes except for the pump's flow work and that mass is conserved."""
    audit = energy_balance(plant, result)
    hydraulic = result.children["pump"].outputs.hydraulic_power
    assert abs(audit["residual"] - hydraulic) / audit["in"] < 1e-12
    assert mass_balance(plant, result)["residual"] == 0
    assert_plant_closes(plant, result)


def test_charge_cools_the_building_with_native_groundwater():
    """Empty stores produce at the aquifer temperature; the exchanger cools the building."""
    plant = _plant()
    result = plant(return_in=SUMMER)
    exchanger = result.children["heat_exchanger"]
    groundwater = exchanger.inlets.cold_in
    assert result.children["storage"].outlets.production_out.T == 284.15 and groundwater.T > 284.15
    assert result.outlets.supply_out == exchanger.outlets.hot_out
    assert result.outlets.supply_out.T < SUMMER.T
    storage = result.children["storage"]
    assert storage.inlets.injection_in.T == exchanger.outlets.cold_out.T
    assert storage.outlets.production_out == result.children["pump"].inlets.fluid_in
    assert result.children["heat_pump"].inlets.power_in == 0
    assert result.children["storage"].outputs.heat_accumulation == pytest.approx(
        30.0 * CP * (storage.inlets.injection_in.T - 284.15), rel=1e-9
    )
    _check_balances(plant, result)


def test_two_charge_steps_fill_the_warm_store():
    """Stepping twice fills the warm store with the first hour's accumulation less conduction.

    The conduction loss that sets in during the first hour takes about 0.15 %.
    """
    plant = _plant()
    state, first = plant.step(None, HOUR, {"return_in": SUMMER})
    state, second = plant.step(state, HOUR, {"return_in": SUMMER})
    assert state["storage"]["warm_volume"] == pytest.approx(2 * 30 / 1000 * HOUR)
    assert state["storage"]["warm_temperature_change"] > 0
    assert first.children["storage"].outputs.stored_energy == 0
    stored = first.children["storage"].outputs.heat_accumulation * HOUR
    assert stored > second.children["storage"].outputs.stored_energy > 0.995 * stored
    _check_balances(plant, second)


def test_discharge_feeds_the_heat_pump_from_the_warm_store():
    """After charging, the warm store feeds the evaporator and the condenser heats the building."""
    plant = _plant()
    state, _ = plant.step(None, 6 * HOUR, {"return_in": SUMMER})
    warm = 284.15 + state["storage"]["warm_temperature_change"]
    _season(plant, "discharge")
    state, result = plant.step(state, HOUR, {"return_in": WINTER})
    out = reading(result)
    lifted = result.children["heat_pump"]
    assert result.children["storage"].outlets.production_out.T == pytest.approx(warm, rel=1e-14)
    assert (
        result.children["pump"].inlets.fluid_in.T
        == result.children["storage"].outlets.production_out.T
    )
    assert result.outlets.supply_out.T == pytest.approx(313.15, rel=1e-12)
    assert lifted.inlets.source_in == result.children["pump"].outlets.fluid_out
    assert result.children["storage"].inlets.injection_in.T == lifted.outlets.source_out.T < warm
    assert result.children["heat_exchanger"].outputs.duty == 0
    assert out.electricity == pytest.approx(
        reading(lifted).electricity + reading(result.children["pump"]).electricity, rel=1e-14
    )
    assert state["storage"]["cold_volume"] == pytest.approx(30 / 1000 * HOUR)
    _check_balances(plant, result)


def test_idle_moves_no_groundwater_and_flow_is_required_to_stop():
    """Idle passes the building circuit; idle with groundwater flow raises."""
    plant = _plant("idle")
    plant.storage.groundwater_flow = 0.0
    result = plant(return_in=SUMMER)
    assert result.outlets.supply_out.T == SUMMER.T
    assert reading(result).electricity == 0
    plant.storage.groundwater_flow = 30.0
    with pytest.raises(gm.errors.PhysicsError, match="idle"):
        plant(return_in=SUMMER)


class Campus(Module):
    """Building loop served by the ATES plant, to step it as a child."""

    def __init__(self):
        """Declare the test composite."""
        super().__init__()

        # Modules
        self.ates = _plant()

        # Inlets
        self.return_in = Inlet(Stream)

        # Outputs
        self.stored_energy = Output(float)

        # Outlets
        self.supply_out = Outlet(Stream)

    def forward(self, inlets):
        """Cool the building return."""

        # Modules
        served = self.ates(return_in=inlets.return_in)

        # Outputs
        self.stored_energy = served.children["storage"].outputs.stored_energy

        # Outlets
        supply_out = served.outlets.supply_out

        outlets = dict(supply_out=supply_out)
        return outlets


def test_nested_plant_steps_through_its_parent():
    """A parent composite steps the ATES storage two levels down."""
    campus = Campus()
    state, _ = campus.step(None, HOUR, {"return_in": SUMMER})
    state, result = campus.step(state, HOUR, {"return_in": SUMMER})
    assert state["ates"]["storage"]["warm_volume"] == pytest.approx(2 * 30 / 1000 * HOUR)
    assert result.outputs.stored_energy > 0
