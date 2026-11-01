"""The yearly cash flow of a plant run, shared by the net present value and the payback."""

from gemini.evaluate._utils.cost import investment, yearly_cost
from gemini.evaluate._utils.flows import Flows


def net_cash_flow(plant, case, results, on_error):
    """Return ``(capex, yearly net cash flow, unit, reason)``; no cost gives ``None`` numbers.

    ``plant`` already has its design values. The revenue is the heat and the cold sold at their
    prices.
    """
    cost = investment(plant, case, on_error)
    if cost.value is None:
        return None, None, cost.unit, cost.reason
    yearly = yearly_cost(plant, case, results, "raise")
    flows = Flows(plant, results)
    revenue = flows.cost("heat", case) + flows.cost("cold", case)
    return cost.value, revenue - yearly.value, cost.unit, None
