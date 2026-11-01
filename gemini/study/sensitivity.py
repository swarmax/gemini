"""How much the metrics of a plant depend on each of its parameters."""

from gemini.errors import NotImplementedYet


def sensitivity(plant, problem, parameters, metrics, *, plan=None):
    """Return how each metric changes when each parameter moves, one at a time.

    Parameters
    ----------
    plant : Module
        A plant with parameter values.
    problem : Problem
        What the plant is asked to do.
    parameters : list of str
        The parameters ``"path.parameter"`` to move.
    metrics : list of str
        The metrics to read, as for ``minimize``.
    plan : DataFrame, optional
        The run input held fixed, for a building block with no demand.

    Raises
    ------
    NotImplementedYet
        Always: the sensitivity is not built yet.
    """
    raise NotImplementedYet("study.sensitivity")
