"""The rules a new module class must meet, as a report."""

import inspect
import json

from gemini._utils.jsonable import to_plain
from gemini._utils.registry import CATEGORIES
from gemini.modules.call import evaluate
from gemini.modules.module import Module

_NUMERIC = ("number", "integer")
_NEEDS_VALUES = ("missing_value", "invalid_call")
"""Error codes of a call that lacks a parameter, a control or an inlet stream."""


def _category(cls, instance):
    if cls.category in CATEGORIES:
        return True, f"category = {cls.category!r}"
    return False, f"category = {cls.category!r}; expected one of {', '.join(CATEGORIES)}"


def _forward_signature(cls, instance):
    names = list(inspect.signature(cls.forward).parameters)
    if names == ["self", "inlets"]:
        return True, "forward(self, inlets)"
    return False, f"forward parameters = {names}; expected ['self', 'inlets']"


def _units(cls, instance):
    """Check that every scalar numeric declaration states its unit; arrays are exempt."""
    declarations = {
        **{f"parameters.{name}": item for name, item in instance.named_parameters(recurse=False)},
        **{f"controls.{name}": item for name, item in instance.controls(recurse=False).items()},
        **{f"boundaries.{name}": item for name, item in instance.boundaries(recurse=False).items()},
        **{f"outputs.{name}": item for name, item in instance.outputs(recurse=False).items()},
    }
    missing = [
        name
        for name, item in declarations.items()
        if item.value_type() in _NUMERIC
        and item.unit is None
        and getattr(item, "shape", None) is None
    ]
    if missing:
        return False, f"declared without a unit: {', '.join(missing)}; use a quantity type"
    return True, f"{len(declarations)} declarations, every numeric one with a unit"


def _describe(cls, instance):
    json.dumps(instance.describe(), allow_nan=False)
    return True, "describe() returns plain JSON"


def _call(cls, instance, example):
    """Run one call through ``evaluate``; a missing value without an example is undecided."""
    example = example or {}
    result = evaluate(
        cls,
        example.get("parameters"),
        example.get("inlets"),
        example.get("controls"),
        on_error="record",
    )
    if not result["errors"]:
        return True, f"one call returned {len(result['outputs'])} outputs"
    error = result["errors"][0]
    if not example and error["code"] in _NEEDS_VALUES:
        return None, f"needs example values: {error['message']}"
    return False, f"{error['code']}: {error['message']}"


def _attempt(name, function, *arguments):
    """Return the report entry of one check; any error it raises is a failed check."""
    try:
        passed, message = function(*arguments)
    except Exception as error:
        passed, message = False, f"{type(error).__name__}: {error}"
    return {"name": name, "passed": passed, "message": message}


def check(cls, example=None):
    """Return a report of gemini's module rules for a new ``Module`` class; it never raises.

    The checks, in order: ``is_module`` (a subclass of ``Module``), ``instantiate`` (``cls()``
    declares without error, which also enforces the declaration rules: ``Stream`` ports, valid
    bounds, no clashing names), ``category`` (one of ``gm.modules.categories()``),
    ``forward_signature`` (exactly ``forward(self, inlets)``), ``units`` (every numeric
    scalar parameter, control, boundary and output is declared with a quantity type that has a unit;
    coefficient arrays are exempt),
    ``describe`` (``describe()`` returns plain JSON) and ``call`` (one call through
    ``gm.call`` with the example values runs). Any exception a check meets, including one
    raised by the class itself, becomes a failed check with its message.

    Parameters
    ----------
    cls : type
        The class to check.
    example : dict, optional
        Values for the ``call`` check, the arguments of ``gm.call``:
        ``{"parameters": {...}, "inlets": {...}, "controls": {...}}``. Without it the call uses
        the declared defaults, and a module that needs a value gets ``passed`` ``None``.

    Returns
    -------
    dict
        Plain JSON ``{module, passed, checks}``: ``module`` is the class name, ``checks`` a list of
        ``{name, passed, message}`` where ``passed`` is ``True``, ``False`` or ``None`` (could not
        be decided), and ``passed`` is ``False`` if any check failed, otherwise ``True``.
    """
    name = getattr(cls, "__name__", repr(cls))
    if not (isinstance(cls, type) and issubclass(cls, Module)):
        checks = [{"name": "is_module", "passed": False, "message": "expected a Module subclass"}]
        return _report(name, checks)
    checks = [{"name": "is_module", "passed": True, "message": f"{name} is a Module subclass"}]
    try:
        instance = cls()
    except Exception as error:
        failed = {"name": "instantiate", "passed": False}
        return _report(name, checks + [failed | {"message": f"{type(error).__name__}: {error}"}])
    checks.append({"name": "instantiate", "passed": True, "message": f"{name}() declares"})
    checks += [
        _attempt("category", _category, cls, instance),
        _attempt("forward_signature", _forward_signature, cls, instance),
        _attempt("units", _units, cls, instance),
        _attempt("describe", _describe, cls, instance),
        _attempt("call", _call, cls, instance, example),
    ]
    return _report(name, checks)


def _report(name, checks):
    """Return the report: the checks and whether none failed."""
    return to_plain(
        {
            "module": name,
            "passed": all(item["passed"] is not False for item in checks),
            "checks": checks,
        }
    )
