"""Cascades of two-way mixers and splitters, the way a plant joins or divides a flow over many."""


def mix_chain(plant, ends, mixers, out=None):
    """Mix the outlets ``ends`` in order through the ``mixers`` and connect the mix to ``out``.

    The running mix enters ``branch1_in`` of each mixer and the next end ``branch2_in``. The
    mixers are the path of a ``ModuleList``, one fewer than the ends.
    """
    running = ends[0]
    for index, end in enumerate(ends[1:]):
        plant.connect(running, f"{mixers}.{index}.branch1_in")
        plant.connect(end, f"{mixers}.{index}.branch2_in")
        running = f"{mixers}.{index}.fluid_out"
    if out is not None:
        plant.connect(running, out)


def split_chain(plant, splitters, targets):
    """Divide the inlet ``splitters.0.fluid_in`` over the inlets ``targets`` in order.

    Each splitter sends its ``branch2_out`` to a target and its ``branch1_out`` on to the next
    splitter, the last one to the last target. The links between splitters are connected first.
    """
    count = len(targets) - 1
    for index in range(count - 1):
        plant.connect(f"{splitters}.{index}.branch1_out", f"{splitters}.{index + 1}.fluid_in")
    for index in range(count):
        plant.connect(f"{splitters}.{index}.branch2_out", targets[index])
    plant.connect(f"{splitters}.{count - 1}.branch1_out", targets[count])


def connect_gas(plant):
    """Connect the degasser gas through the makeup to the peak boiler, the excess to the flare."""
    plant.connect("degasser.gas_out", "gas_makeup.gas_in")
    plant.connect("gas_grid.gas_out", "gas_makeup.grid_in")
    plant.connect("gas_makeup.fuel_out", "peak_boiler.fuel_in")
    plant.connect("gas_makeup.excess_out", "flare.gas_in")


def connect_cooler(plant, hot_out, hot_in, cooler):
    """Reject the heat of the loop ``hot_out`` to ``hot_in`` through the air cooler ``cooler``."""
    plant.connect(hot_out, f"{cooler}.fluid_in")
    plant.connect(f"{cooler}.fluid_out", hot_in)
    plant.connect("atmosphere.air_out", f"{cooler}.air_in")
    plant.connect(f"{cooler}.air_out", "atmosphere.air_in")
    plant.connect("electricity_grid.power_out", f"{cooler}.power_in")
