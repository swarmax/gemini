"""The cascades and the shared wiring blocks that plants connect with."""

import gemini as gm
from gemini.plants._utils.wiring import mix_chain, split_chain


class Recorder:
    """A plant stand-in that records the connections in order."""

    def __init__(self):
        """Start with no connection."""
        self.connections = []

    def connect(self, source, target):
        """Record one connection."""
        self.connections.append((source, target))


def test_a_mix_chain_feeds_the_running_mix_to_the_first_branch():
    """Three ends need two mixers; the last mix goes to the outlet."""
    plant = Recorder()
    mix_chain(plant, ["a", "b", "c"], "mixers", "out")
    assert plant.connections == [
        ("a", "mixers.0.branch1_in"),
        ("b", "mixers.0.branch2_in"),
        ("mixers.0.fluid_out", "mixers.1.branch1_in"),
        ("c", "mixers.1.branch2_in"),
        ("mixers.1.fluid_out", "out"),
    ]


def test_a_mix_chain_without_an_outlet_leaves_the_last_mix_open():
    """The caller connects what follows."""
    plant = Recorder()
    mix_chain(plant, ["a", "b"], "mixers")
    assert plant.connections[-1] == ("b", "mixers.0.branch2_in")


def test_a_split_chain_links_the_splitters_then_serves_the_targets():
    """Each splitter serves a target by branch2; the last gets what is left by branch1."""
    plant = Recorder()
    split_chain(plant, "splitters", ["x", "y", "z"])
    assert plant.connections == [
        ("splitters.0.branch1_out", "splitters.1.fluid_in"),
        ("splitters.0.branch2_out", "x"),
        ("splitters.1.branch2_out", "y"),
        ("splitters.1.branch1_out", "z"),
    ]


def test_the_heating_plants_keep_their_gas_wiring():
    """The shared block connects the degasser gas to the makeup and the flare."""
    plant = gm.plants.get("HeatingPlant")
    assert "gas_makeup.excess_out" in str(plant.to_dict(structure=True)["connections"])
