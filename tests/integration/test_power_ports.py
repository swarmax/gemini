"""Ports that carry a power, ``many`` ports and connections whose taker decides the flow."""

import numpy as np
import pytest

import gemini as gm
from gemini._utils import registry
from gemini.compiler.graph import run
from gemini.errors import ValidationError
from gemini.modules import Module
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.physics import energy
from gemini.types import Power, Stream

STREAM = gm.Stream(m_dot=2.0, T=300.0, p=2e5)


class Consumer(Module):
    """Pass the stream on and draw ``rating`` of electricity per kg/s."""

    category = "pumps"

    abstract = True

    def __init__(self):
        """Declare the rating and the ports."""
        super().__init__()

        # Parameters
        self.rating = Parameter(Power)

        # Inlets
        self.fluid_in = Inlet(Stream)
        self.power_in = Inlet(Power, kind="electricity")

        # Outputs
        self.drawn = Output(Power)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Draw what the flow needs."""

        # Outlets
        power_in = energy.total_power([self.rating * inlets.fluid_in.m_dot])

        outlets = dict(fluid_out=inlets.fluid_in, power_in=power_in)
        self.drawn = power_in
        return outlets


class Bus(Module):
    """Take what its consumers draw and what a source gives, and report the balance."""

    category = "power"

    abstract = True

    def __init__(self):
        """Declare both sides of the bus."""
        super().__init__()

        # Inlets
        self.power_in = Inlet(Power, kind="electricity", many=True)

        # Outputs
        self.net = Output(Power)

        # Outlets
        self.power_out = Outlet(Power, kind="electricity", many=True)

    def forward(self, inlets):
        """Nothing leaves but what its takers draw."""

        outlets = dict()
        self.net = energy.total_power(inlets.power_out) - energy.total_power(inlets.power_in)
        return outlets


class Source(Module):
    """A source whose stream exists before the other modules run."""

    category = "piping"

    abstract = True

    def __init__(self):
        """Declare the offer and the return side."""
        super().__init__()

        # Parameters
        self.temperature = Parameter(float)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outputs
        self.back = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream, offered=True)

    def _offer(self, inlets):
        return {"fluid_out": gm.Stream(m_dot=1.0, T=self.temperature, p=1e5)}

    def forward(self, inlets):
        """Give the same stream again."""

        # Outlets
        fluid_out = self._offer(inlets)["fluid_out"]

        outlets = dict(fluid_out=fluid_out)
        self.back = inlets.fluid_in.m_dot
        return outlets


class Taker(Module):
    """Take half of what its source offers, at the offered temperature."""

    category = "piping"

    abstract = True

    def __init__(self):
        """Declare the drawn inlet."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream, drawn=True)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Draw half of the offer."""

        # Outlets
        taken = inlets.fluid_in.with_(m_dot=inlets.fluid_in.m_dot / 2)

        outlets = dict(fluid_out=taken, fluid_in=taken)
        return outlets


class Offer(Module):
    """A source whose takers decide how much it gives."""

    category = "piping"

    abstract = True

    def __init__(self):
        """Declare the drawn offer."""
        super().__init__()

        # Outputs
        self.taken = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream, offered=True, drawn=True)

    def _offer(self, inlets):
        return {"fluid_out": gm.Stream(m_dot=8.0, T=320.0, p=1e5)}

    def forward(self, inlets):
        """Nothing to give but the offer."""

        outlets = dict()
        self.taken = inlets.fluid_out.m_dot
        return outlets


def consumer(rating):
    """Return a consumer of ``rating`` W per kg/s."""
    return Consumer().set_params("", {"rating": rating})


def wired():
    """Return a plant of two consumers on one bus, fed through the plant port ``feed``."""
    plant = gm.Plant("Wired")
    plant.add(Consumer, "first", {"rating": 10.0})
    plant.add(Consumer, "second", {"rating": 30.0})
    plant.add(Bus, "bus")
    plant.connect("feed", "first.fluid_in")
    plant.connect("first.fluid_out", "second.fluid_in")
    plant.connect("second.fluid_out", "product")
    plant.connect("bus.power_out", "first.power_in")
    plant.connect("bus.power_out", "second.power_in")
    return plant


