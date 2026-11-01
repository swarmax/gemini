"""The variables of a search: the choices of the case, or the list a caller gives."""

from gemini import units
from gemini._utils.strings import join_path
from gemini.errors import ValidationError
from gemini.plants._utils.roles import units_of
from gemini.study._utils.resize import resized
from gemini.study._utils.roles import concrete
from gemini.study._utils.target import check_name, value_si

STRUCTURE = "size.doublets"
"""The name of the number of doublets, a structural size of the plant class."""


LIMITS = ("lower", "upper")
"""The keys of the bounds of a variable."""


def from_choices(case):
    """Return the variables of ``case.choices``: ``size.doublets`` and ``depth``, as dicts."""
    choices = case.choices
    if choices is None:
        raise ValidationError(
            "choices is missing; expected a value in the case (it has no default), or the "
            "variables of the call",
            path="choices",
            code="missing_value",
        )
    found = []
    if choices.doublets is not None:
        found.append(_variable(STRUCTURE, choices.doublets.min, choices.doublets.max))
    if choices.depth is not None:
        found.append(
            _variable(
                "depth",
                *(units.Quantity(end, "m") for end in (choices.depth.min, choices.depth.max)),
            )
        )
    if not found:
        raise ValidationError(
            "choices: no doublets and no depth; expected at least one",
            path="choices",
            code="missing_value",
        )
    return found


def _variable(name, lower, upper):
    path, _, parameter = name.rpartition(".")
    return {"path": path, "parameter": parameter, "lower": lower, "upper": upper}


def split(plant, case, variables):
    """Return ``(counts, names, bounds, fixed)`` of the variables of a call.

    ``counts`` are the doublet counts, ``names`` and ``bounds`` the continuous variables in SI,
    and ``fixed`` the variables the plant cannot take.

    ``counts`` is ``[None]`` when the number of doublets is no variable. A variable on a role the
    plant lacks, and the doublets of a plant that takes no ``size.doublets``, are not searched:
    each is a ``{name, value, reason}`` of ``fixed``. A name or a bound that does not fit raises
    before any run, and so does a call with nothing left to search (``invalid_design``).
    """
    if not variables:
        raise ValidationError(
            "study.minimize: variables = []; expected at least one",
            path="variables",
            code="missing_value",
        )
    counts, names, bounds, fixed = [None], [], [], []
    for item in variables:
        name = join_path(item["path"], item["parameter"])
        if name == STRUCTURE:
            counts = _counts(plant, item, fixed)
        elif concrete(plant, name):
            names.append(name)
            bounds.append(_bounds(plant, case, name, item))
        else:
            fixed.append({"name": name, "value": None, "reason": _lacks(name)})
    if counts == [None] and not names:
        reasons = "; ".join(f"{item['name']}: {item['reason']}" for item in fixed)
        raise ValidationError(
            f"study.minimize: nothing can be searched; {reasons}",
            path=fixed[0]["name"],
            code="invalid_design",
        )
    return counts, names, bounds, fixed


def _lacks(name):
    """Return why a variable on a role is not searched."""
    role = name.partition(".")[0]
    return f"the plant has no unit of the role {role!r}"


def _bounds(plant, case, name, item):
    """Return the closed bounds of a variable in SI, checked against its first concrete name."""
    first = concrete(plant, name)[0]
    check_name(plant, case, first)
    lower, upper = (value_si(plant, case, first, item[end]) for end in LIMITS)
    if not lower < upper:
        raise ValidationError(
            f"study.minimize: {name}: lower = {item['lower']}, upper = {item['upper']}; "
            "expected lower below upper",
            path=name,
        )
    return lower, upper


def _counts(plant, item, fixed):
    """Return the numbers of doublets of a variable, every integer from lower to upper.

    A plant that takes no ``size.doublets`` keeps its count, which goes to ``fixed``.
    """
    lower, upper = int(item["lower"]), int(item["upper"])
    if lower > upper:
        raise ValidationError(
            f"study.minimize: {STRUCTURE}: lower = {lower}, upper = {upper}; expected lower <= "
            "upper",
            path=STRUCTURE,
            code="out_of_bounds",
        )
    if (plant.to_dict().get("size") or {}).get("doublets") is None:
        count = len(units_of(plant, "doublet"))
        reason = f"{type(plant).__name__} takes no structural size 'doublets'"
        fixed.append({"name": STRUCTURE, "value": units.Quantity(count, "-"), "reason": reason})
        return [None]
    resized(plant, lower)
    return list(range(lower, upper + 1))
