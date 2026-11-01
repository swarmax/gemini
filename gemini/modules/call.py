"""One call of one module from plain JSON."""

from collections.abc import Mapping

from gemini import units as unit_table
from gemini._utils import registry
from gemini.errors import GeminiError, ValidationError
from gemini.errors.base import check_on_error
from gemini.modules._utils import design
from gemini.modules.module import Module
from gemini.types import bare
from gemini.types.flows import FIELD_SI, STREAM_FIELDS, Stream
from gemini.types.shapes import OutputUnits

FLOW = ("m3/s", "volume_flow")
"""The SI unit and the quantity of ``flow``, the volume flow in place of ``m_dot``."""


def evaluate(module, parameters, inlets, controls, on_error="raise", units=None):
    """Return ``{outlets, outputs, errors}`` of one call of a registered module or class.

    ``module`` is a registry name or a ``Module`` class. ``parameters`` maps parameter names to
    quantities (``{"value": 150, "unit": "m3/h"}``, or a ``gm.units.Quantity``) for a value with a
    dimension and plain numbers for one without. ``inlets`` maps each inlet
    port to its stream fields, ``{"m_dot": {"value": 10, "unit": "kg/s"}, "T": ...}``, or ``flow``
    in place of ``m_dot`` for a volume flow, which converts with the density of the inlet's
    fluid, and an optional ``fluid``. ``m_dot`` refuses a volume unit and suggests ``flow``.
    ``controls`` maps control and boundary names to values for this call only, in the same form.
    A bare number for a value with a dimension, in ``parameters``, ``controls`` or an inlet
    field, is refused with ``invalid_value`` naming the path, the quantity and its units.

    The result is plain JSON with units: ``outlets`` is ``{port: {field: {value, unit}}}`` and
    ``outputs`` is ``{name: {value, unit}}``, in SI or in ``units``, a map from quantity to unit,
    and ``errors`` is empty. A call that fails raises; with ``on_error="record"`` it returns empty
    ``outlets`` and ``outputs`` and in ``errors`` the problem of what went wrong.
    """
    check_on_error(on_error)
    try:
        output = OutputUnits(units)
        _check_mass_flows(inlets or {})
        _check_inlets(inlets or {})
        instance = _instance(module)
        _check_given(instance, parameters or {}, controls or {})
        instance._override_params(parameters or {})
    except GeminiError as error:
        return _failed(error, on_error)
    except (TypeError, ValueError) as error:
        return _failed(ValidationError(str(error)), on_error)
    try:
        result = instance(dict(inlets or {}), **(controls or {}))
    except GeminiError as error:
        return _failed(error, on_error)
    return {
        "outlets": _outlets(result.outlets, output),
        "outputs": _outputs(instance, result.outputs, output),
        "errors": [],
    }


def _check_mass_flows(inlets):
    """Refuse a volume flow given as ``m_dot``, pointing to ``flow``."""
    for port, fields in inlets.items():
        flow = fields.get("m_dot") if isinstance(fields, Mapping) else None
        unit = flow.get("unit") if isinstance(flow, Mapping) else getattr(flow, "unit", None)
        if unit is not None and unit_table.fits(unit, "volume_flow"):
            raise ValidationError(
                f"evaluate: {port}.m_dot = {flow!r}; expected a mass flow; give it as 'flow'",
                path=f"{port}.m_dot",
                code="invalid_call",
                suggestions=["flow"],
            )


def _check_inlets(inlets):
    """Refuse a bare number for a stream field of an inlet: it is a quantity."""
    for port, fields in inlets.items():
        if not isinstance(fields, Mapping):
            continue
        for name, value in fields.items():
            unit, quantity = FLOW if name == "flow" else FIELD_SI.get(name, (None, None))
            bare.refuse(f"{port}.{name}", value, unit, quantity)


def _check_given(instance, parameters, controls):
    """Refuse a bare number for a parameter, control or boundary with a dimension."""
    for name, value in parameters.items():
        design.refuse_bare(instance.get(name), value, name)
    declared = instance.inputs()
    for name, value in controls.items():
        if name in declared:
            design.refuse_bare(declared[name], value, name)


def _instance(module):
    """Return a new module from a registry name or a class."""
    if isinstance(module, str):
        module = registry.get(module)
    if isinstance(module, Module):
        return module
    if not (isinstance(module, type) and issubclass(module, Module)):
        raise ValidationError(
            f"evaluate: module = {module!r}; expected a registry name or a Module class"
        )
    return module()


def _failed(error, on_error):
    """Raise the failure of a call, or return it under ``on_error="record"``."""
    if on_error == "raise":
        raise error
    return {"outlets": {}, "outputs": {}, "errors": [error.to_dict()]}


def _outlets(outlets, output):
    """Return each outlet as ``{field: {value, unit}}``; a power port has the field ``power``."""
    return {port: _outlet(value, output) for port, value in outlets.items()}


def _outlet(value, output):
    """Return one outlet: its stream fields, or ``{power: {value, unit}}``."""
    if isinstance(value, list):
        return [_outlet(item, output) for item in value]
    if not isinstance(value, Stream):
        return {"power": output.value(value, "W", "power")}
    return {name: output.value(getattr(value, name), *FIELD_SI[name]) for name in STREAM_FIELDS}


def _outputs(instance, outputs, output):
    """Return each output as ``{value, unit}``; an output without a declared unit is ``"-"``."""
    declarations = instance.outputs(recurse=False)
    return {
        name: output.value(
            number,
            (declarations[name].unit if name in declarations else None) or "-",
            declarations[name].quantity if name in declarations else None,
        )
        for name, number in outputs.items()
    }
