"""All checks of a finished run together."""

from gemini._utils.jsonable import to_plain
from gemini.evaluate._utils.verdict import verdict
from gemini.evaluate.bounds import bounds
from gemini.evaluate.constraints import constraints
from gemini.evaluate.energy_balance import energy_balance
from gemini.evaluate.mass_balance import mass_balance


def run_all(plant, case, results):
    """Run the energy ledger, the mass ledger, the bounds and the constraints on a finished run.

    Parameters
    ----------
    plant : Module
        The plant that produced ``results``.
    case : Case
        The case of the run; its constraints and its service requirements are checked.
    results : Results
        A finished run.

    Returns
    -------
    dict
        Plain JSON ``{passed, checks}``: ``checks`` lists the results of ``energy_balance``,
        ``mass_balance`` and ``bounds``, then those of ``constraints`` (each
        ``{name, passed, value, limit}``), and ``passed`` is ``False`` if any check failed,
        ``True`` if none failed and at least one passed, and ``None`` if none could judge.
    """
    checks = [
        energy_balance(plant, case, results),
        mass_balance(plant, case, results),
        bounds(plant, case, results),
        *constraints(plant, case, results),
    ]
    return to_plain({"passed": verdict([item["passed"] for item in checks]), "checks": checks})
