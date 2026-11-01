"""The heating and cooling plants of the sample problem and two days of their demand.

The days are round numbers every plant covers.
"""

import pandas as pd

import gemini as gm
from tests.fixtures.sample_problems import sample_problem, template_plant

HEAT = 12e6
"""Heating demand of the days [W]."""
COLD = 5e6
"""Cooling demand of the days [W]."""
CONSTRAINTS = [
    gm.Constraint(
        "d*.reservoir.liquid_flow",
        min={"value": 50, "unit": "m3/h"},
        max={"value": 300, "unit": "m3/h"},
        when="running",
    ),
    gm.Constraint("d*.brine_cooling", max={"value": 40, "unit": "K"}, when="running"),
]


def filled_dict(name):
    """Return the plant dict of plant class ``name`` with the values of the sample problem."""
    return template_plant(name).to_dict(structure=True)


def two_days():
    """Return two days of demand [W]."""
    index = pd.date_range("2027-07-01", periods=2, freq="D", tz="UTC", name="time")
    return pd.DataFrame({"heating_demand": HEAT, "cooling_demand": COLD}, index=index)


def two_days_problem():
    """Return the two days under the limits and prices of the sample problem, without its site."""
    return gm.Problem(two_days(), constraints=CONSTRAINTS, assumptions=sample_problem().assumptions)
