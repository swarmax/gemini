"""One call of one module from plain JSON."""

from collections.abc import Mapping

from gemini import units as unit_table
from gemini._utils import registry
from gemini.errors import GeminiError, ValidationError
from gemini.errors.base import check_on_error
from gemini.modules.module import Module
from gemini.types.flows import STREAM_FIELDS, Stream
from gemini.types.shapes import OutputUnits

STREAM_UNITS = {
    "m_dot": ("kg/s", "mass_flow"),
    "T": ("K", "temperature"),
    "p": ("Pa", "pressure"),
}
"""The SI unit and the quantity of each numeric stream field."""


def evaluate(module, parameters, inlets, controls, on_error="raise", units=None):
    """Return ``{outlets, outputs, errors}`` of one call of a registered module or class.

    ``module`` is a registry name or a ``Module`` class. ``parameters`` maps parameter names to
    numbers or unit strings (``"150 m3/h"``). ``inlets`` maps each inlet port to its stream
    fields, ``{"m_dot": "10 kg/s", "T": "80 degC", "p": "5 bar"}``, or ``flow`` in place of
    ``m_dot`` for a volume flow (``"150 m3/h"``), which converts with the density of the inlet's
    fluid, and an optional ``fluid``. ``m_dot`` refuses a volume unit and suggests ``flow``.
    ``controls`` maps control and boundary names to values for this call only.

    The result is plain JSON with units: ``outlets`` is ``{port: {field: {value, unit}}}`` and
    ``outputs`` is ``{name: {value, unit}}``, in SI or in ``units``, a map from quantity to unit,
    and ``errors`` is empty. A call that fails raises; with ``on_error="record"`` it returns empty
    ``outlets`` and ``outputs`` and in ``errors`` the problem of what went wrong.
    """
    check_on_error(on_error)
    try:
        output = OutputUnits(units)
        _check_mass_flows(inlets or {})
        instance = _instance(module)
        instance._override_params(parameters or {})
        result = instance(dict(inlets or {}), **(controls or {}))
    except GeminiError as error:
        return _failed(error, on_error)
    except (TypeError, ValueError) as error:
        return _failed(ValidationError(str(error)), on_error)
    return {
        "outlets": _outlets(result.outlets, output),
        "outputs": _outputs(instance, result.outputs, output),
        "errors": [],
    }


def _check_mass_flows(inlets):
    """Refuse a volume flow given as ``m_dot``, pointing to ``flow``."""
    for port, fields in inlets.items():
        flow = fields.get("m_dot") if isinstance(fields, Mapping) else None
        *_, unit = str(flow).rpartition(" ")
        if unit_table.fits(unit, "volume_flow"):
            raise ValidationError(
                f"evaluate: {port}.m_dot = {flow!r}; expected a mass flow; give it as 'flow'",
                path=f"{port}.m_dot",
                code="invalid_call",
                suggestions=["flow"],
            )


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
    return {name: output.value(getattr(value, name), *STREAM_UNITS[name]) for name in STREAM_FIELDS}


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
