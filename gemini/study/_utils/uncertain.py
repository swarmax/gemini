"""The uncertain values a case declares: the only ones ``sample`` and ``sensitivity`` move."""

from gemini.errors import ValidationError
from gemini.study._utils.target import CASE_PREFIX, case_field


def declared(case, study):
    """Return ``[(name, uncertainty, value)]``, ``name`` as ``case.<path>`` and value in SI.

    Raises ``missing_value`` when the case declares none.
    """
    if not case.uncertainty:
        raise ValidationError(
            f"study.{study}: the case declares no uncertainty; expected an 'uncertainty' next to a "
            "number of environment or assumptions in case.json",
            path="case.uncertainty",
            code="missing_value",
        )
    found = []
    for path, uncertainty in case.uncertainty.items():
        name = f"{CASE_PREFIX}{path}"
        found.append((name, uncertainty, case_field(case, name)[1]))
    return found
