"""Levelised cost of cold."""

from gemini.evaluate._utils.levelised import levelised


def lcoc(plant, case, results, discount_rate=None, lifetime=None, on_error="raise"):
    """Return the levelised cost of cold [currency/J]; the cooling twin of ``lcoh``.

    The same formula with the cold delivered (what the water gains across the ``CoolingGrid``
    leaves) in place of the heat, and for a plant that also delivers heat the share of the cost
    ``allocation.heat_cost_share`` leaves. The parameters and the return shape are those of
    ``lcoh``.
    """
    return levelised(plant, case, results, "cold", (discount_rate, lifetime), on_error)
