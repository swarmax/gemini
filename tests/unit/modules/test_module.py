"""Registration, calls, state and output-recording contracts."""

import inspect
import math
import pickle
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import numpy as np
import pytest

import gemini as gm
from gemini import ops, runtime
from gemini.modules import Module, ModuleDict
from gemini.modules.declarations import Boundary, Control, Inlet, Outlet, Output, Parameter
from gemini.types import Electricity, Frequency, Ports, Stream
from tests.fixtures.errors import raises


class PassThrough(Module):
    """Contract fixture passing an inlet stream through unchanged."""

    def __init__(self):
        """Declare a minimal module used across registration tests."""
        super().__init__()

        # Parameters
        self.value = Parameter(float, gt=0, calibratable=True)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.multiplier = Control(float, default=1, gt=0)

        # Outputs
        self.result = Output(float, soft_sensor=True)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Record the scalar product and return the stream."""

        # Outlets
        inlet = inlets.fluid_in
        outlet = inlet

        outlets = dict(fluid_out=outlet)
        self.result = self.value * self.multiplier
        return outlets


def test_registration_construction_and_state():
    """Keyword values fill registered declarations and state reload is atomic."""
    module = PassThrough().set_params("", {"value": 2})
    assert module.value == 2
    assert dict(module.named_parameters()) == {"value": module.get("value")}
    assert [item for item in module.parameters() if item.calibratable] == [module.get("value")]
    module.value = 3
    assert module.value == 3
    state = module.state_dict()
    module.value = 4
    module.set_state_dict(state)
    assert module.value == 3
    with pytest.raises(gm.errors.ValidationError):
        module.value = -1


def test_call_output_and_signature_guards():
    """All supported inlet call forms resolve to the same fixed Ports shape."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    module = PassThrough().set_params("", {"value": 2})
    results = [
        module(fluid_in=stream, multiplier=4),
        module({"fluid_in": stream}, multiplier=4),
        module(Ports({"fluid_in": stream}), multiplier=4),
        module(stream, multiplier=4),
    ]
    assert [result.outputs.result for result in results] == [8, 8, 8, 8]
    assert all(result.outlets.fluid_out is stream for result in results)
    assert all(isinstance(result.inlets, Ports) for result in results)
    assert all(isinstance(result.outlets, Ports) for result in results)
    assert module.result.soft_sensor


def test_a_wrong_call_names_the_inlets():
    """Missing, misspelled, mixed, invalid and repeated inlets each say what is valid."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    module = PassThrough().set_params("", {"value": 2})
    with raises(
        gm.errors.ValidationError,
        "invalid_call",
        match="pass_through.*missing.*fluid_in.*valid names: fluid_in",
    ):
        module()
    with raises(
        gm.errors.ValidationError,
        "invalid_call",
        match="pass_through.*fluid_ni.*valid names.*did you mean 'fluid_in'",
    ):
        module(fluid_ni=stream)
    with raises(
        gm.errors.ValidationError,
        "invalid_call",
        match="pass_through.*cannot mix.*fluid_in.*valid names: fluid_in",
    ):
        module({"fluid_in": stream}, fluid_in=stream)
    with raises(
        gm.errors.ValidationError,
        "invalid_call",
        match="pass_through.*invalid inlet 'fluid_in'.*valid names: fluid_in",
    ):
        module(fluid_in=1)
    with raises(
        gm.errors.ValidationError,
        "invalid_call",
        match="pass_through.*multiple values.*inlet.*valid names",
    ):
        module(stream, fluid_in=stream)


def test_outlet_dict_names_and_flow_types_are_checked(monkeypatch):
    """Forward returns exactly one declared, correctly typed outlet dictionary."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    module = PassThrough().set_params("", {"value": 2})

    def scalar_forward(inlets):
        return inlets.fluid_in

    monkeypatch.setattr(module, "forward", scalar_forward)
    with pytest.raises(gm.errors.DefinitionError, match="outlet dict"):
        module(fluid_in=stream)

    monkeypatch.setattr(module, "forward", lambda inlets: {})
    with pytest.raises(gm.errors.DefinitionError, match=r"pass_through.*missing=\['fluid_out'\]"):
        module(fluid_in=stream)
    monkeypatch.setattr(module, "forward", lambda inlets: {"fluid_out": stream, "extra": stream})
    with pytest.raises(gm.errors.DefinitionError, match=r"pass_through.*extra=\['extra'\]"):
        module(fluid_in=stream)
    monkeypatch.setattr(module, "forward", lambda inlets: {"fluid_out": 1})
    with pytest.raises(
        gm.errors.DefinitionError, match="pass_through.*invalid outlet 'fluid_out'.*valid names"
    ):
        module(fluid_in=stream)


