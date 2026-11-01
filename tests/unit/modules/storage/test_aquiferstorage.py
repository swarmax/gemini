"""ATES well pair: store bookkeeping, conduction losses, recovery and balances."""

import math

import pytest

import gemini as gm
from gemini import ops
from gemini.modules import Module, energy_balance, mass_balance
from gemini.modules.declarations import Inlet, Outlet, Output
from gemini.modules.heating import ElectricBoiler
from gemini.modules.storage import AquiferStorage
from gemini.physics import ground
from gemini.types import Stream
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_function_matches, assert_same_error
from tests.fixtures.reading import reading

WARM = Stream(
    m_dot=gm.units.Quantity(30, "kg/s"),
    T=gm.units.Quantity(291.15, "K"),
    p=gm.units.Quantity(3e5, "Pa"),
)
COLD = WARM.with_(T=279.15)
WATER = 1000 * 4217.4
AQUIFER = 0.3 * WATER + 0.7 * 2.0e6
HOUR = 3600.0


def storage(mode="charge"):
    """Return a configured well pair in ``mode``."""
    module = with_values(AquiferStorage()).set_params(
        "",
        {
            "aquifer_temperature": gm.units.Quantity(284.15, "K"),
            "aquifer_thickness": gm.units.Quantity(30, "m"),
            "porosity": 0.3,
            "rock_volumetric_heat_capacity": gm.units.Quantity(2.0e6, "J/m3/K"),
            "ground_conductivity": gm.units.Quantity(2.5, "W/m/K"),
        },
    )
    module.mode = mode
    return module


def conductance(water_volume):
    """Return the hand-computed store conductance [W/K] of a water volume [m3]."""
    radius = math.sqrt(water_volume * WATER / AQUIFER / (math.pi * 30))
    area = 2 * math.pi * radius * (radius + 30)
    diffusivity = 2.5 / AQUIFER
    return 2 * 2.5 * area / math.sqrt(math.pi * diffusivity * 182.625 * 86400)


class Plant(Module):
    """Heater feeding the warm well while charging."""

    def __init__(self):
        """Declare the test composite."""
        super().__init__()

        # Modules
        self.heater = ElectricBoiler().set_params(
            "", {"capacity": gm.units.Quantity(1e7, "W"), "efficiency": 0.9}
        )
        self.storage = storage()

        # Inlets
        self.supply_in = Inlet(Stream)

        # Outputs
        self.stored_energy = Output(float)

        # Outlets
        self.return_out = Outlet(Stream)

    def forward(self, inlets):
        """Heat the supply, store it and return the cold-well water."""

        # Modules
        heated = self.heater(fluid_in=inlets.supply_in, temperature_setpoint=291.15)
        stored = self.storage(injection_in=heated.outlets.fluid_out)

        # Outputs
        self.stored_energy = stored.outputs.stored_energy

        # Outlets
        return_out = stored.outlets.production_out

        outlets = dict(return_out=return_out)
        return outlets


def test_plain_call_uses_the_empty_initial_stores():
    """Empty stores produce native groundwater and hold no energy."""
    module = storage()
    result = module(injection_in=WARM)
    out = reading(result)
    assert module.initial_state()["warm_volume"] == 0
    assert result.outlets.production_out == WARM.with_(T=284.15)
    assert out.stored_energy == 0 and out.heat_loss == 0 == out.heat_absorbed
    assert out.recovery_efficiency is None and out.warm_temperature == 284.15


def test_two_charge_steps_fill_and_mix_the_warm_store():
    """The warm store gains Q dt per step at the mixed temperature, then decays exactly."""
    module = storage()
    volume = 30 / 1000 * HOUR
    state, _ = module.step(None, HOUR, {"injection_in": WARM})
    decay = math.exp(-HOUR * conductance(volume) / (WATER * volume))
    assert state["warm_volume"] == pytest.approx(volume)
    assert state["warm_temperature_change"] == pytest.approx(7 * decay, rel=1e-12)
    assert state["cold_volume"] == 0 and state["charged_heat"] == pytest.approx(WATER * volume * 7)
    first = state["warm_temperature_change"]
    state, result = module.step(state, HOUR, {"injection_in": WARM})
    mixed = (first + 7) / 2
    decay = math.exp(-HOUR * conductance(2 * volume) / (WATER * 2 * volume))
    assert state["warm_temperature_change"] == pytest.approx(mixed * decay, rel=1e-12)
    assert reading(result).heat_loss == pytest.approx(conductance(volume) * first, rel=1e-12)
    assert reading(result).production_out_T == 284.15


def test_heat_accumulation_is_the_rate_of_change_of_stored_energy():
    """Mass is balanced; heat_accumulation is dE/dt at the step start and closes the audit."""
    module = storage("discharge")
    start = {
        "warm_volume": 2e5,
        "warm_temperature_change": 5.0,
        "cold_volume": 1e5,
        "cold_temperature_change": -3.0,
        "charged_heat": 6e12,
        "recovered_heat": 1e12,
    }
    state, result = module.step(start, 1.0, {"injection_in": COLD})
    assert mass_balance(module, result)["residual"] == 0
    out = reading(result)
    assert result.outlets.loss_out == pytest.approx(conductance(2e5) * 5 - conductance(1e5) * 3)
    _, after = module.step(state, 1.0, {"injection_in": COLD})
    rate = after.outputs.stored_energy - out.stored_energy
    assert out.heat_accumulation == pytest.approx(rate, rel=1e-6)
    audit = energy_balance(module, result)
    assert audit["relative_residual"] < 1e-12
    assert audit["heat_accumulation"] == out.heat_accumulation
    assert out.production_out_T == 289.15 and out.recovery_efficiency == pytest.approx(1 / 6)
    recovered = 1e12 + WATER * 30 / 1000 * 5.0
    assert state["recovered_heat"] == pytest.approx(recovered)