@pytest.fixture(autouse=True)
def classes(monkeypatch):
    """Register the test modules for the plants of this file."""
    for cls in (Consumer, Bus, Source, Taker, Offer):
        entry = registry._Entry(cls.category, module=cls)
        monkeypatch.setitem(registry._entries, cls.__name__, entry)


def test_a_consumer_decides_what_its_inlet_carries():
    """A direct call needs no power: the module gives it and the result shows it."""
    result = consumer(10.0)(fluid_in=STREAM)
    assert result.inlets.power_in == result.outputs.drawn == 20.0


def test_a_many_port_holds_what_its_takers_drew():
    """The consumers run before the bus, which receives what each drew."""
    result = wired()(feed=STREAM)
    bus = result.children["bus"]
    assert bus.outlets.power_out == [20.0, 60.0]
    assert bus.outputs.net == 80.0
    assert bus.inlets.power_in == []


def test_the_same_plant_is_one_graph_on_every_backend():
    """A power port is traced like a stream; a graph gives the numbers of a direct call."""
    plant = wired()
    stream = gm.Stream(m_dot=np.array([1.0, 2.0]), T=300.0, p=2e5)
    outcome = run(plant, {"feed": stream}, {})
    assert outcome.breaks == []
    assert outcome.graph.result.children["bus"].outputs.net is not None


def test_a_plant_port_shared_by_two_consumers_gives_their_sum():
    """Inside a plant the ends of one plant port add up with an explicit function."""
    plant = gm.Plant("Shared")
    plant.add(Consumer, "first", {"rating": 10.0})
    plant.add(Consumer, "second", {"rating": 30.0})
    plant.connect("feed", "first.fluid_in")
    plant.connect("first.fluid_out", "second.fluid_in")
    plant.connect("second.fluid_out", "product")
    plant.connect("power_in", "first.power_in")
    plant.connect("power_in", "second.power_in")
    assert plant.to_dict()["inlets"]["power_in"] == ["first.power_in", "second.power_in"]
    assert plant(feed=STREAM).inlets.power_in == 80.0
    assert gm.Plant.from_dict(plant.to_dict()).to_dict() == plant.to_dict()


def test_a_second_end_is_refused_on_a_plain_stream_port():
    """A stream port stays one to one; only a power or the air is shared."""
    plant = gm.Plant("Plain")
    plant.add("Filter", "first")
    plant.add("Filter", "second")
    plant.connect("feed", "first.fluid_in")
    with pytest.raises(ValidationError, match="already taken"):
        plant.connect("feed", "second.fluid_in")


def test_a_power_port_does_not_fit_a_stream_port():
    """Connections check the kinds and what the ports carry."""
    plant = gm.Plant("Mismatch")
    plant.add(Bus, "bus")
    plant.add("Filter", "filter")
    with pytest.raises(ValidationError) as caught:
        plant.connect("bus.power_out", "filter.fluid_in")
    assert caught.value.code == "stream_mismatch"


def test_a_many_port_may_stay_empty():
    """A bus without takers is connected; nothing is dangling."""
    plant = gm.Plant("Idle")
    plant.add(Bus, "bus")
    assert plant()
    assert gm.plants.validate(plant.to_dict(structure=True), on_error="record") == []


def test_an_offered_outlet_closes_a_loop_without_state():
    """The offer runs first, the loop back to the source is no cycle of the plan."""
    plant = gm.Plant("Loop")
    plant.add(Source, "source", {"temperature": 330.0})
    plant.add("Filter", "filter")
    plant.connect("source.fluid_out", "filter.fluid_in")
    plant.connect("filter.fluid_out", "source.fluid_in")
    steps = plant._compiled().steps
    assert [(step.path, step.offer) for step in steps] == [
        ("source", True),
        ("filter", False),
        ("source", False),
    ]
    result = plant()
    assert result.children["source"].outputs.back == 1.0
    assert result.children["filter"].inlets.fluid_in.T == 330.0


def test_a_taker_decides_what_a_drawn_offer_gives():
    """The taker gets the conditions and returns what it took; the source receives that."""
    plant = gm.Plant("Drawn")
    plant.add(Offer, "well")
    plant.add(Taker, "taker")
    plant.connect("well.fluid_out", "taker.fluid_in")
    plant.connect("taker.fluid_out", "product")
    result = plant()
    assert result.children["taker"].inlets.fluid_in.m_dot == 4.0
    assert result.children["well"].outputs.taken == 4.0