class NestedParent(Module):
    """Nested-call fixture copying its child's recorded output."""

    def __init__(self):
        """Declare one child inside a container and a copied output."""
        super().__init__()

        # Modules
        self.children_by_name = ModuleDict({"child": PassThrough().set_params("", {"value": 3})})

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outputs
        self.child_value = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Call the child and copy its recorded output."""

        # Modules
        child = self.children_by_name.child(fluid_in=inlets.fluid_in, multiplier=2)

        # Outputs
        self.child_value = child.outputs.result

        # Outlets
        outlet = child.outlets.fluid_out

        outlets = dict(fluid_out=outlet)
        return outlets


def test_output_records_are_thread_local():
    """Concurrent evaluations never share output records."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    module = PassThrough().set_params("", {"value": 2})
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(
            pool.map(lambda value: module(fluid_in=stream, multiplier=value), range(1, 9))
        )
    assert [result.outputs.result for result in values] == [2 * value for value in range(1, 9)]
    assert module.result.soft_sensor


def test_output_records_are_nested_per_call():
    """A child's call inside its parent keeps its own inputs and outputs."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    result = NestedParent()(fluid_in=stream)
    assert result.outputs.child_value == 6
    assert result.children["children_by_name.child"].outputs.result == 6
    assert NestedParent().children_by_name.child(fluid_in=stream).outputs.result == 3


def test_uninitialized_and_hooks():
    """Uninitialized parameters and hook ordering have clear behavior."""
    module = PassThrough()
    assert module.missing_parameters() == ["value"]
    with raises(gm.errors.ValidationError, "missing_value", match="uninitialized"):
        module(fluid_in=Stream(m_dot=1, T=300, p=1e5))
    module.value = 2
    calls = []
    before = module.register_forward_pre_hook(lambda module, inlets: calls.append("before"))
    after = module.register_forward_hook(lambda module, inlets, outlets: calls.append("after"))
    module(fluid_in=Stream(m_dot=1, T=300, p=1e5))
    assert calls == ["before", "after"]
    before.remove()
    after.remove()


class RequiredInputs(Module):
    """Fixture with required unit-bearing control and boundary values."""

    def __init__(self):
        """Declare one inlet, required control, required boundary and result."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.frequency = Control(Frequency, gt=0, le=60)

        # Boundaries
        self.grid_frequency = Boundary(Frequency)

        # Outputs
        self.total = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Read applied values through ordinary attributes."""

        # Outlets
        inlet = inlets.fluid_in
        outlet = inlet

        outlets = dict(fluid_out=outlet)
        self.total = self.frequency + self.grid_frequency
        return outlets


def test_input_resolution_units_bounds_and_metadata():
    """Per-call, persistent and default values resolve in order and validate as SI."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    module = RequiredInputs()
    module.frequency = {"value": 40, "unit": "Hz"}
    module.grid_frequency = 50
    assert module.get("frequency").unit == "Hz"
    assert module.get("grid_frequency").unit == "Hz"
    assert module(fluid_in=stream).outputs.total == 90
    assert module(fluid_in=stream, frequency={"value": 45, "unit": "Hz"}).outputs.total == 95
    assert module.frequency == 40
    with pytest.raises(gm.errors.ValidationError, match="frequency.*invalid control.*Hz"):
        module.frequency = {"value": 61, "unit": "Hz"}


