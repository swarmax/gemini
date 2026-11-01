"""A composite that derives a child value, as ``modules.md`` shows it."""

from gemini.modules import ProductionReservoir
from gemini.modules.declarations import Parameter
from gemini.physics import hydraulics
from gemini.plants.plant import Plant
from gemini.types import Density, Length


class Column(Plant):
    """A reservoir whose pressure comes from the height of its water column."""

    category = "plants"

    abstract = True

    def __init__(self):
        """Declare the child and the design values it derives from."""
        super().__init__()

        # Modules
        self.reservoir = ProductionReservoir()

        # Parameters
        self.height = Parameter(Length | None, default=None)
        self.density = Parameter(Density | None, default=None)

    def _set_si_params(self, path, params, valid_from=None):
        """Derive the reservoir pressure, unless the same call states it."""
        if path:
            return super()._set_si_params(path, params, valid_from)
        values = self._own_values(params, valid_from)
        derived = {}
        if values["height"] is not None and values["density"] is not None:
            pressure = hydraulics.hydrostatic_dp(values["density"], values["height"])
            derived["reservoir.pressure"] = pressure
        return super()._set_si_params("", self._keep_derived(derived, params) | params, valid_from)
