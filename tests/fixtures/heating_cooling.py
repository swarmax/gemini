"""The heating and cooling plants of the sample case and days of their demand.

The days are round numbers every plant covers.
"""

import pandas as pd

from tests.fixtures.sample_cases import sample_case, template_plant

HEAT = 12e6
"""Heating demand of the days [W]."""
COLD = 5e6
"""Cooling demand of the days [W]."""


def filled_dict(name):
    """Return the plant dict of plant class ``name`` with the values of the sample case."""
    return template_plant(name).to_dict(structure=True)


def days_case(heat, cold=None, start="2027-07-01"):
    """Return the days of ``heat`` [W] (and ``cold``) under the sample case, without its duration.

    The environment, limits and prices are the sample case's; its 330 d duration constraint is
    left out, because the days are fewer.
    """
    case = sample_case()
    index = pd.date_range(start, periods=len(heat), freq="D", tz="UTC", name="time")
    data = {"heating_demand": heat} | ({} if cold is None else {"cooling_demand": cold})
    frame = pd.DataFrame(data, index=index)
    frame.attrs = {"units": dict.fromkeys(frame, "W"), "quantities": dict.fromkeys(frame, "power")}
    time = case.time.model_copy(update={"start": index[0], "end": index[-1] + index.freq})
    demand = case.demand.model_copy(update={"frame": frame})
    constraints = tuple(item for item in case.constraints if item.over != "duration")
    return case.model_copy(update={"time": time, "demand": demand, "constraints": constraints})


def two_days():
    """Return two days of demand [W]."""
    return days_case([HEAT] * 2, [COLD] * 2).demand.frame


def two_days_case():
    """Return the two days under the sample case."""
    return days_case([HEAT] * 2, [COLD] * 2)
