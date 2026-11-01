"""The rating of each kind of equipment and the use the run made of it."""

from collections import namedtuple

from gemini.modules.cooling import AbsorptionUnit, AdsorptionChiller
from gemini.modules.exchangers import Cooler, HeatExchanger
from gemini.modules.heating import CHP, Boiler, ElectricBoiler, HeatPump
from gemini.modules.piping import Pipe
from gemini.modules.pumps import CentrifugalPump, CirculationPump
from gemini.modules.storage import ThermalStorage
from gemini.plants import Doublet

Rating = namedtuple("Rating", "parameter unit use")
"""The parameter that holds the rating, its SI unit, and ``use(frame, path)`` that gives the series
of what the run used, in the same unit, or ``None`` when the run holds no such column."""


def _column(name):
    """Return the reader of the leaf column ``name`` of a module."""

    def use(frame, path):
        return frame[f"{path}.{name}"] if f"{path}.{name}" in frame else None

    return use


def _gain(inlet, outlet):
    """Return the reader of the enthalpy flow [W] that a stream gains between two ports."""

    def use(frame, path):
        names = [f"{path}.{port}.enthalpy_flow" for port in (inlet, outlet)]
        return frame[names[1]] - frame[names[0]] if all(name in frame for name in names) else None

    return use


def _no_reading(frame, path):
    """Return ``None``: the run holds no use of this equipment."""


RATINGS = {
    Boiler: Rating("capacity", "W", _gain("fluid_in", "fluid_out")),
    ElectricBoiler: Rating("capacity", "W", _gain("fluid_in", "fluid_out")),
    CHP: Rating("electric_capacity", "W", _column("power_out")),
    AbsorptionUnit: Rating("capacity", "W", _gain("chilled_out", "chilled_in")),
    AdsorptionChiller: Rating("capacity", "W", _gain("chilled_out", "chilled_in")),
    Cooler: Rating("capacity", "W", _gain("fluid_out", "fluid_in")),
    Doublet: Rating("nominal_flow", "m3/s", _column("reservoir.liquid_flow")),
    CirculationPump: Rating("flow", "kg/s", _column("fluid_out.mass_flow")),
    CentrifugalPump: Rating("best_efficiency_flow", "m3/s", _column("fluid_in.volume_flow")),
    HeatExchanger: Rating("thermal_conductance", "W/K", _no_reading),
    ThermalStorage: Rating("volume", "m3", _no_reading),
    Pipe: Rating("length", "m", _no_reading),
}
"""The rating of each class of equipment that has one.

A heat pump is rated by ``capacity`` and is read with ``rating_of``, which picks the side that its
mode makes useful."""


def rating_of(module):
    """Return the ``Rating`` of an equipment module, or ``None`` when it has none."""
    if isinstance(module, HeatPump):
        use = (
            _gain("sink_in", "sink_out")
            if module.mode == "heating"
            else _gain("source_out", "source_in")
        )
        return Rating("capacity", "W", use)
    return next((rating for cls, rating in RATINGS.items() if type(module) is cls), None)
