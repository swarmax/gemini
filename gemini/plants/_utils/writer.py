"""Write a plant as its plant dict: a class and its values, or its structure."""

from copy import deepcopy

from gemini._utils.jsonable import to_plain
from gemini._utils.strings import join_path
from gemini.errors import GeminiError
from gemini.modules._utils import design
from gemini.modules._utils.serialization import (
    FORMAT,
    keep_stated,
    plain_value,
    to_sections,
    tree_params,
)
from gemini.plants._utils import inputs
from gemini.plants._utils.plan import is_group, is_plant
from gemini.types import Fluid


def _same(module, name, stated, current):
    try:
        return keep_stated(stated, current, lambda value: _plain(module, name, value))
    except GeminiError:
        return None


def _plain(module, name, value):
    return plain_value(design.parameter(module, name).validate(value))


def params_entry(plant, key, module):
    """Return the ``params`` of one module: stated values while true, others that changed.

    A value the case holds is never written: a run sets it on a copy. A value with a unit is
    written as ``{"value", "unit"}``.
    """
    stated = plant._stated.get(key) or {}
    baseline = plant._baselines.get(key, {})
    derived = design.derived_names(module)
    owned = {name for name, parameter in module.named_parameters() if parameter.case}
    result = {}
    for name, value in tree_params(module).items():
        if name in owned:
            continue
        if name in stated:
            kept = _same(module, name, stated[name], value)
            result[name] = kept if kept is not None else value
        elif name not in derived and (name not in baseline or baseline[name] != value):
            result[name] = value
    return {
        name: design.quantity_form(design.parameter(module, name), value)
        for name, value in result.items()
    }


def modules_entry(plant, container, prefix=""):
    """Return the ``modules`` mapping of ``container``, groups nested."""
    result = {}
    for name, child in container.named_children():
        key = join_path(prefix, name)
        entry = {"type": type(child).__name__}
        if getattr(child, "_size", None):
            entry["size"] = deepcopy(child._size)
        if is_group(child):
            entry["modules"] = modules_entry(plant, child, key)
        else:
            params = params_entry(plant, key, child)
            if params or plant._stated.get(key) is not None:
                entry["params"] = params
        result[name] = entry
    return result


def _port_text(ends):
    """Return the ``"path.port"`` text of a plant port, a list when several ends share it."""
    if isinstance(ends, list):
        return [join_path(*end) for end in ends]
    return join_path(*ends)


def _input_form(found, value):
    """Return an input as the plant dict stores it: a fluid and a quantity in their dict forms."""
    if isinstance(value, Fluid):
        return value._to_dict()
    return design.quantity_form(found, value)


def _inputs_section(plant):
    """Return the ``inputs`` key of the plant dict, empty when nothing below ``plant`` set one."""
    stated = {
        join_path(path, name): _input_form(inputs.declaration(module, name), value)
        for path, module in plant.named_modules()
        if is_plant(module)
        for name, value in module._inputs.items()
    }
    return {"inputs": to_plain(deepcopy(stated))} if stated else {}


def class_dict(plant, fresh):
    """Return the plant dict of a plant of a class: ``fresh`` is a new one, without values."""
    plant._baselines[""] = tree_params(fresh)
    data = {"format": FORMAT, "type": type(plant).__name__}
    if plant._size:
        data["size"] = deepcopy(plant._size)
    data["params"] = params_entry(plant, "", plant)
    fluids = {path: module._fluid for path, module in fresh.named_modules()}
    return data | to_sections(plant, plant._sections, fluids) | _inputs_section(plant)


def structure_dict(plant):
    """Return the plant dict of ``plant`` with its modules and connections."""
    data = {
        "format": FORMAT,
        "name": plant.name,
        "modules": modules_entry(plant, plant),
        "connections": deepcopy(plant._connections),
    }
    for side in ("inlets", "outlets"):
        if plant._listed[side]:
            data[side] = {name: _port_text(end) for name, end in plant._listed[side].items()}
    if plant._output_entries is not None:
        data["outputs"] = deepcopy(plant._output_entries)
    if plant._constraints:
        data["constraints"] = [item.as_dict() for item in plant._constraints]
    return data | to_sections(plant, plant._sections) | _inputs_section(plant)
