"""Read an old GEMINI project folder into a plant."""

import warnings
from copy import deepcopy

from gemini._utils import registry
from gemini._utils.mappings import set_nested
from gemini._utils.strings import did_you_mean, join_path
from gemini.errors import GeminiWarning, ValidationError
from gemini.types import Binding, ModuleBindings

from . import tables
from .design import from_legacy_design
from .project import GeminiProject


def si_unit(unit):
    """Return the SI unit an old tag unit converts to."""
    if unit not in tables.SI_UNITS:
        raise ValidationError(
            f"old tag: unit = {unit!r}; expected one of {sorted(tables.SI_UNITS)}"
            f"{did_you_mean(unit, tables.SI_UNITS)}",
            code="invalid_format",
        )
    return tables.SI_UNITS[unit]


_SECTIONS = ("controls", "boundaries", "inlets", "measured", "state")


def _entries(section, values):
    """Yield ``(keys, binding)`` of one bindings section; inlet keys are ``(port, field)``."""
    if section != "inlets":
        return [((field,), binding) for field, binding in values.items()]
    return [
        ((port, field), binding)
        for port, fields in values.items()
        for field, binding in fields.items()
    ]


def _data_column(path, keys):
    """Return the column of the shipped datasets for the binding ``keys`` of the module at ``path``.

    The datasets were written before the port names of the ``<role>_in`` rule and stay as they are.
    """
    port = tables.DATA_PORTS.get((path, keys[0]), keys[0])
    name = join_path(path, ".".join((port, *keys[1:])))
    return tables.DATA_COLUMNS.get(name, name)


def converted_bindings(design):
    """Return SI bindings to new column names, and the old binding of each new column.

    New columns are the bound module path joined with the field (``doublet.esp.frequency``)
    or with the port and field (``doublet.esp.suction.p``).
    """
    converted, sources = {}, {}
    for path, old in design.bindings.items():
        bound = ModuleBindings()
        for section in _SECTIONS:
            for keys, binding in _entries(section, getattr(old, section)):
                name = _data_column(path, keys)
                new = Binding(column=name, unit=si_unit(binding.unit))
                set_nested(getattr(bound, section), keys, new)
                sources[name] = binding
        converted[path] = bound
    return converted, sources


def _filled_module(plant, path, item):
    """Return the plant module at ``path`` with the converted history of ``item``.

    The current values are the latest snapshot (with any explicit override applied once), and
    explicit overrides are cleared because the old project now defines the design.
    """
    module = plant.get_submodule(path)
    expected = tables.MODULE_CLASSES[item.type]
    if not isinstance(module, expected):
        raise ValidationError(
            f"{path}: module type = {type(module).__name__}; expected {expected.__name__} for "
            f"old kind {item.type!r}",
            code="invalid_format",
        )
    module._param_history = [snapshot.model_copy(deep=True) for snapshot in item.params]
    values = module._params_at(None)
    module._param_overrides = {}
    return {"params": values, "fluid": item.fluid.model_dump()}


def to_plant(project, plant):
    """Fill an existing example plant with converted SI parameters, histories and bindings.

    Old fields the bridge cannot map are listed in one ``GeminiWarning``.
    """
    design = from_legacy_design(project)
    if design.unmapped:
        warnings.warn(
            f"Unmapped GEMINI fields: {', '.join(design.unmapped)}", GeminiWarning, stacklevel=2
        )
    state = {path: _filled_module(plant, path, item) for path, item in design.modules.items()}
    state[""] = {"params": {}, "fluid": next(iter(design.modules.values())).fluid.model_dump()}
    plant.set_state_dict(state, strict=False)
    plant.bindings, _ = converted_bindings(design)
    plant.boundary = deepcopy(design.boundary)
    return plant.set_inputs(design.inputs)


def from_folder(folder):
    """Return the plant of the old GEMINI project in ``folder``, ``gm.Plant.from_legacy``.

    The bridge maps the example project's ten nodes (``tables.NODE_PATHS``): another node set, a
    missing ``.param`` file or a unit it does not know raises ``ValidationError``. Old fields that
    have no new counterpart are listed in one ``GeminiWarning``. The data CSV is converted
    separately, by the internal ``gemini.data.legacy.to_dataset``.

    The result is ``DoubletHeatPlant`` filled with the converted SI parameters, dated histories,
    fluids, bindings and assumptions.
    """
    return to_plant(GeminiProject.from_folder(folder), registry.get("DoubletHeatPlant")())
