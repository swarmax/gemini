"""A loop is a graph construct: the compiled plant gives the numbers and errors of each row."""

import numpy as np
import pytest

import gemini as gm
from gemini import ops, runtime
from gemini.compiler.graph import GraphCache, evaluate, graph_feeds
from gemini.errors import PhysicsError
from gemini.modules import CirculationPump, Module
from gemini.modules.declarations import Control, Inlet, Outlet, Output
from gemini.plants.plant import Plant
from gemini.types import Stream
from tests.fixtures.engine_plants import loop_plant

ROWS = 6
TARGETS = np.array([340.0, 300.0, 350.0, 320.0, 310.0, 330.0])
SLOPES = np.array([0.5, 0.5, 0.9, 0.5, 0.7, 0.5])
FLOWS = np.array([2.0, 2.0, 3.0, 0.0, 1.0, 2.0])
UPPERS = np.array([1e3, 1e3, 1e3, 1e3, 335.0, 1e3])


@ops.physics
def _watched(temperature):
    """Return the temperature, which must be outside the window of 315 to 325 K."""
    inside = ops.logical_and(temperature > 315.0, temperature < 325.0)
    ops.check(
        ops.logical_not(inside),
        PhysicsError,
        "probe: T = {temperature} K",
        temperature=temperature,
    )
    return temperature


class Relaxer(Module):
    """Move the temperature towards a target at a flow; the controls make a row each."""

    category = "exchangers"
    abstract = True

    def __init__(self):
        """Declare the controls, the inlet and the outlet."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.target = Control(float)
        self.slope = Control(float, default=0.5)
        self.flow = Control(float, default=2.0)
        self.upper = Control(float, default=1e3)

        # Outputs
        self.drop = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Relax the temperature, linearly, and set the flow."""

        # Outlets
        inlet = inlets.fluid_in
        temperature = self.slope * inlet.T + (1 - self.slope) * self.target
        outlet = inlet.with_(T=temperature, m_dot=self.flow)
        outlets = dict(fluid_out=outlet)

        # Outputs
        self.drop = inlet.T - outlet.T
        return outlets

    def _loop_start(self, port, entering):
        return 300.0

    def _loop_limits(self, inlets):
        return None, self.upper


class Watching(Relaxer):
    """A relaxer that refuses the window of 315 to 325 K for the temperature that enters."""

    abstract = True

    def forward(self, inlets):
        """Probe the entering temperature, then relax."""
        ops.require(_watched(inlets.fluid_in.T))
        return super().forward(inlets)


class Circuit(Plant):
    """A pump and a relaxer in a closed circuit; the plant has no inlet."""

    abstract = True
    relaxer_class = Relaxer
    loop_passes = 50

    def __init__(self):
        """Connect the pump and the relaxer in a ring."""
        super().__init__()

        # Modules
        self.pump = CirculationPump()
        self.relaxer = self.relaxer_class()

        # Inlets
        self.power_in = gm.modules.declarations.Inlet(gm.types.Power, kind="electricity")

        # Outlets
        self.loss_out = gm.modules.declarations.Outlet(gm.types.Power, kind="heat")

        # Connections
        self.connect("power_in", "pump.power_in")
        self.connect("pump.loss_out", "loss_out")
        self.connect("relaxer.fluid_out", "pump.fluid_in")
        self.connect("pump.fluid_out", "relaxer.fluid_in")
        self.pump.set_params("", {"flow": 2.0, "pressure_rise": 1e4, "loop_pressure": 2e5})


class Drifting(Relaxer):
    """A relaxer whose pass warms the stream by the ``target`` kelvin: it never settles."""

    abstract = True

    def forward(self, inlets):
        """Warm the stream by ``target`` K per pass."""
        outlet = inlets.fluid_in.with_(T=inlets.fluid_in.T + self.target)
        self.drop = -self.target
        return dict(fluid_out=outlet)


_RINGS = {}


def _circuit(cls=Relaxer, passes=50):
    ring = _RINGS.setdefault(
        cls, type("Ring", (Circuit,), {"relaxer_class": cls, "abstract": True})
    )
    plant = ring()
    plant.loop_passes = passes
    return plant


def _inputs(*columns):
    names = {"target": TARGETS, "slope": SLOPES, "flow": FLOWS, "upper": UPPERS}
    return {f"relaxer.{name}": names[name] for name in columns}


def _compiled(plant, inputs, rows=ROWS, backend=None, cache=None):
    graph = (cache or GraphCache()).graph(plant, {})
    feeds = graph_feeds(graph, plant, {}, inputs)
    with runtime.settings(backend=backend):
        return graph, evaluate(graph, feeds, rows, module=plant)


def _alone(plant, inputs, row):
    for name, values in inputs.items():
        owner, _, local = name.rpartition(".")
        setattr(plant.get_submodule(owner), local, float(values[row]))
    return plant()


