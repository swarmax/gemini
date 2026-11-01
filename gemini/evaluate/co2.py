"""CO2 emitted by a finished run, and the fuel and grid energy it draws."""

import numpy as np

from gemini.evaluate._utils.outcome import reported
from gemini.evaluate._utils.series import edge_total, energy, results_total, window_seconds
from gemini.modules.grids import ElectricityGrid
from gemini.types.shapes import measure


def co2(plant, problem, results, on_error="raise"):
    """Return the CO2-equivalent emitted over the run [kg].

    The sum over the leaves of ``co2_emission``, plus ``methane_emission`` times
    ``Assumptions.methane_gwp``, plus grid electricity energy times
    ``electricity_emission_factor``. Emissions come from what each module burns or releases, so
    they follow the gas composition. On-site generation offsets consumption before grid
    electricity is counted and a surplus earns no credit.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    problem : Problem
        Its assumptions give ``methane_gwp`` and ``electricity_emission_factor`` [kg/J].
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
        grid_energy, window}``: ``value``
        in kg over the window of the results; ``direct`` the CO2, ``methane`` the methane released
        and ``electricity`` the CO2 of grid electricity, in kg; ``fuel_energy`` and ``grid_energy``
        in J and ``window`` in s, each a value. Grid electricity drawn without
        ``electricity_emission_factor`` raises ``ValidationError`` (code ``missing_assumption``).
    """
    return reported(on_error, "kg", lambda: _co2(plant, results, problem.assumptions))


def released(results, field):
    """Return the time integral of leaf column ``field`` over the run; without it, zero."""
    total = results_total(results, results.to_frame(), field)
    if total is None:
        return 0.0
    return float(np.nansum(total.to_numpy(dtype=float) * window_seconds(results)))


def _ledger(plant, results, module_class, field):
    """Return the energy [J] of column ``field`` of the leaves of ``module_class`` over a run."""
    frame = results.to_frame()
    total = edge_total(plant, frame, field, module_class)
    return 0.0 if total is None else energy(total, window_seconds(results))


def _co2(plant, results, assumptions):
    """Return the CO2-equivalent of a run."""
    fuel = released(results, "fuel")
    grid = _ledger(plant, results, ElectricityGrid, "net_import")
    direct = released(results, "co2_emission")
    methane = released(results, "methane_emission")
    electricity = 0.0
    if grid > 0:
        electricity = grid * assumptions.emission_factor(required=True)
    return measure(
        direct + methane * assumptions.methane_gwp + electricity,
        "kg",
        direct=measure(direct, "kg"),
        methane=measure(methane, "kg"),
        electricity=measure(electricity, "kg"),
        fuel_energy=measure(fuel, "J"),
        grid_energy=measure(grid, "J"),
        window=measure(float(window_seconds(results).sum()), "s"),
    )
