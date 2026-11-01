"""Costs that scale with a size: a unit cost times a quantity."""

from gemini import ops


@ops.physics
def scaled(factor: float, size: float) -> float:
    """Return the cost of a size at a unit cost, ``C = f s``.

    Parameters
    ----------
    factor : float
        Unit cost [currency per unit of the size], or a yearly share [1/yr] of a cost.
    size : float
        The size [W, m, m3, W/K, 1], or the cost [currency] the share applies to.

    Returns
    -------
    float
        The cost [currency], or the yearly cost [currency/yr] of a share.

    Notes
    -----
    Linear cost scaling, as the capex factors of the Danish Energy Agency, Technology Data for
    Energy Plants (2020), and a fixed operating cost as a share of the capex per year. No economy of
    scale, learning or replacement.
    """
    return factor * size