def _tear(result):
    stream = result.children["pump"].inlets.fluid_in
    return np.array([stream.m_dot, stream.T, stream.p])


FULL = _inputs("target", "slope", "flow", "upper")


@pytest.mark.parametrize("backend", [None, "python"])
def test_a_loop_traces_without_a_break_and_gives_the_numbers_of_each_row_alone(backend):
    """Rows that settle early, late, at zero flow or against a limit equal the rows alone."""
    plant = _circuit()
    graph, evaluation = _compiled(plant, FULL, backend=backend)
    assert not graph.root_break and graph.breaks == [] and not evaluation.failed.any()
    for row in range(ROWS):
        alone = _alone(_circuit(), FULL, row)
        found = _tear(evaluation.result)[:, row]
        assert found == pytest.approx(_tear(alone), rel=1e-9, abs=1e-9)
        drop = evaluation.result.children["relaxer"].outputs.drop[row]
        assert drop == pytest.approx(alone.children["relaxer"].outputs.drop, abs=1e-9)


def test_the_backends_agree_on_a_loop():
    """The python backend runs the iteration row by row with the numbers of the arrays."""
    fast = _compiled(_circuit(), FULL)[1].result
    slow = _compiled(_circuit(), FULL, backend="python")[1].result
    assert _tear(fast) == pytest.approx(_tear(slow), rel=1e-12, abs=1e-12)


def test_every_module_has_one_call_in_the_result_and_the_passes_leave_no_record():
    """Only the last pass is recorded, so the outputs and the results see one call each."""
    graph, evaluation = _compiled(_circuit(), FULL)
    assert list(evaluation.result.children) == ["pump", "relaxer"]
    assert [name for name, _ in evaluation.result.call_records] == ["pump", "relaxer"]


def test_the_graph_lists_the_loop_construct():
    """The readable form shows the fixed point, its body and the converged tear fields."""
    graph = GraphCache().graph(_circuit(), {})
    text = graph.describe()
    assert "fixed_point" in text and "carry" in text and "loop_output" in text


def test_a_row_that_fails_at_an_iterate_stops_there_with_the_error_of_its_call():
    """A check that fails at an iterate fails the row as alone; the other rows are unharmed."""
    plant = _circuit(Watching)
    inputs = {"relaxer.target": np.array([340.0, 300.0, 340.0, 360.0])}
    graph, evaluation = _compiled(plant, inputs, rows=4)
    errors = {}
    for row in range(4):
        try:
            _alone(_circuit(Watching), inputs, row)
        except PhysicsError as error:
            errors[row] = error
    assert errors and evaluation.failed.tolist() == [row in errors for row in range(4)]
    for row, error in errors.items():
        assert type(evaluation.error(row)) is type(error)
        assert str(evaluation.error(row)).split("\n")[0] == str(error).split("\n")[0]
        assert evaluation.error(row).code == error.code


def test_a_row_that_does_not_converge_has_its_own_temperature_in_the_message():
    """Rows that close keep their numbers; the one that drifts is ``loop_not_converged``."""
    plant = _circuit(Drifting, passes=4)
    inputs = {"relaxer.target": np.array([0.0, 1.0, 0.0])}
    graph, evaluation = _compiled(plant, inputs, rows=3)
    assert evaluation.failed.tolist() == [False, True, False]
    with pytest.raises(PhysicsError) as alone:
        _alone(_circuit(Drifting, passes=4), inputs, 1)
    error = evaluation.error(1)
    assert (
        error.code == "loop_not_converged"
        and str(error).split("\n")[0] == str(alone.value).split("\n")[0]
    )


def test_two_copies_with_other_parameters_share_one_trace():
    """The tolerance and the passes are in the key; controls and parameters are inputs."""
    cache = GraphCache()
    first = _circuit()
    second = _circuit()
    second.pump.set_params("", {"flow": 3.0})
    one, _ = _compiled(first, FULL, cache=cache)
    two, other = _compiled(second, FULL, cache=cache)
    assert one is two and cache.traces == 1
    assert _tear(other.result)[0, 0] == 3.0 or _tear(other.result)[0, 0] == 2.0
    changed = _circuit(passes=7)
    assert cache.graph(changed, {}) is not one and cache.traces == 2


def test_a_constraint_plant_is_still_a_root_break(monkeypatch):
    """A solve needs a scan: its root is called row by row."""
    plant = gm.plants.get("BoilerChpPlant")
    monkeypatch.setattr(type(plant), "_missing_paths", lambda self: [])
    graph = GraphCache().graph(plant, {name: gm.WATER for name in plant._fed_inlets()})
    assert graph.root_break and "constraint" in graph.breaks[0][1]


def test_the_ring_fixture_traces_without_a_break():
    """The warmer and the carrier of the engine tests close in the graph."""
    graph = GraphCache().graph(loop_plant(), {})
    assert not graph.root_break
