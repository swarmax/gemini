"""Lumped ice store: coil duty, piecewise exact phase segments, balances and limits."""

import math
from types import SimpleNamespace

import pytest

import gemini as gm
from gemini import ops
from gemini.modules import Module, energy_balance, mass_balance
from gemini.modules.declarations import Inlet, Outlet
from gemini.modules.storage import IceStorage
from gemini.types import GLYCOL_30, Stream
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_function_matches, assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

MASS = 1000.0
UA = 2000.0
LATENT = MASS * 333550
"""Latent capacity [J] of the 1 t test store."""

RATE = 2.0 * 3841
"""Glycol capacity rate [W/K] of 2 kg/s of 30 % propylene glycol."""

EFFECTIVENESS = 1 - math.exp(-UA / RATE)
CONDUCTANCE = EFFECTIVENESS * RATE
FREEZING = 273.15
COLD = Stream(m_dot=2.0, T=268.15, p=3e5, fluid=GLYCOL_30)
WARM = COLD.with_(T=285.15)


def _store():
    """Return a 1 t store with a 2 kW/K coil."""
    return with_values(IceStorage()).set_params("", {"water_mass": MASS, "thermal_conductance": UA})


def test_plain_call_charges_an_empty_store():
    """The initial store is all water at 0 degC; cold glycol is warmed by e (T_f - T_in)."""
    store = _store()
    result = store(fluid_in=COLD)
    out = reading(result)
    assert out.fluid_out_T == pytest.approx(268.15 + EFFECTIVENESS * 5)
    assert out.signed_duty == pytest.approx(-CONDUCTANCE * 5)
    assert out.stored_cold == 0 and out.is_empty and not out.is_full
    assert result.outlets.fluid_out.m_dot == COLD.m_dot and result.outlets.fluid_out.p == COLD.p
    assert out.heat_accumulation == pytest.approx(out.signed_duty)
    assert energy_balance(store, result)["relative_residual"] < 1e-12
    assert mass_balance(store, result)["residual"] == 0


def test_latent_steps_freeze_at_constant_duty():
    """Partly frozen, the store stays at 0 degC and x grows by -duty dt / (M L)."""
    store = _store()
    state, result = store.step(
        {"ice_fraction": 0.5, "temperature": FREEZING}, 3600, {"fluid_in": COLD}
    )
    assert result.outputs.stored_cold == pytest.approx(0.5 * LATENT)
    first = 0.5 + CONDUCTANCE * 5 * 3600 / LATENT
    assert state == {"ice_fraction": pytest.approx(first, rel=1e-14), "temperature": FREEZING}
    state, result = store.step(state, 3600, {"fluid_in": COLD})
    assert reading(result).signed_duty == pytest.approx(-CONDUCTANCE * 5)
    assert state["ice_fraction"] == pytest.approx(first + CONDUCTANCE * 5 * 3600 / LATENT)


def test_a_full_store_subcools_and_an_empty_store_warms():
    """A step that fills (empties) the store continues as sensible ice (water)."""
    store = _store()
    state, _ = store.step({"ice_fraction": 0.99, "temperature": FREEZING}, 3600, {"fluid_in": COLD})
    filled = 0.01 * LATENT / (CONDUCTANCE * 5)
    tau = MASS * 2096.8 / CONDUCTANCE
    assert state["ice_fraction"] == 1
    assert state["temperature"] == pytest.approx(268.15 + 5 * math.exp(-(3600 - filled) / tau))
    _, result = store.step(state, 60, {"fluid_in": COLD})
    assert result.outputs.is_full and result.outputs.stored_cold == pytest.approx(LATENT)

    state, _ = store.step({"ice_fraction": 0.01, "temperature": FREEZING}, 3600, {"fluid_in": WARM})
    emptied = 0.01 * LATENT / (CONDUCTANCE * 12)
    tau = MASS * 4219.9 / CONDUCTANCE
    assert state["ice_fraction"] == 0
    assert state["temperature"] == pytest.approx(285.15 - 12 * math.exp(-(3600 - emptied) / tau))


def test_sensible_stores_reach_freezing_then_change_phase():
    """Warm water cools to 0 degC before freezing; subcooled ice warms to 0 degC before melting."""
    store = _store()
    state, _ = store.step({"ice_fraction": 0, "temperature": 278.15}, 7200, {"fluid_in": COLD})
    reach = MASS * 4219.9 / CONDUCTANCE * math.log(10 / 5)
    assert state["temperature"] == FREEZING
    assert state["ice_fraction"] == pytest.approx(CONDUCTANCE * 5 * (7200 - reach) / LATENT)
    state, _ = store.step({"ice_fraction": 1, "temperature": 263.15}, 7200, {"fluid_in": WARM})
    reach = MASS * 2096.8 / CONDUCTANCE * math.log(22 / 12)
    assert state["temperature"] == FREEZING
    assert state["ice_fraction"] == pytest.approx(1 - CONDUCTANCE * 12 * (7200 - reach) / LATENT)


