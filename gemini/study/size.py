"""Size the units of a plant for a problem."""

from gemini.errors import NotImplementedYet


def size(plant, problem, *, plan=None):
    """Return the capacity of each unit of a plant that meets the problem at least cost.

    Parameters
    ----------
    plant : Module
        A plant with parameter values.
    problem : Problem
        What the plant is asked to do.
    plan : DataFrame, optional
        The run input held fixed, for a building block with no demand.

    Raises
    ------
    NotImplementedYet
        Always: the sizing is not built yet.
    """
    raise NotImplementedYet("study.size")
