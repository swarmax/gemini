"""Dated parameters and bindings of a module tree, the one implementation behind ``Module``.

``Module.set_params``, ``params_at``, ``param_history``, ``bindable`` and ``set_bindings`` call
these functions with the module they belong to. Parameters are addressed by a module path below
that module and a (possibly dotted) parameter name; values are validated by their declarations,
so unit strings are accepted and stored in SI.
"""

from collections.abc import Mapping
from copy import deepcopy

from pydantic import ValidationError as PydanticError
from pydantic_core import to_jsonable_python

from gemini import units
from gemini._utils.jsonable import to_plain
from gemini._utils.strings import close_matches, did_you_mean, join_names, join_path
from gemini._utils.time import EARLIEST, to_utc
from gemini.errors import ValidationError
from gemini.types.bindings import Binding, DatedParams, ModuleBindings
from gemini.types.flows import STREAM_FIELDS

FIELD_UNITS = {"m_dot": ("kg/s", "m3/s"), "T": ("K",), "p": ("Pa",)}
"""The SI units a column bound to a stream field may have; a volume flow becomes mass flow."""

NAMED = {
    "controls": "_controls",
    "boundaries": "_boundaries",
    "measured": "_outputs",
    "state": "_states",
}
"""The sections a plain name binds, each with the declarations of a module that hold them."""


def _date(item):
    return item.valid_from or EARLIEST


def snapshot_at(module, at):
    """Return the snapshot of ``module`` in force at ``at``; ``None`` selects the latest."""
    eligible = [
        item
        for item in module._param_history
        if at is None or item.valid_from is None or item.valid_from <= to_utc(at)
    ]
    if not eligible:
        raise ValidationError(f"{module.path}: no parameters valid at {at}", code="invalid_design")
    return max(eligible, key=_date)


def params_at(module, path, time=None):
    """Return the parameter values of the module at ``path`` in force at ``time`` as plain JSON."""
    values = module.get_submodule(path)._params_at(time)
    return to_plain(to_jsonable_python(values))


def param_history(module, path):
    """Return the dated snapshots of the module at ``path`` as ``[{valid_from, params}]``."""
    history = module.get_submodule(path)._param_history
    return to_plain([item.model_dump(mode="json") for item in history])


def parameter(module, name):
    """Return the parameter declaration ``name`` below ``module``; an unknown name suggests one."""
    path, _, local = name.rpartition(".")
    owner = module._find_submodule(path) if path else module
    if owner is not None and local in owner._parameters:
        return owner._parameters[local]
    declarations = dict(module.named_parameters())
    if name not in declarations:
        raise ValidationError(
            f"{module.path}: unknown parameter {name!r}; valid: {join_names(declarations)}"
            f"{did_you_mean(name, declarations)}",
            suggestions=close_matches(name, declarations),
            code="unknown_name",
        )
    return declarations[name]


def _validated_changes(target, params):
    """Return ``{owner: {name: plain SI value}}`` for ``params``, raising before any change."""
    changes = {}
    for name, value in params.items():
        declaration = parameter(target, name)
        validated = declaration.validate(value)
        changes.setdefault(declaration.owner, {})[declaration.name] = to_jsonable_python(
            deepcopy(validated)
        )
    return changes


def _store_snapshot(owner, values, when):
    """Merge ``values`` into the snapshot dated ``when``, or add one built on the one in force."""
    history = owner._param_history
    entry = next((item for item in history if item.valid_from == when), None)
    if entry is not None:
        entry.params = entry.params | values
        return
    before = [
        item
        for item in history
        if when is None or item.valid_from is None or item.valid_from <= when
    ]
    reference = max(before, key=_date) if before else min(history, key=_date)
    history.append(DatedParams(valid_from=when, params=deepcopy(reference.params) | values))
    history.sort(key=_date)


def _deriving_owner(module, name):
    """Return ``(module, name below it)`` of the first module on ``name`` that derives, or None."""
    parts = name.split(".")
    for index in range(1, len(parts)):
        child = module._find_submodule(".".join(parts[:index]))
        if child is not None and child._derives_params():
            return child, ".".join(parts[index:])
    return None


def set_params(module, path, params, valid_from=None):
    """Store a validated, complete snapshot for the module at ``path`` and return ``module``.

    Each snapshot is the values in force at ``valid_from`` merged with ``params``. Without a
    date the undated base entry changes, and so do the current values. A value on the way to a
    module that overrides ``set_params`` goes through that method.
    """
    when = None if valid_from is None else to_utc(valid_from)
    target = module.get_submodule(path)
    changes = _validated_changes(target, params)
    routed = {}
    for name, value in params.items():
        found = _deriving_owner(module, join_path(path, name))
        if found is not None:
            routed.setdefault(found[0], {})[found[1]] = value
            declaration = parameter(target, name)
            del changes[declaration.owner][declaration.name]
    for owner, values in changes.items():
        _store_snapshot(owner, values, when)
        if when is None:
            for name, value in values.items():
                owner._parameters[name].set(value, explicit=False)
                owner._param_overrides.pop(name, None)
    for owner, values in routed.items():
        owner.set_params("", values, valid_from)
    return module


def derived_names(module):
    """Return the dotted names below ``module`` whose values a deriving module computed."""
    return {
        join_path(path, name)
        for path, item in module.named_modules()
        for name in item._derived_params
    }


def bindable(module, path):
    """Return what the module at ``path`` accepts bindings for, by section."""
    target = module.get_submodule(path)
    return {
        "controls": list(target._controls),
        "boundaries": list(target._boundaries),
        "inlets": {port: list(STREAM_FIELDS) for port in target._fed_inlets()},
        "measured": list(target._outputs),
        "state": list(target._states),
    }