def test_stopped_glycol_leaves_the_store_unchanged():
    """Zero flow transfers no heat and keeps the state."""
    store = _store()
    start = {"ice_fraction": 0.3, "temperature": FREEZING}
    state, result = store.step(start, 3600, {"fluid_in": COLD.with_(m_dot=0)})
    assert state == start and reading(result).signed_duty == 0
    assert result.outlets.fluid_out.T == COLD.T


def test_invalid_states_and_flows_raise():
    """A temperature that contradicts the phase, and reverse flow, are rejected."""
    store = _store()
    with raises(
        gm.errors.ValidationError, "invalid_design", match="ice_storage: temperature = 270"
    ):
        store.step({"ice_fraction": 0.5, "temperature": 270.0}, 60, {"fluid_in": COLD})
    with raises(gm.errors.ValidationError, "invalid_design", match="with ice_fraction = 0"):
        store.step({"ice_fraction": 0, "temperature": 270.0}, 60, {"fluid_in": COLD})
    with pytest.raises(gm.errors.PhysicsError, match="fluid_in.m_dot = -1"):
        store(fluid_in=COLD.with_(m_dot=-1))
    with pytest.raises(gm.errors.ValidationError):
        store.step({"ice_fraction": 1.5, "temperature": FREEZING}, 60, {"fluid_in": COLD})


class StoreLine(Module):
    """Two ice stores charged in series."""

    def __init__(self):
        """Declare the test composite."""
        super().__init__()

        # Modules
        self.first = _store()
        self.second = _store()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the glycol through both stores."""

        # Modules
        first = self.first(fluid_in=inlets.fluid_in)
        second = self.second(fluid_in=first.outlets.fluid_out)

        # Outlets
        outlet = second.outlets.fluid_out

        outlets = dict(fluid_out=outlet)
        return outlets


def _stream_gain(result):
    """Return the heat [W] the glycol takes from the stores of ``result``, negative when cooled."""
    return sum(reading(leaf).signed_duty for leaf in result.leaves().values())


def test_composite_step_freezes_both_stores():
    """A composite steps both stores; the upstream store sees colder glycol and freezes faster."""
    line = StoreLine()
    state, _ = line.step(None, 1800, {"fluid_in": COLD})
    state, result = line.step(state, 1800, {"fluid_in": COLD})
    assert state["first"]["ice_fraction"] > state["second"]["ice_fraction"] > 0
    audit = energy_balance(line, result)
    assert audit["relative_residual"] < 1e-12
    assert audit["heat_accumulation"] == pytest.approx(_stream_gain(result), rel=1e-12)
    assert mass_balance(line, result)["residual"] == 0


STORE_STATES = [
    (0.0, 280.15, COLD),
    (0.0, 273.15, COLD),
    (0.4, 273.15, WARM),
    (0.4, 273.15, COLD),
    (1.0, 265.15, WARM),
    (1.0, 265.15, COLD),
    (0.0, 273.15, WARM),
    (0.0, 278.15, COLD.with_(m_dot=0)),
]


def test_ice_storage_matches_per_row():
    """Outputs and outlet of the initial store equal one call per row; the states are a break."""
    rows = [dict(fluid_in=glycol) for glycol in (COLD, WARM, COLD.with_(m_dot=0))]
    assert_module_matches(_store(), rows, breaks=True)


@pytest.mark.parametrize("dt", [600, 20000, 400000])
def test_ice_storage_advance_matches_per_row(monkeypatch, dt):
    """The piecewise phase integration on stacked states equals one step per row, stopped too."""
    store = _store()

    @ops.physics
    def advance(fraction, temperature, m_dot, glycol_T, pressure):
        monkeypatch.setattr(IceStorage, "ice_fraction", fraction, raising=False)
        monkeypatch.setattr(IceStorage, "temperature", temperature, raising=False)
        glycol = Stream(m_dot=m_dot, T=glycol_T, p=pressure, fluid=GLYCOL_30)
        states = store._advance_states(SimpleNamespace(fluid_in=glycol._numpy()), None, dt)
        return states["ice_fraction"], states["temperature"]

    rows = [(x, t, g.m_dot, g.T, g.p) for x, t, g in STORE_STATES]
    assert_function_matches(advance, rows)