def test_missing_input_and_unknown_keyword_errors_are_complete():
    """Missing and unknown values report path, kind, unit and valid names before forward."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    module = RequiredInputs()
    with raises(
        gm.errors.ValidationError, "missing_value", match="required_inputs.frequency.*control.*Hz"
    ):
        module(fluid_in=stream)
    module.frequency = 50
    with raises(
        gm.errors.ValidationError,
        "missing_value",
        match="required_inputs.grid_frequency.*boundary.*Hz",
    ):
        module(fluid_in=stream)
    with raises(gm.errors.ValidationError, "invalid_call", match="valid names"):
        module(fluid_in=stream, typo=1)


def test_call_inputs_and_hook_assignments_do_not_leak():
    """Context-local values survive nesting and pre-hook changes last for one call only."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    module = RequiredInputs()
    module._set_inputs({"frequency": 50, "grid_frequency": 50})
    seen = []

    def clamp(module, inlets):
        current = module
        seen.append(current.frequency)
        current.frequency = min(current.frequency, 45)

    handle = module.register_forward_pre_hook(clamp)
    assert module(fluid_in=stream).outputs.total == 95
    handle.remove()
    assert module.frequency == 50
    assert module(fluid_in=stream).outputs.total == 100
    assert seen == [50]

    class AssignInForward(RequiredInputs):
        """Fixture changing a control from inside its active forward context."""

        def forward(self, inlets):
            """Override frequency for only the current call."""

            # Outlets
            inlet = inlets.fluid_in
            outlet = inlet

            outlets = dict(fluid_out=outlet)
            self.frequency = 10
            self.total = self.frequency + self.grid_frequency
            return outlets

    assigned = AssignInForward()
    assigned._set_inputs({"frequency": 50, "grid_frequency": 50})
    assert assigned(fluid_in=stream).outputs.total == 60
    assert assigned.frequency == 50


