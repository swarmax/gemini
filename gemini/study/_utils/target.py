"""What a study may vary: a value of the plant, or a value of the case named ``case.<path>``."""

from gemini import units
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.case._utils.fields import Q, QMap, si_unit_of, to_si
from gemini.errors import ValidationError
from gemini.modules.declarations import Parameter

CASE_PREFIX = "case."
"""A name that starts with it is a value of the case, by its path in ``case.json``."""


def is_case_name(name):
    """Whether ``name`` is a value of the case: ``case.`` and the path of the value."""
    return name.startswith(CASE_PREFIX)


def _missing(name):
    return ValidationError(
        f"{name} is missing; expected a value in the case (it has no default)",
        path=name,
        code="missing_value",
    )


def _child(node, part, name):
    """Return the part ``part`` of a section or of a map, or raise saying what is valid."""
    if isinstance(node, dict):
        valid = list(node)
    else:
        valid = list(type(node).model_fields)
    if part not in valid:
        raise ValidationError(
            f"{name}: {part!r} is unknown; expected one of {join_names(valid)}"
            f"{did_you_mean(part, valid)}",
            path=name,
            code="unknown_name",
            suggestions=close_matches(part, valid),
        )
    return node[part] if isinstance(node, dict) else getattr(node, part)


def _meta(node, part, inherited):
    """Return the ``Q`` or ``QMap`` that describes the field ``part`` of ``node``, if any."""
    if isinstance(node, dict):
        return inherited
    found = [item for item in type(node).model_fields[part].metadata if isinstance(item, (Q, QMap))]
    return found[0] if found else None


def case_field(case, name):
    """Return ``(meta, current)`` of the value ``case.<path>``: its quantity and its SI value.

    ``current`` is ``None`` when the value is absent; a section above it that is absent raises
    ``missing_value``. A path that is no number of the case (a list, a text, a date) raises
    ``invalid_value``; an unknown part raises ``unknown_name`` with the valid parts.
    """
    node, meta = case, None
    parts = name.removeprefix(CASE_PREFIX).split(".")
    for index, part in enumerate(parts):
        found = _child(node, part, name)
        meta = _meta(node, part, meta)
        if found is None and index < len(parts) - 1:
            raise _missing(name)
        node = found
    if meta is None or not isinstance(meta, (Q, QMap)):
        raise ValidationError(
            f"{name} is not a number of the case; expected the path of a quantity, such as "
            "case.assumptions.finance.opex.electricity",
            path=name,
            code="invalid_value",
        )
    return meta, node


def _set(node, parts, leaf):
    """Return ``node`` with the value at ``parts`` replaced, copying each section on the way."""
    head, rest = parts[0], parts[1:]
    if isinstance(node, dict):
        return {**node, head: _set(node[head], rest, leaf) if rest else leaf}
    value = _set(getattr(node, head), rest, leaf) if rest else leaf
    return node.model_copy(update={head: value})


def _checked(meta, number):
    """Return a number in SI, refused when it breaks the bounds of the field ``meta``."""
    given = units.Quantity(number, si_unit_of(meta.quantity))
    return meta.convert(given) if isinstance(meta, Q) else to_si(given, meta.quantity)


def with_case_values(case, values):
    """Return a copy of ``case`` with the SI numbers ``{case.<path>: number}`` set.

    A profile becomes the constant. A number that breaks the bounds of its field raises
    ``out_of_bounds``.
    """
    for name, number in values.items():
        meta, _ = case_field(case, name)
        case = _set(case, name.removeprefix(CASE_PREFIX).split("."), _checked(meta, number))
    return case


def _declaration(plant, name):
    """Return the parameter declaration of ``name``, or raise for a name that is no parameter."""
    declaration = plant.get(name)
    if not isinstance(declaration, Parameter):
        raise ValidationError(
            f"study: {name} is not a parameter of the plant; expected a parameter, or a value of "
            f"the case as {CASE_PREFIX}<path>",
            path=name,
            code="invalid_value",
        )
    return declaration


def check_name(plant, case, name):
    """Raise unless ``name`` is a parameter of the plant or a number of the case."""
    if is_case_name(name):
        case_field(case, name)
        return
    _declaration(plant, name)


def unit_of(plant, case, name):
    """Return the SI unit of the value ``name`` as text, ``-`` for a number without a dimension."""
    if is_case_name(name):
        return si_unit_of(case_field(case, name)[0].quantity)
    return _declaration(plant, name).unit or "-"


def value_si(plant, case, name, bound, difference=False):
    """Return ``bound``, a ``Quantity`` or its dict, in the SI unit of the value ``name``.

    A plain number is accepted only for a value without a dimension. A ``difference`` is a spread
    such as a standard deviation, which a unit offset does not move.
    """
    if is_case_name(name):
        return _case_bound(case, name, bound, difference)
    declaration = _declaration(plant, name)
    if isinstance(bound, dict):
        bound = units.Quantity.from_dict(bound)
    if isinstance(bound, units.Quantity):
        number = units.value_in_si(bound, declaration.unit, name, declaration.quantity)
        return number - units.to_si(0, bound.unit) if difference else number
    if declaration.unit not in (None, "-"):
        raise ValidationError(
            f"study: {name} = {bound!r}; expected {units.QUANTITY_FORM}, because the parameter "
            f"has the unit {declaration.unit!r}",
            path=name,
            code="invalid_value",
        )
    return bound


def _case_bound(case, name, bound, difference):
    """Return a bound of a number of the case in SI."""
    meta, _ = case_field(case, name)
    try:
        number = to_si(bound, meta.quantity)
    except ValidationError as error:
        raise ValidationError(f"study: {name}: {error}", path=name, code=error.code) from error
    if difference and isinstance(bound, (dict, units.Quantity)):
        given = units.Quantity.from_dict(bound) if isinstance(bound, dict) else bound
        return number - units.to_si(0, given.unit)
    return number


def quantities(plant, case, values):
    """Return ``{name: Quantity}`` for SI values, each in the SI unit of its value."""
    return {
        name: units.Quantity(number, unit_of(plant, case, name)) for name, number in values.items()
    }
