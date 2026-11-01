"""CO2 emitted by a finished run, and the fuel and grid energy it draws."""

from gemini.evaluate._utils.co2_steps import emissions_steps, grid_steps, released_steps
from gemini.evaluate._utils.outcome import reported
from gemini.types.shapes import measure


def co2(plant, case, results, on_error="raise"):
    """Return the CO2-equivalent emitted over the run [kg].

    The sum over the leaves of ``co2_emission``, plus ``methane_emission`` times
    ``emissions.CH4.gwp``, plus grid electricity energy times ``emissions.CO2.electricity``, step
    by step, so that a factor that is a profile follows the run. Emissions come from what each
    module burns or releases, so they follow the gas composition. On-site generation offsets
    consumption before grid electricity is counted and a surplus earns no credit.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    case : Case
        Its assumptions give ``emissions.CH4.gwp`` and ``emissions.CO2.electricity`` [kg/J]; a
        factor is needed only when the run releases methane or draws grid electricity.
    results : Results
        A finished run; the emissions of ``Atmosphere`` and ``net_import`` of the
        ``ElectricityGrid`` are integrated, and the ``fuel`` of the burners.
    on_error : {"raise", "record"}, optional
        A value the inputs cannot give raises; ``"record"`` makes it ``None`` with a ``reason``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, direct, methane, electricity, fuel_energy,
        grid_energy, window}``: ``value`` in kg over the window of the results; ``direct`` the
        CO2, ``methane`` the methane released and ``electricity`` the CO2 of grid electricity, in
        kg; ``fuel_energy`` and ``grid_energy`` in J and ``window`` in s,
        each a value. A factor the run needs and the case lacks raises ``ValidationError`` (code
        ``missing_assumption``).
    """
    return reported(on_error, "kg", lambda: _co2(plant, case, results))


def _co2(plant, case, results):
    """Return the CO2-equivalent of a run."""
    direct, methane, equivalent, electricity = emissions_steps(plant, case, results)
    return measure(
        float((direct + equivalent + electricity).sum()),
        "kg",
        direct=measure(float(direct.sum()), "kg"),
        methane=measure(float(methane.sum()), "kg"),
        electricity=measure(float(electricity.sum()), "kg"),
        fuel_energy=measure(float(released_steps(results, "fuel").sum()), "J"),
        grid_energy=measure(float(grid_steps(plant, results).sum()), "J"),
        window=measure(float(results.durations.sum()), "s"),
    )
