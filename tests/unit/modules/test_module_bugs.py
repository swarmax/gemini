"""Regression tests for base-class bugs found in the cleanup audit (E-modules-*)."""

import pytest

import gemini as gm
from gemini.modules import Filter, Module, ProductionReservoir
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.plants.plant import Plant
from gemini.types import Power, Stream
from tests.fixtures.designs import with_values
from tests.fixtures.errors import raises

STREAM = Stream(
    m_dot=gm.units.Quantity(10, "kg/s"),
    T=gm.units.Quantity(330, "K"),
    p=gm.units.Quantity(1e6, "Pa"),
)


def define_module():
    """Define a fresh module class each call, as a notebook cell or a factory does."""

    class Repeated(Module):
        """Pass-through defined anew by every call."""

        def __init__(self):
            super().__init__()

            # Inlets
            self.fluid_in = Inlet(Stream)

            # Outlets
            self.fluid_out = Outlet(Stream)

        def forward(self, inlets):
            """Return the inlet."""

            # Outlets
            outlet = inlets.fluid_in

            outlets = dict(fluid_out=outlet)
            return outlets

    return Repeated


def test_redefining_a_module_class_works():
    """E-modules-001: a second definition with the same name no longer collides."""
    first, second = define_module(), define_module()
    assert first is not second
    assert second()(STREAM).outlets.fluid_out == STREAM


def test_user_class_may_reuse_a_builtin_name():
    """E-modules-001: a user class called ``Filter`` does not clash with the built-in one."""

    class Filter(Module):
        """User filter with the same class name as the built-in."""

    assert with_values(Filter()).name == "filter"


def test_subclass_of_a_concrete_module_may_add_declarations():
    """E-modules-002: declarations after ``super().__init__()`` register in a subclass."""

    class ScoredFilter(Filter):
        """Filter with one extra design parameter."""

        def __init__(self):
            super().__init__()

            # Parameters
            self.score = Parameter(float, default=1.0)

    module = with_values(ScoredFilter())
    assert "score" in dict(module.named_parameters())
    assert module(fluid_in=STREAM).outputs.pressure_drop >= 0


def test_missing_super_init_is_explicit():
    """A subclass that forgets ``super().__init__()`` fails at its first declaration."""

    class Broken(Module):
        """Forgets the base initialiser."""

        def __init__(self):
            self.value = Parameter(float)

    with pytest.raises(gm.errors.DefinitionError, match="super"):
        Broken()


def test_assigned_fluid_survives_parameter_changes_and_is_saved():
    """E-modules-003: ``module.fluid = ...`` is not reverted and ``state_dict`` stores it."""
    module = with_values(Filter())
    module.fluid = gm.WATER
    module.nominal_pressure_drop = 1000
    assert module.fluid == gm.WATER
    assert with_values(Filter()).set_state_dict(module.state_dict()).fluid == gm.WATER


def test_a_reservoir_fluid_applies_as_soon_as_it_is_set(fresh_plant):
    """E-modules-004: the fluid of a reservoir holds its density, read when the fluid is set."""
    fresh_plant.doublet.reservoir.fluid = gm.Fluid(density=gm.units.Quantity(1100, "kg/m3"))
    assert fresh_plant.doublet.reservoir.fluid.density == 1100


class Child(Module):
    """Leaf whose forward hook reads its parent's control."""

    def __init__(self):
        """Declare the fixture ports and outputs."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Return the inlet."""

        # Outlets
        outlet = inlets.fluid_in

        outlets = dict(fluid_out=outlet)
        return outlets


class Parent(Module):
    """Composite with a control its child's hook reads."""

    def __init__(self):
        """Declare the fixture ports and outputs."""
        super().__init__()

        # Modules
        self.child = Child()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.setting = Control(float, default=1.0)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream through the child."""

        # Modules
        result = self.child(fluid_in=inlets.fluid_in)

        # Outlets
        outlet = result.outlets.fluid_out

        outlets = dict(fluid_out=outlet)
        return outlets


def test_child_hook_reads_the_parent_call_value():
    """E-modules-005: inside a nested call the parent's control has its call value."""
    parent, seen = Parent(), []

    def observe(module, inlets, outlets):
        seen.append(parent.setting)

    parent.child.register_forward_hook(observe)
    parent(fluid_in=STREAM, setting=5.0)
    assert seen == [5.0]
    assert parent.setting == 1.0


class Meter(Module):
    """Leaf whose optional reading is missing."""

    def __init__(self):
        """Declare the fixture ports and outputs."""
        super().__init__()

        # Outputs
        self.reading = Output(Power | None)
        self.power = Output(Power)

    def forward(self, inlets):
        """Produce no stream."""

        outlets = dict()
        self.reading = None
        self.power = 2.0
        return outlets


class Share(Plant):
    """Composite dividing an optional reading by a power."""

    def __init__(self):
        """Declare the fixture ports and outputs."""
        super().__init__()

        # Modules
        self.meter = Meter()

        # Outputs
        self.share = Output.ratio("meter.reading", "meter.power")


def test_ratio_with_a_missing_operand_is_none():
    """E-modules-010: ``Output.ratio`` gives ``None`` when an operand is ``None``."""
    assert Share()().outputs.share is None


def test_composite_step_refuses_stateful_descendants():
    """E-modules-009: a stateless composite cannot silently skip its stateful children."""

    class Tank(Child):
        """Stateful leaf."""

        stateful = True

    parent = Parent()
    parent.child = Tank()
    with raises(gm.errors.ValidationError, "invalid_design", match="child"):
        parent.step(None, 900.0, {"fluid_in": STREAM})


def test_injection_reservoir_without_injectivity_fails_in_forward():
    """E-modules-019: a missing injectivity index fails even when outputs are skipped."""
    reservoir = gm.modules.InjectionReservoir().set_params(
        "",
        {
            "pressure": gm.units.Quantity(2e7, "Pa"),
            "temperature": gm.units.Quantity(350, "K"),
            "permeability": gm.units.Quantity(1e-13, "m2"),
            "aquifer_thickness": gm.units.Quantity(100, "m"),
            "drainage_radius": gm.units.Quantity(0, "m"),
            "top_depth": gm.units.Quantity(2000, "m"),
            "wellbore_radius": gm.units.Quantity(0.1, "m"),
            "skin": 0.0,
        },
    )
    with (
        gm.modules.no_outputs(),
        raises(gm.errors.ValidationError, "invalid_design", match="injectivity"),
    ):
        reservoir(sandface_in=STREAM)


def test_reservoir_health_without_design_index_is_not_assessed():
    """E-modules-011: a missing productivity index means not assessed, not a crash."""
    reservoir = with_values(ProductionReservoir())
    reservoir.set_params(
        "", {"pressure": gm.units.Quantity(2e7, "Pa"), "temperature": gm.units.Quantity(350, "K")}
    )
    assert reservoir.health(None, {"flow": 0.04, "bottomhole_pressure": 1.9e7}) is None
