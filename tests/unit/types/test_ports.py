"""Immutable named fluid-port mappings."""

import numpy as np
import pytest

from gemini.errors import ValidationError
from gemini.types import BRINE, Ports, Stream
from gemini.units import Quantity
from tests.fixtures.errors import raises


@pytest.fixture
def streams():
    """Return two distinct streams for mapping tests."""
    return (
        Stream(m_dot=Quantity(1, "kg/s"), T=Quantity(300, "K"), p=Quantity(1e5, "Pa")),
        Stream(m_dot=Quantity(2, "kg/s"), T=Quantity(310, "K"), p=Quantity(2e5, "Pa")),
    )


def test_mapping_attributes_and_declaration_order(streams):
    """Ports expose the complete Mapping API and attribute access in input order."""
    suction, return_stream = streams
    ports = Ports({"fluid_in": suction, "return_stream": return_stream}, path="plant.pump")

    assert ports["fluid_in"] is suction
    assert ports.fluid_in is suction
    assert "return_stream" in ports
    assert len(ports) == 2
    assert list(ports) == ["fluid_in", "return_stream"]
    assert list(ports.keys()) == ["fluid_in", "return_stream"]
    assert list(ports.values()) == [suction, return_stream]
    assert list(ports.items()) == [
        ("fluid_in", suction),
        ("return_stream", return_stream),
    ]


def test_unknown_names_include_path_valid_names_and_suggestion(streams):
    """Mapping and attribute misses explain the owning module and nearest port."""
    ports = Ports({"fluid_in": streams[0]}, path="plant.esp")

    with pytest.raises(
        AttributeError, match="plant.esp.*fluid_ni.*valid names: fluid_in.*did you mean 'fluid_in'"
    ):
        ports.fluid_ni
    with raises(
        ValidationError, "unknown_port", match="plant.esp.*fluid_out.*valid names: fluid_in"
    ):
        ports["fluid_out"]


def test_ports_are_immutable_and_copy_the_source_mapping(streams):
    """Neither mapping syntax, attributes nor later source edits can mutate Ports."""
    source = {"fluid_in": streams[0]}
    ports = Ports(source, path="pump")
    source["fluid_in"] = streams[1]

    assert ports.fluid_in is streams[0]
    with pytest.raises(TypeError):
        ports["fluid_in"] = streams[1]
    with pytest.raises(TypeError):
        del ports["fluid_in"]
    with pytest.raises(AttributeError, match="immutable"):
        ports.fluid_in = streams[1]
    with pytest.raises(AttributeError, match="immutable"):
        del ports.fluid_in


def test_ports_reject_non_stream_values(streams):
    """The port mapping never carries scalar controls or computed outputs."""
    with pytest.raises(
        ValidationError, match="plant.esp.*fluid_in.*Stream or a power.*valid names: fluid_in"
    ):
        Ports({"fluid_in": {"value": 1, "unit": "W"}}, path="plant.esp")


def test_ports_accept_streams_of_arrays():
    """Batched calls pass ``Stream`` values of arrays through the same mapping."""
    state = Stream(
        m_dot=Quantity(np.array([1.0, 2.0]), "kg/s"),
        T=Quantity(300.0, "K"),
        p=Quantity(1e5, "Pa"),
        fluid=BRINE,
    )
    assert Ports({"fluid_in": state}).fluid_in is state


def test_trusted_ports_equal_checked_ports_and_stay_immutable(streams):
    """The unchecked constructor of the engine gives the same mapping, read-only."""
    values = {"fluid_in": streams[0], "return_stream": streams[1]}
    trusted = Ports._trusted(dict(values), "plant.pump")
    assert dict(trusted) == dict(Ports(values, path="plant.pump")) == values
    assert trusted._unknown("fluid_in") == Ports(values, path="plant.pump")._unknown("fluid_in")
    with pytest.raises(AttributeError, match="immutable"):
        trusted.fluid_in = streams[1]