def test_hooks_are_ordered_removable_and_observe_named_ports():
    """Hooks use named ports, preserve outlets and ignore their return value."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    replacement = stream.with_(p=2e5)
    module = PassThrough().set_params("", {"value": 2})
    calls = []

    def first_hook(module, inlets):
        calls.append(("first", module))

    def second_hook(module, inlets):
        calls.append(("second", module))

    first = module.register_forward_pre_hook(first_hook)
    second = module.register_forward_pre_hook(second_hook)

    def observe(module, inlets, outlets):
        calls.append(("post", module))
        return {"fluid_out": replacement}

    post = module.register_forward_hook(observe)
    result = module(fluid_in=stream)
    assert [name for name, _ in calls] == ["first", "second", "post"]
    assert result.outlets.fluid_out is stream
    second.remove()
    post.remove()
    first.remove()
    assert module(fluid_in=stream).outlets.fluid_out is stream
    state = module.state_dict()
    restored = PassThrough().set_params("", {"value": 1}).set_state_dict(state)
    assert not restored._pre_hooks and not restored._hooks


def test_set_inputs_uses_recursive_paths_and_suggests_mistakes():
    """Plant-wide input setting addresses leaf declarations and validates atomically."""

    class ParentInputs(Module):
        """Own one child solely to test relative input paths."""

        def __init__(self):
            """Register the child input fixture."""
            super().__init__()

            # Modules
            self.child = RequiredInputs()

        def forward(self, inlets):
            """Return no outlets for the structural fixture."""

            # Modules
            self.child(
                fluid_in=Stream(m_dot=1, T=300, p=1e5),
            )

            outlets = dict()
            return outlets

    parent = ParentInputs()
    parent._set_inputs({"child.frequency": {"value": 50, "unit": "Hz"}, "child.grid_frequency": 50})
    assert parent().children["child"].outputs.total == 100
    with raises(gm.errors.ValidationError, "unknown_name", match="did you mean 'child.frequency'"):
        parent._set_inputs({"child.frequncy": 40})


def test_hooks_require_the_fixed_signatures():
    """Hook registration rejects old by-name, variadic and defaulted signatures."""
    module = PassThrough().set_params("", {"value": 1})

    with pytest.raises(gm.errors.DefinitionError, match="forward hook.*module, inlets, outlets"):
        module.register_forward_hook(lambda module, inlet, outlet: None)
    with pytest.raises(gm.errors.DefinitionError, match="forward pre-hook.*module, inlets"):
        module.register_forward_pre_hook(lambda module: None)

    def defaulted(module, inlets, outlets=None):
        pass

    with pytest.raises(gm.errors.DefinitionError, match="forward hook.*module, inlets, outlets"):
        module.register_forward_hook(defaulted)


def test_missing_output_and_named_hook_ordering():
    """Checks run after output computation and named hooks observe completed values."""

    class MissingOutput(Module):
        """Leave one declared output unset."""

        def __init__(self):
            super().__init__()
            self.fluid_in = Inlet(Stream)
            self.value = Output(float)
            self.fluid_out = Outlet(Stream)

        def forward(self, inlets):
            outlets = dict(fluid_out=inlets.fluid_in)
            pass
            return outlets

    stream = Stream(m_dot=1, T=300, p=1e5)
    module = MissingOutput()
    with pytest.raises(gm.errors.DefinitionError, match="missing_output.*value"):
        module(fluid_in=stream)

    good = PassThrough().set_params("", {"value": 3})
    seen = []

    def observe(module, inlets, outlets):
        seen.append((module.result, inlets.fluid_in, outlets.fluid_out))

    good.register_forward_hook(observe)
    good(fluid_in=stream, multiplier=2)
    assert seen == [(6, stream, stream)]


def test_no_outputs_is_nested_thread_local_context_and_decorator():
    """The fast path skips output callbacks, formulas, hooks and output checks."""
    stream = Stream(m_dot=1, T=300, p=1e5)
    module = PassThrough().set_params("", {"value": 2})
    calls = []

    def observe(module, inlets, outlets):
        calls.append(module)

    module.register_forward_hook(observe)
    with gm.modules.no_outputs():
        assert not module(fluid_in=stream).outputs
        with gm.modules.no_outputs():
            assert not module(fluid_in=stream).outputs
        assert not module(fluid_in=stream).outputs
    assert module(fluid_in=stream).outputs.result == 2
    assert calls == [module]

    @gm.modules.no_outputs()
    def fast_call():
        return module(fluid_in=stream)

    assert not fast_call().outputs


STREAM = Stream(m_dot=1, T=300, p=1e5)


class EnergyLeaf(Module):
    """Emit a fixed electrical output while preserving a stream."""

    def __init__(self):
        """Declare one stream path and an electricity output."""
        super().__init__()
        self.fluid_in = Inlet(Stream)
        self.electricity = Output(Electricity)
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Return the inlet stream."""
        outlets = dict(fluid_out=inlets.fluid_in)
        self.electricity = 2
        return outlets


class RepeatedTotal(Module):
    """Declare a total over one leaf called twice and record none."""

    def __init__(self):
        """Declare one child and the total."""
        super().__init__()
        self.child = EnergyLeaf()
        self.electricity = Output(Electricity)

    def forward(self, inlets):
        """Call the child twice."""
        self.child(fluid_in=STREAM)
        self.child(fluid_in=STREAM)
        outlets = dict()
        return outlets


def test_a_parent_never_sums_its_children():
    """A total is read from ports: an output the parent does not set is a definition error."""
    with pytest.raises(gm.errors.DefinitionError, match="outputs left unassigned"):
        RepeatedTotal()()


