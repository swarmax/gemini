"""The capacity each unit of a plant needed in a run."""

import numpy as np

from gemini.evaluate._utils.cost import equipment
from gemini.evaluate._utils.ratings import rating_of
from gemini.run._utils.apply import apply_case
from gemini.types.shapes import measure


def capacities(plant, case, results):
    """Return the design capacity of each equipment module of a plant and its peak use in a run.

    A module that is equipment and has a rating is listed: boilers, the CHP, heat pumps and chillers
    by their capacity [W], the doublets by their nominal flow [m3/s], the circulation pumps by
    their flow, and the exchangers, tanks and pipes by their conductance [W/K], volume [m3] and
    length [m]. A fixed item, a well and a module without a rating have no capacity and are not
    listed.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    case : Case
        The case of the run; it gives the design values of the plant.
    results : Results
        A finished run.

    Returns
    -------
    dict
        ``{path: {kind, capacity, peak, share}}`` for each module: ``capacity`` and ``peak`` are
        ``gm.units.Quantity`` values in SI, the design capacity and the largest use of any step,
        and ``share`` is ``peak / capacity`` [-]. ``peak`` and ``share`` are ``None``, with a
        ``reason``, for a module whose use the run does not show.
    """
    frame = results.to_frame()
    found = {}
    for path, module in equipment(apply_case(plant, case)).items():
        rating = rating_of(module)
        if rating is not None:
            found[path] = _entry(module, rating, frame, path)
    return found


def _entry(module, rating, frame, path):
    """Return the capacity, the peak use and the share of one module."""
    capacity = getattr(module, rating.parameter)
    used = rating.use(frame, path)
    entry = {"kind": module.equipment_kind, "capacity": measure(capacity, rating.unit)}
    if used is None or not used.notna().any():
        reason = "the run shows no use of this module"
        return entry | {
            "peak": measure(None, rating.unit, reason),
            "share": measure(None, "-", reason),
        }
    peak = float(np.nanmax(used.to_numpy(dtype=float)))
    return entry | {
        "peak": measure(peak, rating.unit),
        "share": measure(peak / capacity, "-"),
    }
