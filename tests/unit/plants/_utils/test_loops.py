"""Closing a loop: Wegstein's iteration on the tear stream of a plant."""

import numpy as np
import pytest

import gemini as gm
from gemini import ops, runtime
from gemini.compiler.graph.tracer import Tracer
from gemini.modules import CirculationPump, Module
from gemini.modules.declarations import Inlet, Outlet, Output
from gemini.modules.storage import ThermalStorage
from gemini.ops.failures import failures_of, marking
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
    flow = None

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
        if self.flow is not None:
            outlet = outlet.with_(m_dot=self.flow)

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


def test_a_tear_stream_without_flow_has_no_temperature_to_converge():
    """A limit may hold the iterate away from the image: at no flow that carries no energy."""
    tear = loops._Tear(gm.Stream(m_dot=0.0, T=350.0, p=1e5, fluid=gm.WATER), None, 360.0)
    image = gm.Stream(m_dot=0.0, T=373.15, p=2e5, fluid=gm.WATER)
    assert tear.advance(image, 1e-9, True)


def test_a_tear_stream_with_flow_still_converges_on_every_field():
    """Only a stream that stands still gives up its temperature."""
    tear = loops._Tear(gm.Stream(m_dot=1.0, T=350.0, p=1e5, fluid=gm.WATER), None, 360.0)
    assert not tear.advance(gm.Stream(m_dot=1.0, T=373.15, p=1e5, fluid=gm.WATER), 1e-9, True)


class Curved(Relaxer):
    """A relaxer with a saturating rule, so the loop needs several accelerated steps."""

    abstract = True
    scale = 20.0

    def forward(self, inlets):
        """Move towards the target along a ``tanh``, ``slope`` times as far."""
        inlet = inlets.fluid_in
        step = np.tanh((inlet.T - self.target) / self.scale) * self.scale
        outlet = inlet.with_(T=self.target + self.slope * step * 1.9)
        if self.flow is not None:
            outlet = outlet.with_(m_dot=self.flow)
        self.drop = inlet.T - outlet.T
        return dict(fluid_out=outlet)


ROWS = {
    "slope": np.array([0.5, 0.5, 0.9, 0.5, 0.5, 0.7]),
    "target": np.array([340.0, 300.0, 350.0, 340.0, 320.0, 310.0]),
    "start": np.array([300.0, 300.0, 280.0, 300.0, 400.0, 500.0]),
    "flow": np.array([2.0, 2.0, 3.0, 0.0, 2.0, 1.0]),
    "upper": np.array([1e3, 1e3, 1e3, 1e3, 330.0, 1e3]),
}


def _ring(rows, curved=False, **rule):
    """Return the circuit of the ``rows`` of ``ROWS``: a float each, or the arrays themselves."""
    attributes = {name: rows[name] for name in ("slope", "target", "start", "flow")}
    attributes |= {"limits": (None, rows["upper"]), "abstract": True} | rule
    base = Curved if curved else Relaxer
    relaxer = type("Rule", (base,), attributes)
    return type("Ring", (Circuit,), {"relaxer_class": relaxer})()


def _row(row):
    return {name: values[row].item() for name, values in ROWS.items()}


def _answer(plant):
    result = plant()
    tear = result.children["pump"].inlets.fluid_in
    return np.array([tear.m_dot, tear.T, tear.p]), result.children["relaxer"].outputs.drop


@pytest.mark.parametrize("curved", [False, True], ids=["linear", "curved"])
def test_an_array_loop_gives_the_numbers_of_each_row_alone(curved):
    """Rows that settle early, late, at zero flow or against a limit keep their own iterates."""
    tear, drop = _answer(_ring(ROWS, curved))
    for row in range(len(ROWS["slope"])):
        alone, alone_drop = _answer(_ring(_row(row), curved))
        assert tear[:, row].tolist() == alone.tolist()
        assert drop[row] == alone_drop


@ops.physics
def _cooled(temperature, target):
    """Return a temperature half way to the target, which has to be positive."""
    ops.check(target > 0, gm.errors.PhysicsError, "relaxer: target = {target} K", target=target)
    return 0.5 * temperature + 0.5 * target


class Guarded(Relaxer):
    """A relaxer whose rule is a physics function that refuses a negative target."""

    abstract = True

    def forward(self, inlets):
        """Move half way to the target."""
        outlet = inlets.fluid_in.with_(T=_cooled(inlets.fluid_in.T, self.target))
        self.drop = inlets.fluid_in.T - outlet.T
        return dict(fluid_out=outlet)


def _guarded(target):
    start = np.full(target.shape, 300.0) if np.ndim(target) else 300.0
    attributes = {"abstract": True, "target": target, "start": start}
    return type("Ring", (Circuit,), {"relaxer_class": type("Rule", (Guarded,), attributes)})()


def test_a_row_that_fails_a_check_in_a_pass_fails_as_alone_and_the_others_survive():
    """The failing row is marked with the error of its own call; the others keep their numbers."""
    targets = np.array([340.0, -5.0, 320.0])
    with marking():
        tear = _guarded(targets)().children["relaxer"].outlets.fluid_out.T
    failures = failures_of(tear)
    assert failures.mask.tolist() == [False, True, False]
    with raises(gm.errors.PhysicsError, "out_of_range", match="target = -5.0 K") as alone:
        _guarded(-5.0)()
    assert str(failures.error(1)) == str(alone.value)
    assert tear[[0, 2]].tolist() == [
        _guarded(340.0)().children["pump"].inlets.fluid_in.T,
        _guarded(320.0)().children["pump"].inlets.fluid_in.T,
    ]