def test_composite_own_value_is_recorded():
    """A composite that records its own value keeps it."""

    class Own(RepeatedTotal):
        def forward(self, inlets):
            self.electricity = 7
            return super().forward(inlets)

    assert Own()().outputs.electricity == 7


def test_forward_hook_sees_the_recorded_output():
    """Forward hooks run after the outputs are recorded and read them like any output."""
    module = EnergyLeaf()
    seen = []
    module.register_forward_hook(lambda module, inlets, outlets: seen.append(module.electricity))
    module(fluid_in=STREAM)
    assert seen == [2]


def test_unknown_member_stays_an_attribute_error():
    """``hasattr`` and ``getattr`` with a default treat the miss as before."""
    module = RepeatedTotal()
    assert not hasattr(module, "missing")
    assert getattr(module, "missing", None) is None
    with pytest.raises(AttributeError):
        module.missing


def test_unknown_member_before_super_init_has_no_registries():
    """Reading a name before ``super().__init__()`` still raises ``AttributeError``."""

    class Early(Module):
        """Reads an attribute before the base initializer."""

        def __init__(self):
            """Probe a missing name first."""
            self.probe = getattr(self, "missing", "absent")
            super().__init__()

    assert Early().probe == "absent"


def test_unknown_member_survives_pickle_and_copy():
    """The error round-trips with its message intact."""
    module = RepeatedTotal()
    with raises(gm.errors.ValidationError, "unknown_name") as caught:
        module.childd
    for clone in (pickle.loads(pickle.dumps(caught.value)), deepcopy(caught.value)):
        assert str(clone) == str(caught.value)
        assert "did you mean 'child'?" in str(clone)


def test_listings_recurse_by_default_and_ports_stay_local(fresh_plant):
    """Declaration listings use dotted paths below the module; ports are the module's own."""
    doublet = fresh_plant.doublet
    assert "esp.frequency" in doublet.controls()
    assert "reservoir.production_rate" in doublet.inputs()
    assert "esp.head" in doublet.outputs()
    assert "esp.head" in doublet.soft_sensors()
    assert "esp.stage_count" in dict(doublet.named_parameters())
    assert list(doublet.controls(recurse=False)) == []
    assert list(doublet.outputs(recurse=False)) == ["brine_cooling", "volume_imbalance"]
    assert list(doublet.inlets()) == ["return_in", "power_in"]
    assert list(doublet.outlets()) == ["supply_out"]


