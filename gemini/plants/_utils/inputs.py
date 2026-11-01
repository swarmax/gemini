"""The inputs of a plant by path: controls, boundaries and the fields of its plant inlets."""

from pydantic import ValidationError as PydanticError

from gemini import units
from gemini._utils.strings import close_matches, did_you_mean, join_names, split_path
from gemini.errors import ValidationError
from gemini.modules._utils import design
from gemini.modules._utils.description import check_value
from gemini.modules.declarations import Boundary
from gemini.types import Fluid
from gemini.types.quantities import MassFlow, Pressure, Temperature

FIELDS = {"m_dot": Boundary(MassFlow), "T": Boundary(Temperature), "p": Boundary(Pressure)}
"""The declarations of a plant inlet field; ``fluid`` is the one field that is no number."""
FLUID = "fluid"


def _port_field(plant, path):
    """Return ``(port, field)`` when ``path`` is a field of a plant inlet, else ``None``."""
    port, field = split_path(path)
    if port in plant._fed_inlets() and (field in FIELDS or field == FLUID):
        return port, field
    return None


def _names(plant):
    """Return every path that takes an input."""
    ports = [f"{port}.{field}" for port in plant._fed_inlets() for field in (*FIELDS, FLUID)]
    return [*plant.inputs(), *ports]


def _unknown(plant, path):
    """Return the error of a path that takes no input."""
    if path in dict(plant.named_parameters()):
        message = f"inputs: {path} is a parameter; set it with set_params"
        return ValidationError(message, path=path, code="unknown_name")
    names = _names(plant)
    return ValidationError(
        f"inputs: unknown path {path!r}; expected a control, a boundary or a plant inlet field"
        f"{did_you_mean(path, names)}; valid: {join_names(names)}",
        path=path,
        code="unknown_name",
        suggestions=close_matches(path, names),
    )


def _checked_fluid(path, value):
    """Return a fluid field as given, or raise when it is no ``Fluid``."""
    try:
        Fluid.model_validate(value)
    except PydanticError as error:
        raise ValidationError(f"inputs: {path}: {error}", path=path) from error
    return value


def declaration(plant, path):
    """Return the declaration of the input at ``path``; ``None`` for ``fluid`` and unknown paths."""
    found = plant.inputs().get(path)
    if found is None:
        field = _port_field(plant, path)
        if field is not None and field[1] != FLUID:
            return FIELDS[field[1]]
    return found


def _checked_value(plant, path, value):
    """Return the value of one input in SI, or raise naming what does not fit."""
    declaration = plant.inputs().get(path)
    if declaration is None:
        found = _port_field(plant, path)
        if found is None:
            raise _unknown(plant, path)
        if found[1] == FLUID:
            return _checked_fluid(path, value)
        declaration = FIELDS[found[1]]
    fault = check_value(path, declaration, value)
    if fault is not None:
        raise ValidationError(fault["message"], path=path, code=fault["code"])
    return declaration.validate(value)


def checked(plant, values):
    """Return ``values`` by path in SI, or raise for the first that does not fit."""
    return {path: _checked_value(plant, path, value) for path, value in values.items()}


def as_stated(values, in_si):
    """Return what the plant dict stores: a number or text as written, anything else in SI."""
    plain = (int, float, str, dict)
    return {
        path: value if isinstance(value, plain) else in_si[path] for path, value in values.items()
    }


def value(plant, path):
    """Return the input at ``path`` in SI, or ``None`` when it has no value."""
    if path in plant._inputs:
        return _checked_value(plant, path, plant._inputs[path])
    declaration = plant.inputs().get(path)
    if declaration is not None:
        owner, name = declaration.owner, declaration.name
        return getattr(owner, name) if owner._has_input_value(name) else None
    if _port_field(plant, path) is None:
        raise _unknown(plant, path)
    return None


def root_streams(plant):
    """Return the stated plant inlet fields in SI, ``{port: {field: value}}``."""
    streams = {}
    for path, stated in plant._inputs.items():
        found = _port_field(plant, path)
        if found is not None:
            port, field = found
            streams.setdefault(port, {})[field] = _checked_value(plant, path, stated)
    return streams


def refuse_bare(plant, path, value):
    """Raise ``invalid_value`` for a number with a unit that is no ``{"value", "unit"}``."""
    found = declaration(plant, path)
    if found is not None:
        design.refuse_bare(found, value, path)


def in_quantity_form(found, value):
    """Return ``value`` as ``{"value", "unit"}`` when the declaration ``found`` has a unit."""
    if isinstance(value, units.Quantity):
        return value.to_dict()
    unit = None if found is None else found.unit
    if unit in (None, "-") or value is None or isinstance(value, (dict, str, bool)):
        return value
    return {"value": value, "unit": unit}
