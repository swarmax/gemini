"""Closing a loop: Wegstein's iteration on the tear stream of a plant."""

import pytest

import gemini as gm
from gemini import runtime
from gemini.compiler.graph.tracer import Tracer
from gemini.modules import CirculationPump, Module
from gemini.modules.declarations import Inlet, Outlet, Output
from gemini.modules.storage import ThermalStorage
from gemini.plants._utils import loops
from gemini.plants._utils.plan import Loop
from gemini.plants.plant import Plant
from gemini.types import Stream
from tests.fixtures.errors import raises
from tests.fixtures.parity import BACKENDS

STREAM = Stream(m_dot=1.0, T=300.0, p=1e5)


class Relaxer(Module):
    """Move the temperature towards a target: ``T_out = slope T_in + (1 - slope) target``."""

    category = "exchangers"

    abstract = True
    slope = 0.5
    target = 340.0
    start = 300.0
    limits = (None, None)

    def __init__(self):
        """Declare the circuit ports and the count of the calls."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outputs
        self.drop = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Relax the temperature; the rule of the class is linear, as an exchanger is."""

        # Outlets
        inlet = inlets.fluid_in
        outlet = inlet.with_(T=self.slope * inlet.T + (1 - self.slope) * self.target)

        # Outputs
        self.drop = inlet.T - outlet.T

        outlets = dict(fluid_out=outlet)
        return outlets

    def _loop_start(self, port, entering):
        return self.start

    def _loop_limits(self, inlets):
        return self.limits


class Circuit(Plant):
    """A closed circuit of a pump and one relaxer."""

    relaxer_class = Relaxer

    def __init__(self):
        """Connect the pump and the relaxer in a ring."""
        super().__init__()

        # Modules
        self.pump = CirculationPump()
        self.relaxer = self.relaxer_class()

        # Inlets
        self.power_in = Inlet(gm.types.Power, kind="electricity")

        # Outlets
        self.loss_out = Outlet(gm.types.Power, kind="heat")

        # Connections
        self.connect("power_in", "pump.power_in")
        self.connect("pump.loss_out", "loss_out")
        self.connect("relaxer.fluid_out", "pump.fluid_in")
        self.connect("pump.fluid_out", "relaxer.fluid_in")
        self.pump.set_params("", {"flow": 2.0, "pressure_rise": 1e4, "loop_pressure": 2e5})


def circuit(**rule):
    """Return a circuit whose relaxer follows ``rule``."""
    relaxer = type("Rule", (Relaxer,), rule | {"abstract": True})
    return type("Ring", (Circuit,), {"relaxer_class": relaxer})()


def test_a_linear_pass_closes_at_its_fixed_point():
    """One accelerated step lands on a linear pass, and flow and pressure close too."""
    plant = circuit()
    assert isinstance(plant._compiled().items[0], Loop)
    result = plant()
    temperature = result.children["pump"].inlets.fluid_in
    assert temperature.T == pytest.approx(340.0, abs=1e-9)
    assert temperature.m_dot == 2.0 and temperature.p == 2e5


def test_the_tear_is_the_outlet_of_the_module_that_gives_a_first_guess():
    """The relaxer guesses; the connection into the pump is cut, not the last one listed."""
    tear = circuit()._compiled().items[0].tears[0]
    assert tear.source == ("relaxer", "fluid_out") and tear.target == ("pump", "fluid_in")


def test_every_module_is_called_once_for_the_record():
    """Trial passes are invisible: each child has one call and the outputs of the last pass."""
    result = circuit()()
    assert list(result.children) == ["pump", "relaxer"]
    assert result.children["relaxer"].outputs.drop == pytest.approx(0.0, abs=1e-9)


def test_the_iterate_stays_within_the_limits_of_the_modules():
    """A module that must not reverse clamps the temperature, also the first guess."""
    plant = circuit(start=400.0, limits=(None, 330.0), target=320.0)
    assert plant().children["pump"].inlets.fluid_in.T == pytest.approx(320.0, abs=1e-9)


