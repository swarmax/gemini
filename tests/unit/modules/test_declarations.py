"""Ready-made declaration validation."""

import copy
import math
import pickle
from datetime import datetime, timezone

import numpy as np
import pytest

from gemini.errors import DefinitionError, ValidationError
from gemini.modules import Module
from gemini.modules.declarations import (
    _MISS,
    UNSET,
    Boundary,
    Control,
    Inlet,
    Outlet,
    Output,
    Parameter,
)
from gemini.types import (
    Length,
    Pressure,
    PressureDifference,
    Ratio,
    Stream,
    Temperature,
    TemperatureDifference,
)
from gemini.types.bindings import DatedParams


class Declared(Module):
    """Fixture containing every declaration kind."""

    def __init__(self):
        """Declare fields covering each declaration kind."""
        super().__init__()

        # Parameters
        self.length = Parameter(Length)
        self.coefficients = Parameter(list[float], shape=(2,))

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.command = Control(float, default=1)

        # Boundaries
        self.weather = Boundary(float)

        # Outputs
        self.value = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Return the inlet after recording a value."""

        # Outlets
        inlet = inlets.fluid_in
        outlet = inlet

        # Outputs
        self.value = self.command + self.weather

        outlets = dict(fluid_out=outlet)
        return outlets


def _declared(**params):
    """Return the fixture module with parameters set as explicit overrides."""
    module = Declared()
    module.set_params("", params)
    return module


def test_parameter_units_shape_and_metadata():
    """Parameters validate units and vector shape once assigned."""
    module = _declared(length={"value": 1200, "unit": "m"}, coefficients=[1, 2])
    assert module.length == 1200
    assert module.get("length").unit == "m"
    with pytest.raises(ValidationError, match="shape"):
        _declared(length=1, coefficients=[1])
    with pytest.raises(ValidationError, match="expected m"):
        _declared(length={"value": 12, "unit": "bar"}, coefficients=[1, 2])


def test_parameter_history_projects_module_snapshots():
    """A parameter exposes its values from the module's canonical dated snapshots."""
    module = Declared()
    changed = datetime(2025, 1, 1, tzinfo=timezone.utc)
    module._param_history.extend(
        [
            DatedParams(params={"length": 1, "coefficients": [1, 2]}),
            DatedParams(valid_from=changed, params={"length": 2, "coefficients": [3, 4]}),
        ]
    )
    assert module.get("length").history == [(None, 1.0), (changed, 2.0)]


def test_all_sections_list_own_declarations():
    """Section listings expose declaration objects without duplicate schemas."""
    module = _declared(length=1, coefficients=[1, 2])
    assert list(module.inlets()) == ["fluid_in"]
    assert list(module.controls()) == ["command"]
    assert list(module.boundaries()) == ["weather"]
    assert list(module.inputs()) == ["command", "weather"]
    assert list(module.outputs()) == ["value"]
    assert list(module.outlets()) == ["fluid_out"]


def test_inlets_and_outlets_accept_fluid_stream_types_only():
    """Scalar and energy values belong in inputs or outputs, never flow ports."""
    with pytest.raises(DefinitionError, match="Stream type or Power"):
        Inlet(float)
    with pytest.raises(DefinitionError, match="Stream type or Power"):
        Outlet(float)


def test_unset_keeps_its_identity_through_copy_and_pickle():
    """Copied and pickled modules still report unset parameters as missing."""
    assert copy.copy(UNSET) is UNSET
    assert copy.deepcopy(UNSET) is UNSET
    assert pickle.loads(pickle.dumps(UNSET)) is UNSET
    parameter = Parameter(Length)
    assert not copy.deepcopy(parameter).initialized
    assert [item["path"] for item in copy.deepcopy(Declared()).missing_parameters()] == [
        "length",
        "coefficients",
    ]


def test_difference_parameters_ignore_unit_offsets():
    """A temperature difference given in degC is the same number of kelvin."""
    assert Parameter(TemperatureDifference).validate({"value": 5, "unit": "degC"}) == 5
    assert Parameter(PressureDifference).validate({"value": 2, "unit": "barg"}) == 2e5
    assert Parameter(Temperature).validate({"value": 5, "unit": "degC"}) == 278.15