def test_a_row_that_does_not_converge_is_marked_with_its_own_temperature():
    """Rows that close keep their results; the one that drifts gets ``loop_not_converged``."""
    drift = np.array([0.0, 1.0, 0.0])
    relaxer = type(
        "Drifting", (Relaxer,), {"forward": _drifting_by, "abstract": True, "drift": drift}
    )
    plant = type("Ring", (Circuit,), {"relaxer_class": relaxer, "loop_passes": 4})()
    with marking():
        tear = plant().children["pump"].inlets.fluid_in.T
    failures = failures_of(tear)
    assert failures.mask.tolist() == [False, True, False]
    error = failures.error(1)
    assert error.code == "loop_not_converged" and error.path == "relaxer.fluid_out"
    alone = type(
        "Ring",
        (Circuit,),
        {
            "relaxer_class": type(
                "D", (Relaxer,), {"forward": _drifting_by, "abstract": True, "drift": 1.0}
            ),
            "loop_passes": 4,
        },
    )()
    with raises(gm.errors.PhysicsError, "loop_not_converged") as caught:
        alone()
    assert str(error) == str(caught.value)


def _drifting_by(self, inlets):
    """Warm the stream by ``drift`` kelvin on every pass."""
    outlet = inlets.fluid_in.with_(T=inlets.fluid_in.T + self.drift)
    self.drop = -self.drift
    return dict(fluid_out=outlet)


@ops.physics
def _watched(temperature):
    """Return the temperature, which must be outside the window of 310 to 330 K."""
    inside = ops.logical_and(temperature > 310.0, temperature < 330.0)
    ops.check(
        ops.logical_not(inside),
        gm.errors.PhysicsError,
        "probe: T = {temperature} K",
        temperature=temperature,
    )
    return temperature


class Probed(Relaxer):
    """A relaxer with a second outlet, checked in the window and connected to nothing."""

    abstract = True

    def __init__(self):
        """Declare the second outlet."""
        super().__init__()
        self.return_out = Outlet(Stream)

    def forward(self, inlets):
        """Relax as the base class does and probe the entering temperature on the side."""
        outlets = super().forward(inlets)
        outlets["return_out"] = inlets.fluid_in.with_(T=_watched(inlets.fluid_in.T))
        return outlets


class ProbedCircuit(Circuit):
    """The circuit with the side outlet of its relaxer named a port of the plant."""

    def __init__(self):
        """Name the side outlet."""
        super().__init__()
        self.return_out = Outlet(Stream)
        self.connect("relaxer.return_out", "return_out")


def _probed(target):
    start = np.full(target.shape, 300.0) if np.ndim(target) else 300.0
    attributes = {"abstract": True, "target": target, "start": start}
    relaxer = type("Rule", (Probed,), attributes)
    return type("Ring", (ProbedCircuit,), {"relaxer_class": relaxer})()


def test_a_row_that_fails_in_a_step_off_the_tear_at_a_passing_iterate_fails_as_alone():
    """The row fails at the pass its check fails, though its converged iterate would pass."""
    targets = np.array([340.0, 300.0, 340.0, 360.0])
    with marking():
        side = _probed(targets)().outlets.return_out.T
    failures = failures_of(side)
    assert failures is not None
    errors = {}
    for row, target in enumerate(targets.tolist()):
        try:
            _probed(target)()
        except gm.errors.PhysicsError as error:
            errors[row] = error
    assert failures.mask.tolist() == [row in errors for row in range(4)]
    assert errors
    for row, error in errors.items():
        assert type(failures.error(row)) is type(error) and str(failures.error(row)) == str(error)
        assert failures.error(row).code == error.code


@ops.physics
def _bounded(temperature):
    """Return the temperature, which must be at least 325 K."""
    ops.check(
        temperature >= 325.0,
        gm.errors.PhysicsError,
        "bound: T = {temperature} K",
        temperature=temperature,
    )
    return temperature


class DoubleProbed(Probed):
    """A relaxer that also fails a second check on the side outlet, after the first."""

    abstract = True

    def forward(self, inlets):
        """Probe the window, then the bound."""
        outlets = super().forward(inlets)
        bound = _bounded(inlets.fluid_in.T)
        outlets["return_out"] = outlets["return_out"].with_(p=bound * 1e3)
        return outlets


def test_a_row_that_fails_two_checks_in_a_pass_reports_the_first_as_alone():
    """From 320 K the window check runs first and fails first, as alone, not the bound."""
    attributes = {"abstract": True, "target": np.array([340.0, 340.0]), "start": np.full(2, 320.0)}
    relaxer = type("Rule", (DoubleProbed,), attributes)
    with marking():
        side = type("Ring", (ProbedCircuit,), {"relaxer_class": relaxer})()().outlets.return_out.T
    failures = failures_of(side)
    alone = type("Rule", (DoubleProbed,), {"abstract": True, "target": 340.0, "start": 320.0})
    with pytest.raises(gm.errors.PhysicsError, match="probe") as caught:
        type("Ring", (ProbedCircuit,), {"relaxer_class": alone})()()
    assert str(failures.error(0)) == str(caught.value) and "probe" in str(failures.error(1))
