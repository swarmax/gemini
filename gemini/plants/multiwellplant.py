"""A well field: production and injection limbs joined by mixers and splitters."""

from gemini.errors import ValidationError
from gemini.modules.container import ModuleDict, ModuleList
from gemini.modules.declarations import Inlet, Outlet
from gemini.modules.environment import Formation
from gemini.modules.piping import Mixer, Splitter
from gemini.modules.pumps import ESP
from gemini.modules.subsurface import InjectionReservoir, ProductionReservoir
from gemini.modules.wells import InjectionWell, ProductionWell
from gemini.plants._utils.wiring import mix_chain, split_chain
from gemini.plants.plant import Plant
from gemini.types import Power, Stream


class MultiWellPlant(Plant):
    """A well field of ``producers`` and ``injectors`` limbs.

    Each production limb is a ``ModuleDict`` of ``reservoir``, ``well``, ``esp`` and ``riser`` and
    each injection limb of ``well`` and ``sink``, in the lists ``producers`` and ``injectors``. The
    risers join through ``producers - 1`` mixers and the return divides over ``injectors - 1``
    splitters. The field produces from every limb, mixes, then injects.

    A building block, not schedulable: ``gm.schedule`` plans ``Doublet`` children, and this field
    has none; a run sets each rate, frequency and split.
    """

    purpose = "both"

    def __init__(self, producers=2, injectors=1):
        """Build a field of the given size; both are structural arguments."""
        super().__init__()
        if producers < 1 or injectors < 1:
            raise ValidationError(
                f"producers = {producers}, injectors = {injectors}; expected >= 1",
                code="invalid_design",
            )
        self._size = {"producers": producers, "injectors": injectors}

        # Modules
        self.producers = ModuleList(
            ModuleDict(
                {
                    "reservoir": ProductionReservoir(),
                    "well": ProductionWell(),
                    "esp": ESP(),
                    "riser": ProductionWell(),
                }
            )
            for _ in range(producers)
        )
        self.mixers = ModuleList(Mixer() for _ in range(producers - 1))
        self.splitters = ModuleList(Splitter() for _ in range(injectors - 1))
        self.injectors = ModuleList(
            ModuleDict({"well": InjectionWell(), "sink": InjectionReservoir()})
            for _ in range(injectors)
        )
        self.formation = Formation()

        # Inlets
        self.return_in = Inlet(Stream)
        self.power_in = Inlet(Power, kind="electricity")

        # Outlets
        self.supply_out = Outlet(Stream)

        # Connections
        self._connect_production(producers)
        self._connect_injection(injectors)
        for index in range(producers):
            self.connect("power_in", f"producers.{index}.esp.power_in")
            self.connect(f"producers.{index}.well.loss_out", "formation.heat_in")
            self.connect(f"producers.{index}.riser.loss_out", "formation.heat_in")
        for index in range(injectors):
            self.connect(f"injectors.{index}.well.loss_out", "formation.heat_in")

    def _connect_production(self, producers):
        """Connect every production limb and mix the limbs in order."""
        for index in range(producers):
            limb = f"producers.{index}"
            self.connect(f"{limb}.reservoir.sandface_out", f"{limb}.well.bottom_in")
            self.connect(f"{limb}.well.wellhead_out", f"{limb}.esp.fluid_in")
            self.connect(f"{limb}.esp.fluid_out", f"{limb}.riser.bottom_in")
        ends = [f"producers.{index}.riser.wellhead_out" for index in range(producers)]
        mix_chain(self, ends, "mixers", "supply_out")

    def _connect_injection(self, injectors):
        """Connect every injection limb and divide the return over them, one splitter each."""
        for index in range(injectors):
            self.connect(
                f"injectors.{index}.well.bottom_out", f"injectors.{index}.sink.sandface_in"
            )
        targets = [f"injectors.{index}.well.wellhead_in" for index in range(injectors)]
        if injectors == 1:
            self.connect("return_in", targets[0])
            return
        split_chain(self, "splitters", targets)
        self.connect("return_in", "splitters.0.fluid_in")
