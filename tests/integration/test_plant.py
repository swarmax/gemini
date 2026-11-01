"""Explicit plant wiring, buried pump segmentation and diagram verification."""

from pathlib import Path

import pytest

import gemini as gm
from gemini.modules._utils.balance import collect_flows, energy_balance, mass_balance
from gemini.modules._utils.wiring import trace_wiring
from scripts.legacy import wiring
from scripts.legacy.project import GeminiProject
from tests.fixtures import OLD_PROJECT
from tests.fixtures.reading import reading

ROOT = Path(__file__).parents[2]


@pytest.fixture
def example(fresh_plant, fast_dataset):
    """Prepare one real operating point."""
    data = fast_dataset.window(end=fast_dataset.start)
    captured = {}

    def capture(module, inlets):
        captured.update(inlets)

    handle = fresh_plant.register_forward_pre_hook(capture)
    gm.simulate(fresh_plant, plan=data, clock=gm.engine.Clock.from_data(data), on_error="raise")
    handle.remove()
    return fresh_plant, captured


def test_handwritten_wiring_and_split_helpers(example):
    """Every diagram link matches actual identities, including both sides of the buried ESP."""
    plant, inputs = example
    result = plant(**inputs)
    leaves = result.leaves()
    assert set(leaves) == {
        path for path, module in plant.named_modules() if path and module.is_leaf
    }
    traced = trace_wiring(plant, inputs)
    assert len(traced) == 10
    project = GeminiProject.from_folder(OLD_PROJECT)
    assert wiring.check_wiring(plant, project) == []
    well = plant.doublet.well
    bottom = leaves["doublet.reservoir"].outlets["sandface_out"]
    assert well.intake_conditions(bottom) == leaves["doublet.well"].outlets["wellhead_out"]
    discharge = leaves["doublet.esp"].outlets["fluid_out"]
    assert (
        well.wellhead_from_discharge(discharge) == leaves["doublet.riser"].outlets["wellhead_out"]
    )
    assert reading(result).electricity == collect_flows(result)["electricity"]
    assert mass_balance(plant, result)["relative_residual"] < 1e-12
    balance = energy_balance(plant, result)
    assert balance["relative_thermal_residual"] < 1e-12
    assert balance["residual"] == pytest.approx(reading(result).electricity)


def test_trace_hooks_are_removed_after_failure(example):
    """Failed evaluation does not leak observers into subsequent calls."""
    plant, inputs = example
    before = [(len(m._hooks), len(m._pre_hooks)) for m in plant.modules()]
    efficiency = plant.injection_pump.efficiency
    plant.injection_pump.efficiency = None
    with pytest.raises(gm.errors.ValidationError):
        trace_wiring(plant, inputs)
    assert before == [(len(m._hooks), len(m._pre_hooks)) for m in plant.modules()]
    plant.injection_pump.efficiency = efficiency
    plant(**inputs)
