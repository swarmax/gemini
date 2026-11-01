"""Finished-run results built from given leaf columns, for tests of what reads a run."""

from datetime import datetime, timedelta, timezone

import numpy as np

from gemini.engine.chunks import PathColumns, ResultChunk
from gemini.run.results import Results

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def heat_ports(values):
    """Return the columns of a ``HeatingGrid`` delivering ``values`` [W]; NaN stays missing."""
    return {
        "supply_in.enthalpy_flow": values,
        "return_out.enthalpy_flow": [0.0 * value for value in values],
    }


def cold_ports(values):
    """Return the columns of a ``CoolingGrid`` delivering ``values`` [W]; NaN stays missing."""
    return {
        "supply_in.enthalpy_flow": [0.0 * value for value in values],
        "return_out.enthalpy_flow": values,
    }


def make_results(columns, step=3600.0, units=None):
    """Return results holding ``columns`` as ``{path: {field: values}}`` at ``step`` seconds.

    ``units`` is ``{path: {field: unit}}`` as the engine records it; every column needs the
    same number of values.
    """
    count = len(next(iter(next(iter(columns.values())).values())))
    times = [START + timedelta(seconds=step * tick) for tick in range(count)]
    tables = {
        path: PathColumns(
            np.ones(count, dtype=bool),
            {field: np.asarray(values, dtype=float) for field, values in fields.items()},
        )
        for path, fields in columns.items()
    }
    results = Results(units)
    results.commit(ResultChunk(times, [step] * count, tables, [{}] * count))
    return results
