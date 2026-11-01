"""The variables of a search: the choices of the case, or the list a caller gives."""

from gemini import units
from gemini._utils.strings import join_path
from gemini.errors import ValidationError
from gemini.study._utils.resize import resized
from gemini.study._utils.target import check_name, value_si

STRUCTURE = "size.doublets"
"""The name of the number of doublets, a structural size of the plant class."""


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
    """Return ``(counts, names, bounds)``: the doublet counts, and the continuous variables in SI.

    ``counts`` is ``[None]`` when the number of doublets is no variable. A name or a bound that
    does not fit raises before any run.
    """
    if not variables:
        raise ValidationError(
            "study.minimize: variables = []; expected at least one",
            path="variables",
            code="missing_value",
        )
    counts, names, bounds = [None], [], []
    for item in variables:
        name = join_path(item["path"], item["parameter"])
        if name == STRUCTURE:
            counts = _counts(plant, item)
            continue
        check_name(plant, case, name)
        lower, upper = (value_si(plant, case, name, item[end]) for end in ("lower", "upper"))
        if not lower < upper:
            raise ValidationError(
                f"study.minimize: {name}: lower = {item['lower']}, upper = {item['upper']}; "
                "expected lower below upper",
                path=name,
            )
        names.append(name)
        bounds.append((lower, upper))
    return counts, names, bounds


def _counts(plant, item):
    """Return the numbers of doublets of a variable, every integer from lower to upper."""
    lower, upper = int(item["lower"]), int(item["upper"])
    if lower > upper:
        raise ValidationError(
            f"study.minimize: {STRUCTURE}: lower = {lower}, upper = {upper}; expected lower <= "
            "upper",
            path=STRUCTURE,
            code="out_of_bounds",
        )
    resized(plant, lower)
    return list(range(lower, upper + 1))
