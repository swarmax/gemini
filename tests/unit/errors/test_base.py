"""Roots of the GEMINI error and warning hierarchy."""

import json
import pickle

import pytest

import gemini as gm
from gemini import errors
from gemini.errors import base

REMOVED = (
    "BindingError",
    "CallError",
    "CheckpointError",
    "ClockError",
    "ConfigurationError",
    "DatasetError",
    "DeclarationError",
    "FormulaError",
    "InsufficientDataError",
    "LegacyFormatError",
    "MissingChemistryError",
    "MissingMeasurementError",
    "MissingValueError",
    "OutletError",
    "OutputError",
    "PhysicsRangeError",
    "PlantFormatError",
    "SolverError",
    "StepError",
    "TraceError",
    "UnitError",
    "UnknownCorrelationError",
    "UnknownMemberError",
    "UnknownNameError",
    "UnknownPortError",
    "UnknownResultError",
)
"""The former classes; what each meant is a ``code``."""


def test_roots_derive_from_the_builtin_roots():
    """Catching ``GeminiError`` or ``GeminiWarning`` catches everything GEMINI raises or warns."""
    assert issubclass(base.GeminiError, Exception)
    assert issubclass(base.GeminiWarning, UserWarning)
    assert gm.errors.GeminiError is base.GeminiError


def test_every_exported_class_has_a_gemini_root():
    """Every public class derives from a GEMINI root and is documented."""
    for name in set(gm.errors.__all__) - {"CODES", "ROW_CODES"}:
        cls = getattr(gm.errors, name)
        assert issubclass(cls, (base.GeminiError, base.GeminiWarning)), name
        assert cls.__doc__, name


def test_to_dict_gives_the_fixed_shape():
    """``to_dict`` is the problem: plain JSON with the path, code, message and suggestions."""
    error = errors.ValidationError(
        "no such name", path="doublet.esp", code="unknown_name", suggestions=("esp",)
    )
    assert error.to_dict() == {
        "path": "doublet.esp",
        "code": "unknown_name",
        "message": "no such name",
        "suggestions": ["esp"],
    }
    assert json.dumps(error.to_dict())


def test_every_class_has_a_listed_code():
    """Each exported error class carries a code from the fixed list."""
    classes = [getattr(errors, name) for name in errors.__all__]
    for cls in classes:
        if isinstance(cls, type) and issubclass(cls, errors.GeminiError):
            assert cls.code in errors.CODES


def test_an_unlisted_code_is_refused():
    """A code outside ``CODES`` is a programming error."""
    with pytest.raises(errors.GeminiError, match="expected one of CODES"):
        errors.ValidationError("message", code="made_up")


def test_pickling_keeps_location_and_suggestions():
    """A worker process can hand an error back with its details."""
    error = errors.ValidationError("bad", path="a.b", code="invalid_unit", suggestions=("bar",))
    assert pickle.loads(pickle.dumps(error)).to_dict() == error.to_dict()


def test_there_are_seven_public_classes():
    """Six errors and one warning, plus the two fixed lists of codes."""
    assert set(errors.__all__) == {
        "CODES",
        "ROW_CODES",
        "GeminiError",
        "GeminiWarning",
        "ValidationError",
        "DefinitionError",
        "PhysicsError",
        "RunError",
        "Cancelled",
        "NotImplementedYet",
    }


@pytest.mark.parametrize("name", REMOVED)
def test_a_former_class_is_gone(name):
    """What it meant is a code; there is no alias."""
    assert not hasattr(errors, name)


def test_built_in_bases_appear_only_where_python_needs_them():
    """``ValidationError`` is a ``ValueError``; the others derive from ``GeminiError`` alone."""
    assert issubclass(errors.ValidationError, ValueError)
    for cls in (errors.DefinitionError, errors.PhysicsError, errors.RunError, errors.Cancelled):
        assert cls.__bases__ == (errors.GeminiError,)
    assert errors.NotImplementedYet.__bases__ == (errors.GeminiError,)
    assert errors.ROW_CODES["missing_value"]


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("ValidationError", "invalid_value"),
        ("DefinitionError", "invalid_definition"),
        ("PhysicsError", "out_of_range"),
        ("RunError", "step"),
        ("Cancelled", "cancelled"),
        ("NotImplementedYet", "not_implemented"),
    ],
)
def test_every_class_has_a_default_code(name, code):
    """A raise that states no code has the most common one of its class."""
    assert getattr(errors, name)("message").code == code


def test_a_single_error_has_itself_as_its_problems():
    """``problems`` is always a list of problem dicts."""
    error = errors.ValidationError("bad", path="a", code="unknown_name")
    assert error.problems == [error.to_dict()]


def test_one_error_carries_every_problem():
    """``ValidationError.of`` keeps the list ``on_error="record"`` returns."""
    problems = [
        base.problem("a", "unknown_name", "no a", ("b",)),
        base.problem("c", "invalid_unit", "no c"),
    ]
    error = errors.ValidationError.of(problems)
    assert error.problems == problems and error.code == "unknown_name" and error.path == "a"
    assert str(error) == "a: no a; c: no c" and error.suggestions == ("b",)


def test_reported_raises_the_problems_or_returns_them():
    """The one rule of the ``validate`` functions."""
    problems = [base.problem("a", "invalid_value", "bad")]
    assert base.reported([], "raise") == [] and base.reported(problems, "record") == problems
    with pytest.raises(errors.ValidationError, match="a: bad") as caught:
        base.reported(problems, "raise")
    assert caught.value.problems == problems


def test_on_error_has_two_values_everywhere():
    """Any other value is wrong input."""
    with pytest.raises(errors.ValidationError, match="on_error = 'ignore'"):
        base.check_on_error("ignore")


def test_a_problem_without_a_path_has_no_prefix_in_the_message():
    """A message does not start with ``None:``."""
    problem = {"path": None, "code": "invalid_value", "message": "x", "suggestions": []}
    assert errors.ValidationError.of([problem]).args == ("x",)
