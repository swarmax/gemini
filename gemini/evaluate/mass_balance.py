"""Sign check of the mass flows of a run."""

from gemini.evaluate._utils.ledger import columns, nonnegative

MASS_TOLERANCE = 1e-12
"""Smallest negative mass flow [kg/s] still read as zero."""


def mass_balance(plant, case, results):
    """Check the mass-flow ledger of a finished run: no mass flow is negative or infinite.

    It covers the columns whose unit in ``results.units`` is kg/s (for example
    ``degasser.gas_out.mass_flow``): each value must be finite or missing and not negative beyond
    the tolerance. ``plant_balance`` checks the closure.

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
        ``{name: "mass_balance", passed, value, limit}``: ``value`` is the smallest mass flow
        [kg/s], ``limit`` 1e-12 kg/s. ``passed`` is ``None``, with a ``reason`` in ``value``, when
        no output has the unit kg/s, or no value exists.
    """
    values = columns(results, lambda path, field: results.unit(path, field) == "kg/s")
    absent = "results have no output in kg/s"
    return nonnegative("mass_balance", values, MASS_TOLERANCE, "kg/s", absent)