class Quotient(Module):
    """Divide a parameter, a control and an inlet field with plain operators."""

    def __init__(self):
        """Declare the operands of the plain divisions."""
        super().__init__()

        # Parameters
        self.numerator = Parameter(float, default=2.0)
        self.coefficients = Parameter(list[float], default=[1.0, 2.0], shape=(2,))

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.divisor = Control(float, default=0.0)

        # Outputs
        self.ratio = Output(float)
        self.finite = Output(bool)
        self.seen = Output(list[float])
        self.again = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Divide the inlet flow by the control and raise the pressure by one pascal."""
        stream = inlets.fluid_in
        self.kinds = (type(stream.m_dot), type(self.numerator), type(self.divisor))
        self.quotient = stream.m_dot / self.divisor
        outlets = dict(fluid_out=stream.with_(p=stream.p + 1.0))
        self.ratio = self.numerator / self.divisor
        self.finite = self.ratio < 1e300
        self.seen = [coefficient / self.divisor for coefficient in self.coefficients]
        self.again = self.ratio / self.divisor
        return outlets


def test_an_eager_call_divides_silently_and_returns_plain_python_values():
    """Parameters, controls and inlet fields are NumPy scalars inside; results are Python."""
    module = Quotient()
    stream = Stream(m_dot=0.0, T=300.0, p=1e5)
    result = module(fluid_in=stream)
    assert [kind.__name__ for kind in module.kinds] == ["float64"] * 3
    assert math.isinf(result.outputs.ratio) and type(result.outputs.ratio) is float
    assert type(result.outputs.finite) is bool and result.outputs.finite is False
    assert result.outputs.seen == [math.inf, math.inf]
    assert result.outputs.again == math.inf and type(result.outputs.again) is float
    assert all(type(item) is float for item in result.outputs.seen)
    assert math.isnan(module.quotient) and type(result.outlets.fluid_out.p) is float
    assert result.inlets.fluid_in is stream and type(stream.m_dot) is float
    assert type(result.inputs["divisor"]) is float
    assert "np.float64" not in str(result.outlets.fluid_out) and "np.float64" not in str(stream)


def test_a_forced_numpy_backend_keeps_plain_division_silent():
    """Ops give 0-d arrays under a forced NumPy backend; a call on them still wraps its scalars."""

    class Divider(Module):
        def __init__(self):
            super().__init__()
            self.gain = Parameter(float, default=1.0)
            self.ratio = Output(float)

        def forward(self, inlets):
            outlets = dict()
            self.ratio = ops.where(self.gain > 2.0, self.gain / 0.0, ops.add(self.gain, 1.0))
            return outlets

    with runtime.settings(backend="numpy"):
        assert Divider()().outputs.ratio == 2.0


def _rows_stream(flows):
    return Stream(m_dot=np.array(flows), T=np.full(len(flows), 300.0), p=np.full(len(flows), 1e5))


class ColumnOutputs(Module):
    """Outputs that hold the rows of an array call: a list of arrays and an optional with NaN."""

    def __init__(self):
        """Declare an inlet and the outputs."""
        super().__init__()
        self.fluid_in = Inlet(Stream)
        self.sections = Output(list[float])
        self.share = Output(float | None)

    def forward(self, inlets):
        """Record a list of columns and a share that is ``None`` where the level is zero."""
        level = inlets.fluid_in.m_dot
        self.sections = [level + 1.0, level * 2.0]
        self.share = ops.where(level > 0, 1.0 / ops.maximum(level, 1e-9), None)
        return dict()


def test_an_array_call_validates_the_rows_of_a_list_and_a_nan_that_stands_for_none():
    """Each row is accepted as a row call accepts it: lists of columns and NaN of ``X | None``."""
    result = ColumnOutputs()(fluid_in=_rows_stream([0.0, 2.0, 2.0]))
    assert result.outputs.share[1] == 0.5 and np.isnan(result.outputs.share[0])
    assert [item.tolist() for item in result.outputs.sections] == [[1.0, 3.0, 3.0], [0.0, 4.0, 4.0]]


def test_an_array_call_refuses_the_row_a_row_call_refuses():
    """A row of a list output that is not valid fails the call, as in the row call."""

    class Refusing(ColumnOutputs):
        def forward(self, inlets):
            self.sections = [inlets.fluid_in.m_dot, "text"]
            return dict()

    with pytest.raises(gm.errors.ValidationError):
        Refusing()(fluid_in=_rows_stream([1.0, 2.0]))


PUBLIC_METHODS = {
    "named_modules",
    "modules",
    "children",
    "named_children",
    "get_submodule",
    "named_parameters",
    "parameters",
    "controls",
    "boundaries",
    "states",
    "inputs",
    "outputs",
    "inlets",
    "outlets",
    "soft_sensors",
    "set_params",
    "params_at",
    "param_history",
    "set_bindings",
    "bindable",
    "missing_parameters",
    "get",
    "forward",
    "register_forward_pre_hook",
    "register_forward_hook",
    "state_dict",
    "set_state_dict",
    "health",
    "describe",
    "parameter_schema",
    "validate_params",
    "help",
    "initial_state",
    "step",
}
"""The public methods of ``Module``; a plant adds what it needs to connect."""


def test_the_public_methods_of_a_module_are_the_listed_ones():
    """A leaf has these methods and no others; a plant adds what it needs to connect."""
    public = {
        name
        for name, value in inspect.getmembers(Module)
        if not name.startswith("_") and callable(value)
    }
    assert public == PUBLIC_METHODS
