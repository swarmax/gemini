"""The tracer records a whole module call with named inputs by role."""

import re

import numpy as np
import pytest

import gemini as gm
from gemini.compiler.graph import Tracer, run
from gemini.compiler.graph.tracer import parameter_shape
from gemini.errors import DefinitionError, PhysicsError, ValidationError
from gemini.modules.declarations import UNSET
from tests.fixtures.errors import raises


def test_trace_names_inputs_by_role_and_records_outputs(gain):
    """Inlet fields (the fluid is static), controls, parameters and constants are inputs."""
    graph = Tracer().trace(gain, {"fluid_in": gain.fluid})
    roles = {name: node.role for name, node in graph.inputs.items()}
    assert roles == {
        "fluid_in.m_dot": "inlet",
        "fluid_in.T": "inlet",
        "fluid_in.p": "inlet",
        "gain": "control",
        "scale": "parameter",
        "REFERENCE": "constant",
    }
    assert set(graph.outputs) == {
        "outlets.fluid_out.m_dot",
        "outlets.fluid_out.T",
        "outlets.fluid_out.p",
        "outputs.rise",
        "outputs.boost",
    }
    assert graph.inputs["fluid_in.p"].unit == "Pa" and graph.outlet_fluids == {
        "fluid_out": gain.fluid
    }
    assert all(node.op != "input" or node.name for node in graph.nodes)
    assert 3.0 not in [operand for node in graph.nodes for operand in node.operands]


def test_no_outputs_traces_only_the_fluid_step(gain):
    """Under ``no_outputs()`` the graph has outlet fields only."""
    with gm.modules.no_outputs():
        graph = Tracer().trace(gain, {"fluid_in": gain.fluid})
    assert all(name.startswith("outlets.") for name in graph.outputs)


def test_hooks_are_classified_by_what_they_do(gain):
    """A writing hook joins the graph; a reading one and a failing one break the root."""

    def doubles(module, inlets, outlets):
        module.boost = module.boost * 2

    def reads(module, inlets, outlets):
        return module.rise

    handle = gain.register_forward_hook(doubles)
    graph = Tracer().trace(gain, {"fluid_in": gain.fluid})
    assert not graph.root_break and graph.outputs["outputs.boost"].op == "mul"
    handle_reads = gain.register_forward_hook(reads)
    reading = Tracer().trace(gain, {"fluid_in": gain.fluid})
    assert reading.root_break and "only reads and runs on real values" in reading.breaks[0][1]
    handle.remove()
    handle_reads.remove()
    gain.register_forward_hook(lambda module, inlets, outlets: float(module.rise))
    broken = Tracer().trace(gain, {"fluid_in": gain.fluid})
    assert broken.root_break and re.search("forward hook .*float", broken.breaks[0][1])


def test_unassigned_outputs_fail_at_trace_time(gain):
    """``_check_outputs`` runs once during the trace."""

    class Forgetful(type(gain)):
        def forward(self, inlets):
            self.rise = 0.0
            return dict(fluid_out=inlets.fluid_in)

    module = Forgetful().set_params("", {"scale": 1.0})
    with pytest.raises(DefinitionError, match="boost"):
        Tracer().trace(module, {"fluid_in": module.fluid})


def test_untraceable_modules_name_every_reason(gain, tank):
    """Stateful modules, pre-hooks and float32 precision make the root a break, never an error."""
    graph = Tracer().trace(tank, {"fluid_in": gain.fluid})
    assert graph.root_break and "stateful" in graph.breaks[0][1]
    gain.register_forward_pre_hook(lambda module, inlets: None)
    with gm.runtime.settings(precision="float32"):
        graph = Tracer().trace(gain, {"fluid_in": gain.fluid})
    assert graph.root_break and "pre-hooks; runtime precision" in graph.breaks[0][1]


def test_parameter_shapes():
    """Numbers are scalars, numeric sequences vectors and anything else a guard."""
    assert parameter_shape(2) == () and parameter_shape([1.0, 2.0]) == (2,)
    assert parameter_shape(True) is None and parameter_shape("x") is None
    assert parameter_shape(None) is None and parameter_shape([]) is None


