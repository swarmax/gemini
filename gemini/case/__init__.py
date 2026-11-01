"""The case: what a plant is asked to do and the world around it, for every call.

``gm.Case`` and the classes of its sections, in the order of ``case.json``: ``Time``,
``Environment`` (``Ground``, ``Reservoir``, ``Fluid``, ``Air``), ``Demand`` (``Service``),
``Choices`` (``Range``), ``Constraint`` and ``Assumptions`` (``Finance`` with ``Capex``, ``Opex``,
``Revenue`` and ``Allocation``; ``Emissions`` with ``CO2`` and ``CH4``). ``roles()`` lists the roles
and quantities a ``Constraint`` may name. The case sits above ``gm.plants`` and below ``gm.run``.
"""

from .assumptions import CH4, CO2, Allocation, Assumptions, Capex, Emissions, Finance, Opex, Revenue
from .case import Case
from .choices import Choices, Range
from .constraint import Constraint
from .demand import Demand, Service
from .environment import Air, Environment, Fluid, Ground, Reservoir
from .roletable import roles
from .time import Time

__all__ = [
    "Case",
    "Time",
    "Environment",
    "Ground",
    "Reservoir",
    "Fluid",
    "Air",
    "Demand",
    "Service",
    "Choices",
    "Range",
    "Constraint",
    "Assumptions",
    "Finance",
    "Capex",
    "Opex",
    "Revenue",
    "Allocation",
    "Emissions",
    "CO2",
    "CH4",
    "roles",
]
