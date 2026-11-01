"""District network: parallel substations, split and mix cascades, totals and balances."""

import math

import pytest

import gemini as gm
from gemini.modules import energy_balance, mass_balance
from gemini.plants import CoolingSubstation, HeatingSubstation
from gemini.types import Stream
from tests.fixtures.air import air
from tests.fixtures.balance import assert_plant_closes
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

CP = 4217.4
HOT = Stream(
    m_dot=gm.units.Quantity(4.0, "kg/s"),
    T=gm.units.Quantity(348.15, "K"),
    p=gm.units.Quantity(6e5, "Pa"),
)
CHILLED = Stream(
    m_dot=gm.units.Quantity(6.0, "kg/s"),
    T=gm.units.Quantity(279.15, "K"),
    p=gm.units.Quantity(6e5, "Pa"),
)


def _network(**parameters):
    """Return a district network of the given size."""
    return gm.plants.DistrictNetwork(**parameters)


def _leaf_sum(result, name):
    """Return the sum of one output over every leaf call [W]."""
    return sum(reading(leaf).get(name, 0.0) for leaf in result.leaves().values())


def test_heating_network_serves_both_substations(plants):
    """Equal shares feed identical substations; totals and the stream audit add up."""
    network = plants["network"](_network(), plants["heating_substation"])
    result = network(supply_in=HOT, air_in=air(283.15))
    out = reading(result)
    assert_plant_closes(network, result)
    children = result.children
    feeds = [children[f"substations.{index}"].inlets.supply_in.m_dot for index in range(2)]
    assert feeds == [2.0, 2.0]
    assert _leaf_sum(result, "heat_supplied") == pytest.approx(3e5, rel=1e-12)
    pumps = [children["pump"], *(children[f"substations.{i}"].children["pump"] for i in range(2))]
    assert out.electricity == pytest.approx(sum(reading(pump).electricity for pump in pumps))
    assert out.heat_loss == pytest.approx(_leaf_sum(result, "heat_loss"), rel=1e-14)
    assert out.heat_absorbed == 0
    mixed = children["mixers.0"].outlets.fluid_out
    substation = children["substations.0"].outlets.return_out
    assert mixed.T == pytest.approx(substation.T, rel=1e-14) and mixed.m_dot == 4.0
    transfer = 1.0 * math.pi * 0.1 * 500 / (4.0 * CP)
    expected = 283.15 + (mixed.T - 283.15) * math.exp(-transfer)
    assert out.return_out_T == pytest.approx(expected, rel=1e-12)
    assert result.outlets.return_out.T == out.return_out_T
    audit = energy_balance(network, result)
    hydraulic = children["pump"].outputs.hydraulic_power
    assert abs(audit["residual"] - hydraulic) / audit["in"] < 1e-12
    assert mass_balance(network, result)["residual"] == 0


def test_nested_substations_show_what_their_consumers_take(plants):
    """The consumers inside the substations are read once, on their ports, not by the network."""
    network = plants["network"](_network(consumers=3), plants["heating_substation"])
    result = network(supply_in=HOT.with_(m_dot=4.5), air_in=air(283.15))
    substation_sums = [
        reading(result.children[f"substations.{index}"]).heat_supplied for index in range(3)
    ]
    assert "heat_supplied" not in network.outputs(recurse=False)
    assert _leaf_sum(result, "heat_supplied") == pytest.approx(sum(substation_sums), rel=1e-12)


def test_three_way_split_and_mix(plants):
    """The cascades give every substation a third and mix three returns."""
    network = plants["network"](_network(consumers=3), plants["heating_substation"])
    result = network(supply_in=HOT.with_(m_dot=4.5), air_in=air(283.15))
    feeds = [result.children[f"substations.{index}"].inlets.supply_in.m_dot for index in range(3)]
    assert feeds == pytest.approx([1.5] * 3, rel=1e-15)
    assert len(network.splitters) == len(network.mixers) == 2
    assert result.outlets.return_out.m_dot == pytest.approx(4.5, rel=1e-15)
    assert mass_balance(network, result)["residual"] == pytest.approx(0, abs=1e-12)


def test_cooling_network_absorbs_building_and_ground_heat(plants):
    """A cooling network has no heat_supplied; heat_absorbed adds consumers and pipe gains."""
    network = plants["network"](_network(service="cooling"), plants["cooling_substation"])
    assert isinstance(network.substations[0], CoolingSubstation)
    assert "heat_supplied" not in network.outputs(recurse=False)
    result = network(supply_in=CHILLED, air_in=air(283.15))
    assert _leaf_sum(result, "heat_absorbed") > 1.4e5
    assert_plant_closes(network, result)
    audit = energy_balance(network, result)
    hydraulic = result.children["pump"].outputs.hydraulic_power
    assert abs(audit["residual"] - hydraulic) / audit["in"] < 1e-12


def test_single_consumer_and_invalid_structure(plants):
    """One substation needs no tees; bad structural arguments raise."""
    network = plants["network"](_network(consumers=1), plants["heating_substation"])
    assert isinstance(network.substations[0], HeatingSubstation)
    result = network(supply_in=HOT.with_(m_dot=2.0), air_in=air(283.15))
    assert _leaf_sum(result, "heat_supplied") == pytest.approx(1.5e5, rel=1e-12)
    with raises(gm.errors.ValidationError, "invalid_design", match="service"):
        gm.plants.DistrictNetwork(service="steam")
    with raises(gm.errors.ValidationError, "invalid_design", match="consumers"):
        gm.plants.DistrictNetwork(consumers=0)
    with pytest.raises(gm.errors.ValidationError, match="service"):
        gm.plants.DistrictNetwork(service="steam")
