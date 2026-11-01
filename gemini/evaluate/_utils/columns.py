"""The values a constraint reads: the field of a module and its values over a run."""

import numpy as np

from gemini._utils.strings import close_matches, did_you_mean, join_path, split_path
from gemini._utils.time import to_utc
from gemini.errors import ValidationError
from gemini.run.results import PORT_QUANTITIES, port_fields
from gemini.types.flows import FIELD_QUANTITIES


def split_target(target):
    """Return ``(module path, field)``: a port quantity is ``<port>.<quantity>``."""
    head, _, last = target.rpartition(".")
    if last in PORT_QUANTITIES:
        module, _, port = head.rpartition(".")
        return module, f"{port}.{last}"
    return head, last


def fields(plant, path):
    """Return ``{name: (unit, quantity)}`` of what a constraint may judge."""
    module = plant.get_submodule(path)
    declared = dict(module.named_parameters(recurse=False)) | module.outputs(recurse=False)
    named = {
        name: (declaration.unit or "-", declaration.quantity)
        for name, declaration in declared.items()
    }
    return named | port_fields(module)


def is_parameter(plant, path, name):
    """Return whether ``name`` is a parameter of the module at ``path``, not one of its outputs."""
    module = plant.get_submodule(path)
    return name not in module.outputs(recurse=False) and name in dict(
        module.named_parameters(recurse=False)
    )


def field_of(plant, target):
    """Return ``(path, name)``: the module and the field that ``target`` names in ``plant``.

    A module or a field the plant lacks raises ``unknown_name`` with suggestions.
    """
    pattern, name = split_target(target)
    paths = [path for path, _ in plant.named_modules()]
    if pattern not in paths:
        raise ValidationError(
            f"{target}: module = {pattern!r} is not in the plant{did_you_mean(pattern, paths)}",
            path=pattern,
            code="unknown_name",
            suggestions=close_matches(pattern, paths),
        )
    names = list(fields(plant, pattern))
    if name not in names:
        raise ValidationError(
            f"{target}: no field {name!r} in {pattern or 'the plant'}{did_you_mean(name, names)}",
            path=target,
            code="unknown_name",
            suggestions=close_matches(name, names),
        )
    return pattern, name


def _parameter_times(plant, frame, path):
    """Return the instants at which the parameters of ``path`` take their values in the run.

    The start of the run and each date inside it, or the latest values for an undated module.
    """
    dates = [item["valid_from"] for item in plant.param_history(path) if item["valid_from"]]
    if not dates or frame.empty:
        return [None]
    start, end = frame.index[0], frame.index[-1]
    return [start, *(date for date in dates if start < to_utc(date) <= end)]


def parameter_values(plant, frame, path, name):
    """Return each value the parameter takes in the run, as an array."""
    times = _parameter_times(plant, frame, path)
    found = [plant.params_at(path, time)[name] for time in times]
    return np.array([np.nan if item is None else item for item in found], dtype=float)


def _column(frame, path, name):
    """Return a leaf column over the run and whether its module carried flow, tick by tick."""
    if join_path(path, name) not in frame:
        return np.empty(0), np.empty(0, dtype=bool)
    values = frame[join_path(path, name)].to_numpy(dtype=float)
    active = frame[join_path(path, "operating")].to_numpy(dtype=bool)
    return values, active


def series(plant, frame, path, name):
    """Return ``(values, active)`` of an output: a leaf column, or the combination of a plant.

    ``Results`` holds leaf columns, so an output of a plant is computed from the paths it names,
    and a tick counts when every leaf behind it carried flow. A run without the column, because
    every row failed, gives nothing.
    """
    declared = plant.get_submodule(path).outputs(recurse=False)
    key, *paths = (declared[name].formula if name in declared else None) or (None,)
    if key is None:
        return _column(frame, path, name)
    found = [_path_series(plant, frame, path, item) for item in paths]
    active = np.logical_and.reduce([flag for _, flag in found])
    return _combined(key, [values for values, _ in found]), active


def _combined(key, values):
    """Return the arrays of a combination, as a plant computes it on one tick."""
    if key == "sum":
        return np.sum(values, axis=0)
    return values[0] - values[1] if key == "difference" else values[0] / values[1]


def _path_series(plant, frame, path, item):
    """Return ``(values, active)`` of a path of the plant at ``path``."""
    owner, name = split_path(item)
    if not owner:
        return series(plant, frame, path, name)
    if name in FIELD_QUANTITIES:
        module, port = split_path(join_path(path, owner))
        return _column(frame, module, f"{port}.{FIELD_QUANTITIES[name]}")
    return series(plant, frame, join_path(path, owner), name)