def test_a_stream_built_in_forward_traces_and_keeps_its_limits(gain):
    """Building a ``Stream`` from traced values records its limit checks as ``ops.check``."""

    class Drop(type(gain)):
        def forward(self, inlets):
            inlet = inlets.fluid_in
            drop = self.gain * 1e6
            self.rise = -drop
            self.boost = 0.0
            return {
                "fluid_out": gm.Stream(
                    m_dot=inlet.m_dot, T=inlet.T, p=inlet.p - drop, fluid=inlet.fluid
                )
            }

    module = Drop().set_params("", {"scale": 1.0})
    graph = Tracer().trace(module, {"fluid_in": module.fluid})
    assert any(node.op == "check" for node in graph.nodes)
    stream = gm.Stream(
        m_dot=gm.units.Quantity(np.array([1.0, 1.0]), "kg/s"),
        T=gm.units.Quantity(300.0, "K"),
        p=gm.units.Quantity(np.array([2e5, 1e5]), "Pa"),
    )
    assert run(module, {"fluid_in": stream}, {"gain": 0.0}).outlets["fluid_out"]["p"].tolist() == [
        2e5,
        1e5,
    ]
    with pytest.raises(PhysicsError, match="p = -800000.0 Pa"):
        run(module, {"fluid_in": stream}, {"gain": 1.0})


def test_composite_inputs_are_named_by_relative_path(line):
    """Child controls, boundaries and parameters are prefixed; the root's are not."""
    graph = Tracer().trace(line, {"fluid_in": line.fluid})
    roles = {name: node.role for name, node in graph.inputs.items()}
    assert roles == {
        "fluid_in.m_dot": "inlet",
        "fluid_in.T": "inlet",
        "fluid_in.p": "inlet",
        "boost": "control",
        "first.scale": "parameter",
        "gain.scale": "parameter",
        "REFERENCE": "constant",
        "second.draw": "control",
        "second.scale": "parameter",
    }
    assert list(graph.outputs)[3:] == [
        "outputs.rise",
        "outputs.pressure",
        "outputs.electricity",
        "outputs.efficiency",
    ]


def test_a_child_called_twice_reuses_its_inputs(twice):
    """The second call finds the first call's graph inputs."""
    graph = Tracer().trace(twice, {"fluid_in": twice.fluid})
    assert [name for name in graph.inputs if name.startswith("gain")] == ["gain.gain", "gain.scale"]


def test_composite_without_outputs_traces_the_fluid_step(line):
    """Under ``no_outputs()`` a composite graph has outlet fields only."""
    with gm.modules.no_outputs():
        graph = Tracer().trace(line, {"fluid_in": line.fluid})
    assert all(name.startswith("outlets.") for name in graph.outputs)


def test_uninitialized_parameters_of_the_tree_are_refused(line):
    """A parameter without a value anywhere below the root cannot be traced."""
    line.gain._parameters["scale"].value = UNSET
    with raises(ValidationError, "missing_value", match="line: uninitialized parameters"):
        Tracer().trace(line, {"fluid_in": line.fluid})


def test_a_reading_hook_on_a_leaf_child_makes_it_a_break_node(line):
    """An unmarked hook that only reads cannot be replayed, so the leaf child runs untraced."""
    line.gain.register_forward_hook(lambda module, inlets, outlets: module.rise)
    graph = Tracer().trace(line, {"fluid_in": line.fluid})
    assert [path for path, _ in graph.breaks] == ["gain"]
    assert "only reads" in graph.breaks[0][1]


def test_writing_hooks_on_a_child_join_the_graph(line):
    """A hook that writes an output of a child is part of the graph."""

    def doubles(module, inlets, outlets):
        module.rise = module.rise * 2

    line.gain.register_forward_hook(doubles)
    inlet = gm.Stream(
        m_dot=gm.units.Quantity(np.ones(3), "kg/s"),
        T=gm.units.Quantity(np.full(3, 300.0), "K"),
        p=gm.units.Quantity(np.full(3, 1e5), "Pa"),
        fluid=line.fluid,
    )
    result = run(line, {"fluid_in": inlet}, {"boost": np.array([1.0, 2.0, 3.0])})
    assert result.graph is not None
    assert result.outputs["rise"].tolist() == [12.0, 24.0, 36.0]