def test_a_loop_that_does_not_converge_names_its_tear():
    """A pass that keeps moving raises ``PhysicsError`` with the code and the tear path."""
    relaxer = type("Drifting", (Relaxer,), {"forward": _drifting, "abstract": True})
    plant = type("Ring", (Circuit,), {"relaxer_class": relaxer})()
    with raises(gm.errors.PhysicsError, "loop_not_converged") as caught:
        plant()
    assert caught.value.path == "relaxer.fluid_out"


def _drifting(self, inlets):
    """Warm the stream by 1 K on every pass, so no temperature maps to itself."""
    outlet = inlets.fluid_in.with_(T=inlets.fluid_in.T + 1.0)
    self.drop = -1.0
    return dict(fluid_out=outlet)


def test_the_settings_are_on_the_plant():
    """The tolerance and the passes keep the values of before and a plant may change them."""
    assert (Plant.loop_tolerance, Plant.loop_passes) == (1e-9, 50)
    plant = circuit(slope=0.9)
    plant.loop_passes = 1
    with raises(gm.errors.PhysicsError, "loop_not_converged"):
        plant()


def test_a_loop_without_a_first_guess_says_so():
    """No module can start the iteration: the error names the tear."""
    with raises(gm.errors.ValidationError, "invalid_design", match="no first guess"):
        circuit(start=None)()


def test_a_stateful_module_in_a_trial_is_refused():
    """A stateful module would be evaluated at its initial states."""
    with raises(
        gm.errors.ValidationError, "invalid_design", match="stateless module for a trial call"
    ):
        ThermalStorage()._trial()


def test_a_trial_keeps_the_runtime_settings_and_is_not_recorded():
    """A trial runs with the caller's settings and joins no running call."""

    with gm.runtime.settings(precision="float32"):
        assert runtime.get_precision() == "float32"
        assert Relaxer()._trial(fluid_in=STREAM).outlets.fluid_out.T == 320.0


def test_a_loop_runs_the_same_on_every_backend():
    """A plant that iterates is a root break: the same calls row by row on every backend."""
    plant = circuit()
    graph = Tracer().trace(plant, {})
    assert graph.root_break and "closes a loop" in graph.breaks[0][1]
    results = {}
    for backend in BACKENDS:
        with runtime.settings(backend=backend):
            results[backend] = gm.call(plant, {}, {}, {})
    assert all(result == results[BACKENDS[0]] for result in results.values())


@pytest.mark.parametrize(
    ("current", "image", "previous", "previous_image", "expected"),
    [
        (10.0, 20.0, None, None, 20.0),
        (10.0, 20.0, 10.0, 15.0, 20.0),
        (10.0, 15.0, 0.0, 10.0, 20.0),
        (10.0, 30.0, 0.0, 10.0, 30.0),
    ],
)
def test_wegstein_accelerates_a_slope_below_one(current, image, previous, previous_image, expected):
    """No history is substitution, a slope of one or more too, otherwise the secant root."""
    assert loops.proposal(current, image, previous, previous_image) == expected


def test_a_tear_stream_without_flow_has_no_temperature_to_converge():
    """A limit may hold the iterate away from the image: at no flow that carries no energy."""
    tear = loops._Tear(gm.Stream(m_dot=0.0, T=350.0, p=1e5, fluid=gm.WATER), None, 360.0)
    image = gm.Stream(m_dot=0.0, T=373.15, p=2e5, fluid=gm.WATER)
    assert tear.advance(image, 1e-9)


def test_a_tear_stream_with_flow_still_converges_on_every_field():
    """Only a stream that stands still gives up its temperature."""
    tear = loops._Tear(gm.Stream(m_dot=1.0, T=350.0, p=1e5, fluid=gm.WATER), None, 360.0)
    assert not tear.advance(gm.Stream(m_dot=1.0, T=373.15, p=1e5, fluid=gm.WATER), 1e-9)
