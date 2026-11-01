"""The outputs of a plant: combinations of the values at paths.

An output is ``{"difference": [a, b]}``, ``{"ratio": [a, b]}`` or ``{"sum": [a, b, ...]}`` in a
plant dict. A path is what ``Plant.constrain`` reads: ``riser.wellhead_out.T``,
``reservoir.liquid_flow``, or a bare name for an earlier output of the plant. The kind of the
output follows from its first path.
"""

from gemini import ops
from gemini._utils.strings import close_matches, did_you_mean, join_names, split_path
from gemini.errors import DefinitionError, ValidationError
from gemini.modules.declarations import Output
from gemini.types.flows import STREAM_FIELDS
from gemini.types.quantities import (
    MassFlow,
    Pressure,
    PressureDifference,
    Ratio,
    Temperature,
    TemperatureDifference,
)

KEYS = ("difference", "ratio", "sum")
FIELD_KINDS = {"m_dot": MassFlow, "T": Temperature, "p": Pressure}
DIFFERENCES = {"K": TemperatureDifference, "Pa": PressureDifference}
"""The kind of a difference of two values of a unit, where it is not the kind of the values."""


def _unknown(path, valid):
    return ValidationError(
        f"{path!r}: no such output or port field; valid: {join_names(valid)}"
        f"{did_you_mean(path, valid)}",
        suggestions=close_matches(path, valid),
        code="unknown_name",
    )


def _module_at(plant, path):
    module = plant._find_submodule(path)
    if module is None:
        names = [item for item, _ in plant.named_modules() if item]
        raise _unknown(path, names)
    return module


def _kind(plant, path):
    """Return the kind of the value at ``path``."""
    owner, name = split_path(path)
    if not owner:
        if name not in plant._outputs:
            raise _unknown(path, plant._outputs)
        return plant._outputs[name].type
    module = plant._find_submodule(owner)
    if module is not None and name in module._outputs:
        return module._outputs[name].type
    head, port = (owner, None) if module is not None else split_path(owner)
    module = _module_at(plant, head)
    ports = module._inlets | module._outlets
    if port not in ports or name not in STREAM_FIELDS:
        names = [f"{head}.{item}" for item in module._outputs]
        raise _unknown(path, names + [f"{head}.{item}.T" for item in ports])
    return FIELD_KINDS[name]


_MEANINGS = {
    "difference": "{0} minus {1}",
    "ratio": "{0} over {1}",
    "sum": "Sum of {joined}",
}
"""The description of an output by the key of its entry in a plant dict."""


def _result_kind(key, kind):
    """Return the kind of an output of ``key`` over values of ``kind``."""
    if key == "ratio":
        return Ratio | None
    unit = Output(kind).unit
    return (DIFFERENCES.get(unit, kind) if key == "difference" else kind) | None


def check(name, data):
    """Return ``(key, paths)`` of an entry of a plant dict, or raise what is wrong with it."""
    given = [key for key in KEYS if key in data]
    if len(given) != 1 or len(data) != 1:
        raise ValidationError(
            f"{name}: keys = {sorted(data)}; expected exactly one of {join_names(KEYS)}",
            path="",
            code="invalid_format",
        )
    key, paths = given[0], data[given[0]]
    two = key != "sum"
    if not isinstance(paths, list) or len(paths) < 2 or (two and len(paths) != 2):
        raise ValidationError(
            f"{name}.{key} = {paths!r}; expected a list of {'two' if two else 'two or more'} paths",
            path=key,
            code="invalid_format",
        )
    return key, paths


def declare(plant, name, data):
    """Declare output ``name`` of ``plant`` from an entry of a plant dict."""
    key, paths = check(name, data)
    if name in plant._children:
        raise ValidationError(f"{name}: an output cannot share the name of a module", path="")
    kinds = [_kind(plant, path) for path in paths]
    meaning = _MEANINGS[key].format(*paths, joined=", ".join(paths))
    output = Output(_result_kind(key, kinds[0]), description=meaning)
    output.formula = (key, *paths)
    return output


def typed(plant, name, formula):
    """Return the output of a ``formula`` assigned by a plant class, of the kind of its paths."""
    key, *paths = formula
    return declare(plant, name, {key: paths})


def entry_of(formula):
    """Return the entry of a plant dict of ``formula``."""
    key, *paths = formula
    return {key: list(paths)}


def combine(key, values):
    """Return the value of an output; ``None`` when a value is ``None`` or a divisor zero."""
    if any(value is None for value in values):
        return None
    if key == "difference":
        return values[0] - values[1]
    if key == "ratio":
        return ops.where(ops.eq(values[1], 0), None, ops.truediv(values[0], values[1]))
    total = values[0]
    for value in values[1:]:
        total = total + value
    return total


def read(plant, records, path):
    """Return the value at ``path`` in a finished call: ``records`` are its results by path."""
    owner, name = split_path(path)
    if not owner:
        return getattr(plant, name)
    if owner in records:
        return records[owner].outputs[name]
    head, port = split_path(owner)
    if head not in records:
        raise DefinitionError(f"{plant.path}: output path {path!r}: {head!r} was not called")
    result = records[head]
    ports = result.outlets if port in result.outlets else result.inlets
    return getattr(ports[port], name)


def ordered(entries):
    """Return ``(name, data)`` in given order, an output after the outputs it reads."""
    result, waiting = [], list(entries.items())

    def ready(item):
        paths = next((value for key, value in item[1].items() if key in KEYS), ())
        done = {name for name, _ in result}
        return all("." in path or path in done for path in paths)

    while any(ready(item) for item in waiting):
        first = next(item for item in waiting if ready(item))
        waiting.remove(first)
        result.append(first)
    return result + waiting
