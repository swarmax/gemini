"""The yearly cash flow of a plant run, shared by the net present value and the payback."""

from gemini.evaluate._utils.cost import investment, yearly_cost
from gemini.evaluate._utils.flows import Flows


def net_cash_flow(plant, problem, results, on_error):
    """Return ``(capex, yearly net cash flow, unit, reason)``; no cost gives ``None`` numbers.

    ``plant`` already has its site. The revenue is the heat and the cold sold at their prices.
    """
    cost = investment(plant, problem.assumptions, on_error)
    if cost.value is None:
        return None, None, cost.unit, cost.reason
    yearly = yearly_cost(plant, problem, results, "raise")
    flows = Flows(plant, results)
    revenue = flows.cost("heat", problem) + flows.cost("cold", problem)
    return cost.value, revenue - yearly.value, cost.unit, None
