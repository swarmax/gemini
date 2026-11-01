"""What the plants on a chosen number of doublets share: the size, the wiring and the depth."""

from gemini.errors import ValidationError
from gemini.modules.container import ModuleList
from gemini.modules.declarations import Parameter
from gemini.modules.piping import Mixer, Splitter
from gemini.plants._utils.wiring import mix_chain
from gemini.plants.doublet import Doublet
from gemini.plants.plant import Plant
from gemini.types import Length


class DoubletsPlant(Plant):
    """A plant on ``doublets`` doublets ``d0`` to ``d{n-1}``, wired in parallel.

    The supply of each doublet joins through ``doublets - 1`` mixers and the injected brine divides
    over ``doublets - 1`` splitters, ``gm.schedule`` setting the split from the flows. ``depth``
    goes to every doublet, which derives its reservoir from it; a value stated on one doublet wins.
    """

    abstract = True

    minimum_doublets = 1
    maximum_doublets = 3

    def __init__(self, doublets=1):
        """Build the doublets of the size, a structural argument, and what joins them."""
        super().__init__()
        if not self.minimum_doublets <= doublets <= self.maximum_doublets:
            raise ValidationError(
                f"{type(self).__name__}: doublets = {doublets}; expected "
                f"{self.minimum_doublets} to {self.maximum_doublets}",
                path="size.doublets",
                code="invalid_design",
            )
        self._size = {"doublets": doublets}

        # Modules
        for index in range(doublets):
            setattr(self, f"d{index}", Doublet())
        self.production_mixers = ModuleList(Mixer() for _ in range(doublets - 1))
        self.injection_splitters = ModuleList(Splitter() for _ in range(doublets - 1))

        # Parameters
        self.depth = Parameter(
            Length | None,
            default=None,
            description="True vertical depth of the reservoir midpoint, given to every doublet",
        )

    def _set_si_params(self, path, params, valid_from=None):
        """Pass ``depth`` to every doublet, unless the same call states one's own."""
        if path:
            return super()._set_si_params(path, params, valid_from)
        depth = self._own_values(params, valid_from)["depth"]
        derived = {} if depth is None else {f"d{i}.depth": depth for i in self._indices()}
        return super()._set_si_params("", self._keep_derived(derived, params) | params, valid_from)

    def _indices(self):
        return range(self._size["doublets"])

    def _connect_production(self, target):
        """Join the supply of the doublets, in order, into the inlet ``target``."""
        ends = [f"d{index}.supply_out" for index in self._indices()]
        mix_chain(self, ends, "production_mixers", target)

    def _connect_injection(self, source):
        """Divide the brine of the outlet ``source`` over the doublets, one splitter each."""
        running = source
        for index in self._indices()[:-1]:
            splitter = f"injection_splitters.{index}"
            self.connect(running, f"{splitter}.fluid_in")
            self.connect(f"{splitter}.branch1_out", f"d{index}.return_in")
            running = f"{splitter}.branch2_out"
        self.connect(running, f"d{self._indices()[-1]}.return_in")

    def _connect_power(self, source):
        """Connect the pump of every doublet to the outlet ``source``."""
        for index in self._indices():
            self.connect(source, f"d{index}.power_in")