def _flat_names(target):
    """Return every key a binding of ``target`` may have, each a declaration name."""
    names = [name for section in NAMED for name in getattr(target, NAMED[section])]
    return names + [f"{port}.{field}" for port in target._fed_inlets() for field in STREAM_FIELDS]


def _unknown(target, key):
    """Return the error of a binding key that ``target`` does not declare."""
    valid = _flat_names(target)
    return ValidationError(
        f"bindings: unknown name {key!r}; valid: {join_names(valid)}{did_you_mean(key, valid)}",
        path=key,
        suggestions=close_matches(key, valid),
        code="unknown_name",
    )


def _section_of(target, key):
    """Return the section that declares the name ``key``; a clash names both."""
    found = [section for section, owner in NAMED.items() if key in getattr(target, owner)]
    if not found:
        raise _unknown(target, key)
    if len(found) > 1:
        raise ValidationError(
            f"bindings: {key!r} is declared as {' and '.join(found)} of {target.path}; "
            "expected a name unique within the module",
            path=key,
            code="invalid_binding",
        )
    return found[0]


def _binding(key, value, unit):
    """Return the binding of a column name, in ``unit``, or of ``{column, unit}``."""
    if isinstance(value, str):
        return Binding(column=value, unit=unit)
    try:
        return Binding.model_validate(value)
    except PydanticError as error:
        raise ValidationError(f"bindings: {error}", path=key, code="invalid_binding") from error


def _add_named(target, bound, key, value):
    """Add the binding of a control, boundary, measured output or state."""
    section = _section_of(target, key)
    declared = getattr(target, NAMED[section])[key].unit
    binding = _binding(key, value, declared or "-")
    if not _fits(binding.unit, _accepted(declared, section)):
        raise _wrong_unit(key, binding, _accepted(declared, section))
    getattr(bound, section)[key] = binding


def _add_field(target, bound, key, value):
    """Add the binding of an inlet field, ``key`` being ``port.field``."""
    port, _, field = key.rpartition(".")
    if port not in target._fed_inlets() or field not in FIELD_UNITS:
        raise _unknown(target, key)
    binding = _binding(key, value, FIELD_UNITS[field][0])
    if not _fits(binding.unit, FIELD_UNITS[field]):
        raise _wrong_unit(key, binding, FIELD_UNITS[field])
    bound.inlets.setdefault(port, {})[field] = binding


def _wrong_unit(key, binding, accepted):
    return ValidationError(
        f"{key}.unit: unit = {binding.unit!r}; expected a unit of {join_names(accepted)}",
        path=f"{key}.unit",
        code="invalid_unit",
    )


def _accepted(declared, section):
    """Return the SI units a column may have for a declaration of unit ``declared``."""
    if not declared:
        return None
    volumetric = declared == "kg/s" and section in ("controls", "boundaries")
    return (declared, "m3/s") if volumetric else (declared,)


def _fits(unit, accepted):
    """Return whether ``unit`` converts to one of the SI units in ``accepted`` (``None``: any)."""
    return accepted is None or units.si_unit(unit) in accepted


def sectioned(target, bindings):
    """Return the ``ModuleBindings`` of the flat ``bindings``, names and units checked.

    A key is a control, boundary, measured output or state of the module, or ``port.field`` of an
    inlet. A value is a column name, whose unit comes from the run input's metadata or else the
    declaration's SI unit, or ``{column, unit}``.
    """
    if not isinstance(bindings, Mapping):
        raise ValidationError(
            f"bindings = {type(bindings).__name__}; expected a mapping of names to columns",
            code="invalid_binding",
        )
    bound = ModuleBindings()
    for key, value in bindings.items():
        add = _add_field if "." in key else _add_named
        add(target, bound, key, value)
    return bound


def _stored(binding, unit):
    """Return a binding as a file holds it: the column alone when ``unit`` is its unit."""
    return binding.column if binding.unit == unit else binding.model_dump()


def flat(target, bound):
    """Return the flat form of the ``ModuleBindings`` of ``target``, or of no module (``None``)."""
    result = {}
    for section, owner in NAMED.items():
        declarations = getattr(target, owner, {})
        for name, binding in getattr(bound, section).items():
            declaration = declarations.get(name)
            unit = declaration.unit if declaration is not None else None
            result[name] = _stored(binding, unit or "-")
    for port, fields in bound.inlets.items():
        for field, binding in fields.items():
            result[f"{port}.{field}"] = _stored(binding, FIELD_UNITS[field][0])
    return result


def set_bindings(module, path, bindings):
    """Replace the bindings of the module at ``path``, checking names and units; return ``module``.

    ``bindings`` maps declaration names to columns (``sectioned``); a binding whose unit does not
    convert to the unit of its declaration is refused.
    """
    parsed = sectioned(module.get_submodule(path), bindings)
    if parsed == ModuleBindings():
        module.bindings.pop(path, None)
    else:
        module.bindings[path] = parsed
    return module


def refuse_bare(declaration, value, path):
    """Raise ``invalid_value`` for a plain number given to a declaration with a unit.

    A public input with a dimension is a ``Quantity`` or its dict: a number alone does not say
    its unit.
    """
    bare = isinstance(value, (int, float, list, tuple)) and not isinstance(value, bool)
    if bare and declaration.unit not in (None, "-"):
        raise ValidationError(
            f"{path} = {value!r}; expected {units.QUANTITY_FORM}, because it has the unit "
            f"{declaration.unit!r}",
            path=path,
            code="invalid_value",
        )
