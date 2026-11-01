"""Multi-well field: production limbs mixed into one supply, return split over injectors."""

import pytest

import gemini as gm
from gemini.modules import energy_balance, mass_balance
from gemini.types import Stream
from tests.fixtures.balance import assert_plant_closes
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

LIMB = ("reservoir", "well", "esp", "riser")


def _field(doublet, producers=2, injectors=1, rates=(40.0, 30.0)):
    """Return a field whose limbs copy the example doublet's equipment."""
    field = gm.plants.MultiWellPlant(producers=producers, injectors=injectors)
    for limb, rate in zip(field.producers, rates):
        for name in LIMB:
            getattr(limb, name).set_state_dict(getattr(doublet, name).state_dict())
        limb.reservoir.production_rate = rate
        limb.esp.frequency = 50.0
    for limb in field.injectors:
        limb.well.set_state_dict(doublet.injector.state_dict())
        limb.sink.set_state_dict(doublet.sink.state_dict())
    return field


def test_two_producers_mix_into_the_supply(fresh_plant):
    """The supply carries both wells' flow at their capacity-weighted temperature."""
    field = _field(fresh_plant.doublet)
    returned = Stream(
        m_dot=gm.units.Quantity(70, "kg/s"),
        T=gm.units.Quantity(330, "K"),
        p=gm.units.Quantity(5e6, "Pa"),
        fluid=field.producers[0].riser.fluid,
    )
    result = field(return_in=returned)
    assert_plant_closes(field, result)
    first = result.children["producers.0.riser"].outlets.wellhead_out
    second = result.children["producers.1.riser"].outlets.wellhead_out
    supply = result.outlets.supply_out
    assert supply.m_dot == pytest.approx(70, rel=1e-12)
    expected = (first.m_dot * first.T + second.m_dot * second.T) / (first.m_dot + second.m_dot)
    assert supply.T == pytest.approx(expected, rel=1e-12)
    assert supply.p == min(first.p, second.p)
    assert result.outlets.supply_out.T == supply.T
    assert result.children["injectors.0.well"].inlets.wellhead_in == returned
    leaves = result.leaves().values()
    assert reading(result).electricity == pytest.approx(
        sum(reading(leaf).get("electricity", 0.0) for leaf in leaves)
    )
    assert sum(result.children["formation"].inlets.heat_in) == pytest.approx(
        sum(leaf.outlets.loss_out for leaf in leaves if "loss_out" in leaf.outlets)
    )
    audit = energy_balance(field, result)
    assert audit["relative_thermal_residual"] < 1e-12
    assert mass_balance(field, result)["relative_residual"] < 1e-12


def test_splitters_share_the_return_over_three_injectors(fresh_plant):
    """Injector i takes f_i prod (1 - f_j) of the return; the last takes the rest."""
    field = _field(fresh_plant.doublet, producers=1, injectors=3, rates=(40.0,))
    field.splitters[0].split_fraction = 0.5
    field.splitters[1].split_fraction = 0.4
    returned = Stream(
        m_dot=gm.units.Quantity(40, "kg/s"),
        T=gm.units.Quantity(330, "K"),
        p=gm.units.Quantity(5e6, "Pa"),
        fluid=field.producers[0].riser.fluid,
    )
    result = field(return_in=returned)
    flows = [result.children[f"injectors.{i}.well"].inlets.wellhead_in.m_dot for i in range(3)]
    assert flows == pytest.approx([20.0, 8.0, 12.0], rel=1e-14)
    riser = result.children["producers.0.riser"]
    assert result.outlets.supply_out.T == reading(riser).wellhead_temperature
    assert len(field.mixers) == 0
    assert mass_balance(field, result)["relative_residual"] < 1e-12


def test_invalid_structure_raises():
    """A field needs at least one producer and one injector."""
    with raises(gm.errors.ValidationError, "invalid_design", match="producers = 0"):
        gm.plants.MultiWellPlant(producers=0)
    with raises(gm.errors.ValidationError, "invalid_design", match="injectors = 0"):
        gm.plants.MultiWellPlant(injectors=0)
    with pytest.raises(gm.errors.ValidationError, match="producers = 0"):
        gm.plants.MultiWellPlant(producers=0)