def test_unitless_declarations_keep_text_values():
    """Text with a trailing word is not a unit when the declaration has no unit."""
    assert Parameter(str, default="x").validate("12 m") == "12 m"
    assert Parameter(str, default="x").validate("2 stages") == "2 stages"


def test_invalid_values_raise_declaration_errors():
    """Wrong units and wrong shapes name the declaration path, value and expectation."""
    parameter = Parameter(Length).bind(None, "length")
    with pytest.raises(ValidationError, match="length: invalid parameter value.*bar.*expected m"):
        parameter.validate({"value": 12, "unit": "bar"})
    with pytest.raises(ValidationError, match="coefficients: shape = \\(1,\\); expected \\(2,\\)"):
        Parameter(list[float], shape=(2,)).bind(None, "coefficients").validate([1])


def test_limits_come_from_the_quantity_and_the_bounds():
    """Quantity bounds and declared bounds merge; kinds without bounds give nothing."""
    assert Control(Pressure, le=9).limits() == {"ge": 0, "le": 9}
    assert Output(Temperature).limits() == {"gt": 0}
    assert Output(list[Pressure]).limits() == {"ge": 0}
    assert Output(bool).limits() == {}
    assert Output(Ratio | None).accepts_none() and not Output(float).accepts_none()
    assert Inlet(Stream).limits() == {}


SAMPLES = [
    0.0,
    1.5,
    -1.0,
    1e30,
    -1e30,
    5e-324,
    math.nan,
    math.inf,
    -math.inf,
    0,
    3,
    True,
    False,
    np.float64(2.0),
    np.float32(2.0),
    np.int64(2),
    {"value": 5, "unit": "bar"},
    {"value": 300, "unit": "K"},
    "2.0",
    "text",
    {"value": 50, "unit": "Hz"},
    None,
    [1.0, 2.0],
    [1.0, -1.0],
    (1.0, 2.0),
    {"m_dot": 1.0},
    b"1",
    1 + 2j,
]


def _outcome(call, value):
    try:
        result = call(value)
    except Exception as error:
        return type(error), str(error)
    return type(result), "nan" if result != result else repr(result)


def _full_path(declaration):
    full = copy.deepcopy(declaration)
    full._quick = lambda value: _MISS
    return full


def test_the_quick_check_gives_the_result_or_error_of_the_full_path(module_class):
    """Every declared kind and bound: a sample is accepted unchanged or takes the full path."""
    try:
        module = module_class()
    except Exception:
        pytest.skip("not constructible without arguments")
    seen = set()
    for _, owner in module.named_modules():
        for declaration in owner._declarations().values():
            signature = (repr(declaration.type), repr(declaration.bounds), declaration.unit)
            if isinstance(declaration, (Inlet, Outlet)) or signature in seen:
                continue
            seen.add(signature)
            full = _full_path(declaration)
            edges = [
                bound + step
                for bound in declaration.limits().values()
                for step in (0.0, 1e-9, -1e-9)
            ]
            for value in [*SAMPLES, *edges]:
                assert _outcome(declaration.validate, value) == _outcome(full.validate, value), (
                    declaration.path,
                    value,
                )


def test_a_default_is_validated_once_and_mutable_defaults_stay_fresh():
    """``default_value`` converts once, and no caller can change the next caller's default."""
    scalar = Control(Pressure, default={"value": 2, "unit": "bar"})
    assert scalar.default_value() == 2e5 == scalar.default_value()
    series = Control(list[float], default=[1, 2])
    first = series.default_value()
    first.append(9.0)
    assert series.default_value() == [1.0, 2.0]
    assert (
        copy.deepcopy(series).default_value() == pickle.loads(pickle.dumps(series)).default_value()
    )


def test_the_quick_check_converts_numpy_scalars_of_the_eager_scope():
    """An ``np.float64`` or ``np.bool_`` validates to the Python ``float`` or ``bool``."""
    number = Parameter(float, gt=0)
    flag = Parameter(bool)
    checked = number.validate(np.float64(2.5))
    assert type(checked) is float and checked == 2.5
    assert flag.validate(np.bool_(True)) is True
    with pytest.raises(ValidationError, match=r"invalid parameter value -1\.0"):
        number.validate(np.float64(-1.0))
