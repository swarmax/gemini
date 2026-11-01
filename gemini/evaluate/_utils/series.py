"""Plant-level time series read from the leaf columns of a finished run."""

import numpy as np

from gemini._utils.strings import join_path
from gemini.modules.grids import CoolingGrid, HeatingGrid
from gemini.modules.module import Module


def _summed(frame, columns):
    """Return the sum of ``columns`` of ``frame``, NaN where none has a value, or ``None``."""
    return frame[columns].sum(axis=1, min_count=1) if columns else None


def leaf_total(plant, frame, field, module_class=Module):
    """Return the sum of column ``field`` over the leaves of ``module_class``, or ``None``.

    Parameters
    ----------
    plant : Module
        The plant whose leaves wrote the columns.
    frame : pandas.DataFrame
        ``results.to_frame()``: one ``path.field`` column per leaf output or port field.
    field : str
        Column name below the leaf path, such as ``"unmet_demand"`` or ``"gas_out.chemical_flow"``.
    module_class : type, optional
        Only leaves that are instances of this class count; every leaf by default.

    Returns
    -------
    pandas.Series or None
        The sum on the result time index, in the unit of the column. A tick where no summed
        column has a value is NaN. ``None`` when no leaf of the class has the column.
    """
    columns = [
        join_path(path, field)
        for path, module in plant.named_modules()
        if module.is_leaf and isinstance(module, module_class) and join_path(path, field) in frame
    ]
    return _summed(frame, columns)


def port_difference(plant, frame, module_class, first, second):
    """Return the sum over leaves of ``module_class`` of port field ``first`` less ``second``.

    Fields are ``<port>.<quantity>``: what a grid delivers is what its water loses between its
    ports. ``None`` when no such leaf ran. A tick where a column has no value is NaN.
    """
    paths = [
        path
        for path, module in plant.named_modules()
        if module.is_leaf and isinstance(module, module_class) and join_path(path, first) in frame
    ]
    if not paths:
        return None
    return sum(frame[join_path(path, first)] - frame[join_path(path, second)] for path in paths)


HEAT_DELIVERED = (HeatingGrid, "supply_in.enthalpy_flow", "return_out.enthalpy_flow")
"""The class and the two ports whose enthalpy flows give the heat delivered [W]."""

COLD_DELIVERED = (CoolingGrid, "return_out.enthalpy_flow", "supply_in.enthalpy_flow")
"""The class and the two ports whose enthalpy flows give the cold delivered [W]."""


def useful_heat(plant, frame):
    """Return the useful heat [W]: what the ``HeatingGrid`` leaves took, at most their demand."""
    delivered = port_difference(plant, frame, *HEAT_DELIVERED)
    surplus = leaf_total(plant, frame, "surplus", HeatingGrid)
    return delivered if surplus is None or delivered is None else delivered - surplus


def useful_cold(plant, frame):
    """Return the useful cold [W]: what the ``CoolingGrid`` leaves took, at most their demand."""
    delivered = port_difference(plant, frame, *COLD_DELIVERED)
    surplus = leaf_total(plant, frame, "surplus", CoolingGrid)
    return delivered if surplus is None or delivered is None else delivered - surplus


def results_total(results, frame, field):
    """Return the sum of output ``field`` over every path of ``results`` that has it.

    ``frame`` is ``results.to_frame()``. The result is a series in the unit of the field, NaN on
    a tick where no summed column has a value, or ``None`` when no path has the field.
    """
    columns = [
        join_path(path, field) for path, fields in results.names().items() if field in fields
    ]
    return _summed(frame, columns)


def steps(power, seconds):
    """Return the energy [J] of each tick of a power series [W] over durations [s]; NaN gives 0."""
    return np.nan_to_num(power.to_numpy(dtype=float)) * seconds


def energy(power, seconds):
    """Return the energy [J] of a power series [W] over tick durations [s], skipping NaN ticks."""
    return float(steps(power, seconds).sum())