def test_idle_store_decays_exactly_and_rejects_flow():
    """Idle stores relax exponentially, so two steps equal one double step."""
    module = storage("idle")
    start = storage().initial_state() | {"warm_volume": 2e5, "warm_temperature_change": 5.0}
    still = WARM.with_(m_dot=0)
    half, _ = module.step(start, 86400, {"injection_in": still})
    half, result = module.step(half, 86400, {"injection_in": still})
    full, _ = module.step(start, 2 * 86400, {"injection_in": still})
    assert half["warm_temperature_change"] == pytest.approx(full["warm_temperature_change"])
    assert full["warm_volume"] == 2e5 and result.outlets.production_out.m_dot == 0
    stopped, _ = storage().step(start, 2 * 86400, {"injection_in": still})
    assert stopped == full
    empty = storage()
    assert empty.step(None, 60, {"injection_in": still})[0] == empty.initial_state()
    with pytest.raises(gm.errors.PhysicsError, match="idle mode"):
        module(injection_in=WARM)
    with pytest.raises(gm.errors.PhysicsError, match="m_dot = -1"):
        storage()(injection_in=WARM.with_(m_dot=-1))


def test_overdrawn_store_empties_to_native_groundwater():
    """Withdrawal stops at zero volume and the empty store returns to the aquifer temperature."""
    module = storage("discharge")
    start = storage().initial_state() | {"warm_volume": 10.0, "warm_temperature_change": 5.0}
    state, result = module.step(start, HOUR, {"injection_in": COLD})
    assert reading(result).production_out_T == 289.15
    assert state["warm_volume"] == 0 and state["warm_temperature_change"] == 0
    _, result = module.step(state, HOUR, {"injection_in": COLD})
    assert reading(result).production_out_T == 284.15


def test_composite_step_charges_through_the_plant():
    """A plant composite steps the storage through its forward."""
    plant = Plant()
    state, _ = plant.step(None, HOUR, {"supply_in": WARM.with_(T=285.15)})
    state, result = plant.step(state, HOUR, {"supply_in": WARM.with_(T=285.15)})
    assert state["storage"]["warm_volume"] == pytest.approx(2 * 30 / 1000 * HOUR)
    assert result.outputs.stored_energy > 0
    assert result.outlets.return_out.T == 284.15
    assert energy_balance(plant, result)["relative_residual"] < 1e-12
    assert mass_balance(plant, result)["residual"] == 0


class Reader(Module):
    """Record the production temperature before calling the storage."""

    def __init__(self, seen):
        """Declare the test composite; ``seen`` collects the temperatures read."""
        super().__init__()
        object.__setattr__(self, "seen", seen)

        # Modules
        self.storage = storage("discharge").set_params(
            "", {"groundwater_pressure": gm.units.Quantity(3e5, "Pa")}
        )
        self.storage.groundwater_flow = 30.0

        # Inlets
        self.supply_in = Inlet(Stream)

        # Outlets
        self.return_out = Outlet(Stream)

    def forward(self, inlets):
        """Read the production temperature, then call the storage."""

        # Modules
        self.seen.append(self.storage._offered()["production_out"].T)
        stored = self.storage(injection_in=inlets.supply_in)

        # Outlets
        return_out = stored.outlets.production_out

        outlets = dict(return_out=return_out)
        return outlets


def test_the_offer_reads_the_running_step():
    """Before its call a plant reads the start-of-step production temperature of the offer."""
    seen = []
    reader = Reader(seen)
    result = reader(supply_in=COLD)
    assert seen == [284.15] == [result.outlets.return_out.T]
    start = {"warm_volume": 1e5, "warm_temperature_change": 4.0}
    _, result = reader.step({"storage": start}, HOUR, {"supply_in": COLD})
    assert seen[-1] == 288.15 == result.outlets.return_out.T
    assert storage("idle").production_temperature() == 284.15


def test_store_arithmetic_matches_on_arrays():
    """The conduction conductance and the exponential decay agree on arrays for empty stores."""
    module = storage()

    @ops.physics
    def numbers(volume, dt):
        water = module._fluid_heat_capacity(WARM)
        conductance = ground.store_conductance(
            volume,
            module.ground_conductivity,
            module.porosity,
            water,
            module.rock_volumetric_heat_capacity,
            module.aquifer_thickness,
            module.storage_period,
        )
        decay = ground.store_relaxation(1.0, volume, conductance, dt, water)
        return dict(conductance=conductance, decay=decay)

    rows = [(0.0, HOUR), (1e4, HOUR), (3e5, 24 * HOUR)]
    assert_function_matches(numbers, rows)
    assert_same_error(numbers, rows + [(-1.0, HOUR)], gm.errors.PhysicsError)


@pytest.mark.parametrize("mode", ["charge", "discharge"])
def test_moved_store_matches_on_arrays(mode):
    """Mixing into the target and drawing down the source agree on arrays, empty store included."""
    module = storage(mode)

    @ops.physics
    def moved(volume, change):
        warm = module._moved_store("warm", volume, change)
        cold = module._moved_store("cold", volume, change)
        return dict(enumerate(warm + cold))

    rows = [(0.0, 7.0), (500.0, 7.0), (2e5, -5.0)]
    assert_function_matches(moved, rows)
