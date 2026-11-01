"""``gm.plants.capabilities`` against a real ``gm.schedule`` of every plant class."""

import gemini as gm
from gemini.case.roletable import units_of
from tests.fixtures.sample_problems import filled_plant, sample_case


def _plans_doublets(name):
    """Whether a real ``gm.schedule`` of the plant ``name`` gives the flow of its doublets."""
    plant = filled_plant(name)
    paths = [path for path in units_of(plant, "doublet") if path]
    try:
        plan = gm.schedule(plant, sample_case())
    except gm.errors.ValidationError:
        return False
    return bool(paths) and all(f"{path}.flow" in plan.columns for path in paths)


def test_schedulable_agrees_with_a_real_schedule():
    """For every plant class that can be filled with values, the schedule plans it or does not."""
    found = gm.plants.capabilities()
    assert {name: item["schedulable"] for name, item in found.items()} == {
        name: _plans_doublets(name) for name in found
    }
