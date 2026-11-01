"""Sign check of the energy outputs of a run."""

from gemini.evaluate._utils.ledger import columns, nonnegative

ENERGY_TOLERANCE = 1e-9
"""Smallest negative power [W] still read as zero."""

_NONNEGATIVE_ENERGY = ("fuel", "power_in", "power_out")
"""The energy columns that are nonnegative; ``loss_out`` and ``heat_accumulation`` are signed."""


def energy_balance(plant, case, results):
    """Check the energy ledger of a finished run: the energy outputs have their sign.

    It reads every leaf column named ``power_in``, ``power_out`` or ``fuel`` and checks that each
    value is finite or missing and not negative beyond the tolerance (``loss_out`` and
    ``heat_accumulation`` are signed and are not judged). ``plant_balance`` checks the closure.

    Parameters
    ----------
    plant : Module
        The plant of the run; the check does not read it.
    case : Case
        The case of the run; the check does not read it.
    results : Results
        A finished run.

    Returns
    -------
    dict
        ``{name: "energy_balance", passed, value, limit}``: ``value`` is the smallest of those
        powers [W] over all columns and ticks, ``limit`` is 1e-9 W and ``passed`` is whether
        ``value >= -limit`` with no infinite value. ``passed`` is ``None``, with a ``reason`` in
        ``value``, when no such column, or no value, exists.
    """
    values = columns(results, lambda path, field: field in _NONNEGATIVE_ENERGY)
    return nonnegative(
        "energy_balance", values, ENERGY_TOLERANCE, "W", "results have no energy output column"
    )
