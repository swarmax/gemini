# Building plants

A leaf module computes and a plant connects: no class does both ([modules.md](modules.md)). Every
composite is a `Plant`. A plant declares its children, ports and connections and never writes
`forward`: `Plant.forward` is written once. `describe()`, `gm.simulate`, `gm.replay` and `gm.live`
work on any plant, on every backend, and a plant has no run method of its own: run it with
`results = gm.simulate(plant, case)`. How it is computed is in
[native-engine.md](native-engine.md#14-the-plant-class-and-the-plant-dict).

`Plant` is in `gemini/plants/plant.py`, with the plant classes, one file each; `gemini.modules`
never imports `gemini.plants`. Every tool of the plants (the plan, the run, ports, loops, constraints, outputs, the
reader and writer of the plant dict, the schema, the catalogue) is in
`gemini/plants/_utils/`.

Plants are defined in Python. gemini keeps no JSON file; JSON exists only as the plant dict that
agents use: `gm.Plant.from_dict`, `plant.to_dict`, `gm.Plant.from_json`, `plant.to_json`,
`gm.plants.schema`, `gm.plants.validate`.

## A plant class

```python
from gemini.modules import Inlet, Outlet, Output
from gemini.modules.exchangers import HeatExchanger
from gemini.modules.grids import HeatingGrid
from gemini.modules.piping import Valve
from gemini.modules.pumps import CirculationPump
from gemini.plants import Plant
from gemini.types import Power, Stream


class HeatingSubstation(Plant):
    """Indirect district-heating substation serving a building heating circuit."""

    def __init__(self):
        """Declare the children, the ports and the circuits."""
        super().__init__()

        # Modules
        self.valve = Valve()
        self.heat_exchanger = HeatExchanger()
        self.consumer = HeatingGrid()
        self.pump = CirculationPump()

        # Inlets
        self.supply_in = Inlet(Stream, kind="hot_water")
        self.power_in = Inlet(Power, kind="electricity")

        # Outlets
        self.return_out = Outlet(Stream, kind="hot_water")
        self.loss_out = Outlet(Power, kind="heat")

        # Connections
        self.connect("supply_in", "valve.fluid_in")
        self.connect("power_in", "pump.power_in")
        self.connect("valve.fluid_out", "heat_exchanger.hot_in")
        self.connect("heat_exchanger.hot_out", "return_out")
        self.connect("heat_exchanger.cold_out", "consumer.supply_in")
        self.connect("consumer.return_out", "pump.fluid_in")
        self.connect("pump.fluid_out", "heat_exchanger.cold_in")
        self.connect("pump.loss_out", "loss_out")

        # Outputs
        self.approach = Output.difference("heat_exchanger.hot_out.T", "pump.fluid_out.T")
```

The sections are `# Modules`, `# Parameters`, `# Inlets`, `# Boundaries`, `# Outlets`,
`# Connections`, `# Constraints`, `# Outputs`, in that order, empty ones left out. The rules:

- A child assigned as an attribute is registered as `add` does. `super().__init__()` names the plant
  after its class.
- A structural argument goes to `__init__` and into `self._size`, a dict of those arguments:
  `DistrictNetwork(consumers=3, service="cooling")`, `MultiWellPlant(producers=3, injectors=2)`,
  `HeatingCoolingPlant(doublets=2)`.
- A plant class in `gemini/plants/` is registered by its class name. `purpose` says what it
  serves (`heating`, `cooling`, `both`); a building block has none.
- No subclass of `Plant` defines `forward` and no other `Module` holds children
  (`tests/unit/test_code_quality.py`).
- A plant may derive its children's values: see [a plant that sets its children's values](modules.md#a-plant-that-sets-its-childrens-values).

## The builder

```python
import gemini as gm

plant = gm.Plant("Doublet")
plant.add("InjectionWell", name="injector")
plant.add("InjectionReservoir", name="sink")
plant.add("ProductionReservoir", name="reservoir")
plant.add("ProductionWell", name="well")
plant.add("ESP", name="esp")
plant.add("ProductionWell", name="riser")
plant.connect("injector", "sink")
plant.connect("reservoir", "well")
plant.connect("well", "esp")
plant.connect("esp", "riser")
plant.connect("return_in", "injector.wellhead_in")
plant.connect("riser.wellhead_out", "supply_out")
print(plant.summary())
print(gm.plants.validate(plant))
```

`add(type, name=None, params=None)` takes a registry name or a class and one dict of parameters,
the dict `set_params` takes: a `Quantity` or its dict for a value with a dimension (a bare number for it raises `invalid_value`), dotted names for a composite
(`params={"reservoir.temperature": {"value": 87, "unit": "degC"}}`). `connect` takes a handle, `"path.port"` or a module
path. A module path picks the only free port of a fitting kind; a port without a kind fits anything.
If several pairs fit, a `ValidationError` with code `ambiguous_port` lists them. A bare word that
names no module is a plant port, as in `return_in` above. Only `connect` wires modules; there is no
call syntax.

Every inlet and outlet of every module is connected to another module or to a named plant port. A
plant port exists only when it is named; there are no automatic ports. An unconnected port is an
error with code `unconnected_port` and the port path: `gm.plants.validate` and
`from_dict` report it, and a plant with one does not run. While you build, `add` and `connect` do
not check it.

A plant answers what its wiring is: `p.target_of("hx.cold_out")` and `p.source_of("hx.cold_in")` give
the other end of a connection, and `p.feeds("boiler.fluid_out")` the modules an outlet reaches along
its circuit, through mixers, splitters and the units on it, ending at a grid. `gm.schedule` reads the
role of a unit from it.

## The plant dict

The plant dict is the input of an agent's plant-building tool (`gm.plants.schema()` is its schema)
and what the backend stores. It has two forms.

**A plant of a class** stores its class and the values that were given, never its structure or a
derived value. `size` is the one key of every structural argument, next to `type`:

```json
{"format": 2, "type": "MultiWellPlant", "size": {"producers": 3, "injectors": 2},
 "params": {"producers.0.reservoir.temperature": {"value": 87, "unit": "degC"}},
 "bindings": {}, "param_history": {}}
```

**A plant built with `gm.Plant(name)`** has no class and stores its structure. `to_dict(structure=True)`
gives the same form of any plant: this is how an agent edits one, and how it removes a unit, by
taking the unit out of `modules` and `connections` and joining what it joined.

```json
{"format": 2, "name": "Doublet",
 "modules": {"reservoir": {"type": "ProductionReservoir", "params": {}},
             "well": {"type": "ProductionWell", "params": {}},
             "esp": {"type": "ESP", "params": {}},
             "riser": {"type": "ProductionWell", "params": {}},
             "injector": {"type": "InjectionWell", "params": {}},
             "sink": {"type": "InjectionReservoir", "params": {}}},
 "connections": [{"source": "injector.bottom_out", "target": "sink.sandface_in"},
                 {"source": "reservoir.sandface_out", "target": "well.bottom_in"},
                 {"source": "well.wellhead_out", "target": "esp.fluid_in"},
                 {"source": "esp.fluid_out", "target": "riser.bottom_in"}],
 "inlets": {"return_in": "injector.wellhead_in"},
 "outlets": {"supply_out": "riser.wellhead_out"},
 "outputs": {"brine_cooling": {"difference": ["riser.wellhead_out.T", "injector.wellhead_in.T"]}},
 "bindings": {}, "param_history": {}}
```

```python
problems = gm.plants.validate(data, on_error="record")   # every problem at once
plant = gm.Plant.from_dict(data)
assert plant.to_dict() == data
```

| Key | Form | Meaning |
| --- | --- | --- |
| `format` | both | 2 |
| `type`, `size`, `params` | class | the class name, its structural arguments and the flat dotted values that were given |
| `name` | structure | plant name; `module.name` is the name given |
| `modules` | structure | `{id: {type, size?, params}}`; a group is `{type: "ModuleDict", modules: {...}}` |
| `connections` | structure | `[{source, target, type?}]`, ends are `"path.port"` |
| `inlets`, `outlets` | structure | `{plant port: "path.port"}`, a list when several ends share a power or air port |
| `outputs` | structure | `{name: {"difference": [a, b]}}`, `{"ratio": [a, b]}` or `{"sum": [a, b, ...]}`; see [outputs](#outputs) |
| `constraints` | structure | `[{target, equals or at_least, by, bounds}]`; see [constraints](#constraints) |
| `bindings`, `param_history` | both, always | `{path: {name: column}}`; `{path: [{valid_from, params}]}`, the params as `{"value", "unit"}`; see [bindings](#parameters-by-date-and-bindings) |
| `fluids`, `boundary` | both | `{path: {...}}`, the fluid (density, viscosity, specific heat and thermal conductivity as `{"value", "unit"}`) and the stored assumptions of a module |
| `inputs` | both | `{path: value}`, what `plant.set_inputs` was given: controls and boundaries by dotted path, plant inlet fields as `port.field` (`m_dot`, `T`, `p`, `fluid`), quantities for a value with a dimension, numbers for the rest; left out when empty |

- `type` of a module is a registry name. It may name a plant class, whose parameters are then dotted
  (`"esp.stage_count"`), so a plant can contain plants.
- `ModuleDict` and `ModuleList` are groups: they hold children and have no wiring of their own.
  Connections reach through a group (`filters.hot.fluid_out`) but never into a plant child:
  `doublet.supply_out` is right, `doublet.esp.fluid_out` is an error.
- An inlet has one source and an outlet feeds one inlet (`port_in_use`), except a `many` port.
  Splitting and mixing streams are `Splitter` and `Mixer`.
- A port no connection uses is named in `inlets` / `outlets`, or it is `unconnected_port`.
- The order of connections sets the order of the calls where the wiring leaves it open, which is
  what a float sum over the ports depends on. The key order of a dictionary carries no meaning for
  numbers.
- The round trip `from_dict(p.to_dict())` rebuilds the same plant with the same numbers, for every
  shipped plant, quantity dicts included: a stated value stays as written while it equals the current
  one. The backend digests sorted-key JSON.
- A `fluids` entry passes to the modules below it, unless the section names one of them: then it
  speaks for each. The fluid of a plant set in code passes to every child.

`gm.plants.schema()` is generated from the code: the two forms, the enum of registered types, the
output forms. `gm.plants.validate(data)` takes the dict or a `Plant` (it checks the plant's own `to_dict(structure=True)`, so a plant and its dict give the same result), and reports `unconnected_port`, `unknown_name` with suggestions and the other
codes of [errors.md](errors.md) on the paths of the dict, such as `connections[1].target`, and on
`inputs.<path>`: an unknown path, a path that is not an input (`unknown_name`), a wrong unit
(`invalid_unit`).

`plant.set_inputs` is the one public way to set inputs that are part of the design, with a quantity for a value with a dimension (a bare number raises `invalid_value`; `_set_si_inputs` is the private SI path of `gemini`): a setpoint of a
stored heat pump is schedulable as it is read, `from_dict` applies it and `gm.schedule` reads it
through `plant.input_value`. A column of the run wins over it. A value assigned on a module
(`plant.pump.frequency = 50`) and the last tick a run leaves on a module are not stored.
`plant.to_json(path)` and `gm.Plant.from_json(path)` write and read it as JSON. A plant dict of an older
format raises `ValidationError` with code `old_format`.

## What the plant dict holds

The plant dict holds only the plant: the class and size, the design values (`params`), the setpoints
(`inputs`), the bindings and the dated values. It holds nothing that describes the world or the
request, which is in the `gm.Case`: not the ground (gradient, surface temperature), the reservoir
(permeability, thickness, pressure), the brine of a `Doublet`, the air, the return and supply
temperatures of the consumers, the prices, the limits or the demand. A parameter that the case
sets is declared with `Parameter(..., case="<path in the case>")` (`Doublet.gradient`,
`surface_temperature`, `permeability`, `thickness`; `Formation.geothermal_gradient`,
`surface_temperature`; `HeatingGrid` and `CoolingGrid` `return_temperature` and the required supply
temperature): a plant dict that states one is refused with `invalid_value` naming the case path, and
`to_dict` never writes it. A value with a unit in `params` or `inputs` is a `{"value", "unit"}` and
`to_dict` writes it so; a bare number with a dimension is refused, in `params`, `inputs`, `fluids` and `param_history`. Known limits:

- `fluids` remains in the plant dict, for a module whose fluid differs from its class default. A
  plant with no case (a measured or replayed plant such as `DoubletHeatPlant`) carries its own
  brine there; with a case, a `Doublet` takes its fluid from `environment.fluid`.
- The pressure of the water a consumer returns stays a design parameter of the plant: the case
  has no field for it.

## Loops

A connection that closes a cycle is a tear stream. `Plant.forward` iterates the cycle until the tear
stream converges, the same way for every plant:

- The tear is the connection out of a module that gives a first guess (`Module._loop_start`), else
  the last in the connection list. In a substation it is `consumer.return_out`, and on the drive
  water of a chiller the outlet of the `Mixer`, whose guess is the water that joins from outside.
  The first guess has no flow, the highest pressure that enters the loop and the fluid that enters
  the module of the tear.
- A tear stream without flow carries nothing: only its flow has to converge.
- Each pass runs the modules of the loop without recording them, and moves each field of the tear
  stream by Wegstein's method (`plants/_utils/loops.py`); then every module is called once with the
  converged stream, so outputs and balances see one call each. A loop through a stateful module is
  refused.
- `Module._loop_limits` keeps the iterate on the side where a module is valid: a heat exchanger
  must not reverse.
- A loop needs a module that sets its flow and its pressure, such as a `CirculationPump`.
- `plant.loop_tolerance` (1e-9, SI) and `plant.loop_passes` (50) are the settings. A loop that does
  not converge raises `PhysicsError` with code `loop_not_converged` and the tear path.

A compiled plant traces its loops as a `fixed_point` node that iterates on arrays, masked per row,
with the numbers of a plain call. A plant with a constraint is a root break: it runs for real, row by
row, the same on every backend ([engine](engine.md#the-runner)).

A connection with `"type": "state"` reads the value of the previous step. State connections are
valid in the plant dict, the schema and validation; **running such a plant raises
`NotImplementedYet`** until scan exists, because a first step has no previous value.

A plant child in a cycle with other modules, with no cycle among the leaves, is opened: its children
are called directly by the parent, as `DoubletHeatPlant` does with its `doublet`, its constraints are
solved by the parent, and its own outputs are not computed.

## Constraints

```python
self.constrain(
    "riser.wellhead_out.p",
    equals="wellhead_pressure",
    by="reservoir.production_rate",
    bounds="production_rates",
)
self.constrain(
    "injector.bottom_out.p",
    at_least="sink.bottomhole_pressure",
    by="injection_pump.pressure_setpoint",
    bounds=("injection_pump.fluid_in.p", "maximum_injection_pressure"),
)
```

The engine finds the value of the control or boundary `by` at which `target` reaches its value, with
`ops.brentq`, running the modules between them without recording them; then it calls those modules
once with it. `target` and the value are paths; `bounds` is the path of a pair, or two numbers or
paths. With `at_least` a target that reaches its value at the lower bound keeps that bound: the
injection pump adds no head when the column of brine is enough. `plants/_utils/constraints.py` is the
solve; `gm.analysis.nodal` keeps its own curves in `gemini/analysis/solves.py`.

## Outputs

A plant's outputs are only combinations of paths, computed after its children, traced, the same on
every backend:

```python
self.brine_cooling = Output.difference("riser.wellhead_out.T", "injector.wellhead_in.T")
self.share = Output.ratio("boiler.fuel", "chp.fuel")
self.fuel = Output.sum("boiler.fuel", "chp.fuel")
```

A path is an output of a child, a port field (`.m_dot`, `.T`, `.p`) or a bare name for an earlier
output of the plant. The output takes the kind of its paths: a difference of temperatures is a
temperature difference, a ratio has no unit. A value of `None` or a zero divisor gives `None`.
Anything else is read by path: a child's output (`results["sub.consumer.unmet_demand"]`) or a port
field (`results["sub.heat_exchanger.hot_out.T"]`). A plant never sums what a port shows: a total is
read from the ports of its edge modules.

## Registered plants

`gm.plants.names(category=None)` lists the plant classes, `category` being what they serve;
`gm.plants.get(name)` gives a plant without values.

| Class | Serves | Size |
| --- | --- | --- |
| `Doublet`, `NodalDoublet`, `DoubletHeatPlant`, `HeatingSubstation`, `CoolingSubstation`, `ATESPlant` | building blocks | |
| `MultiWellPlant` | both | `producers`, `injectors` |
| `DistrictNetwork` | both | `consumers`, `service` |
| `HeatingPlant` | heating | `doublets` |
| `HeatingCoolingPlant`, `HeatingFullCoolingPlant`, `HeatingAbsorptionCoolingPlant`, `HeatingHeatPumpCoolingPlant` | both | `doublets` |
| `BoilerChpPlant`, `ParallelExchangerPlant`, `DistrictEnergyPlant` | cases | |

The five template plants derive from `DoubletsPlant` (`plants/_utils/doublets.py`): `size={"doublets":
n}`, 1 to 3 (`minimum_doublets`, `maximum_doublets` of the class, `invalid_design` outside), gives the
doublets `d0` to `d{n-1}` in parallel through `production_mixers` and `injection_splitters`. A
plant-level `depth` goes to every doublet, which derives its reservoir from it; a value stated on one
doublet wins, now and later. A run that starts without a geotherm raises `missing_value` naming the path. A `Doublet` with a `depth` and no geotherm waits for it instead of
raising: a plant holds the design, and the `gm.Case` the geotherm and the rest of the environment,
so `gm.simulate(plant, case)` applies them to a copy ([engine.md](engine.md#how-the-case-reaches-the-modules)).

**Schedulable or a building block.** `gm.schedule(plant, case)` plans a plant that has `Doublet` children and a
grid, and its setpoints as `inputs`:

| A plant with values plus `gm.schedule` | Status |
| --- | --- |
| `HeatingPlant`, `HeatingCoolingPlant`, `HeatingFullCoolingPlant`, `HeatingAbsorptionCoolingPlant`, `HeatingHeatPumpCoolingPlant`, and a plant dict of the same units | schedulable: a design is a plant dict, and `inputs/examples/` holds two that run with no failed step |
| `DoubletHeatPlant` | schedulable up to 165 m3/h: the measured ESP curve, which the replay goldens hold, has no head at 60 Hz for more, so the flow range constraint must stop there |
| `Doublet`, `NodalDoublet`, `HeatingSubstation`, `CoolingSubstation`, `DistrictNetwork`, `MultiWellPlant`, `ATESPlant` | building blocks: a run sets their controls and boundaries |
| `DistrictEnergyPlant`, `BoilerChpPlant`, `ParallelExchangerPlant` | cases: their examples set their inputs |

Example values live in `inputs/plants/<Name>.json`, in a source checkout only:
`{"plant": "<Name>", "size": {...}, "params": {"<dotted path>": <value>, ...}}`, numbers as
quantity dicts where the quantity converts to the same float, plus `fluids`, `boundary`, `bindings`,
`param_history` and `inputs` under the names of the plant dict. `example_plant(name)` of `tests/fixtures/sample_cases.py` builds the plant of
that `size`, then `set_params` with `params` and these sections, and `to_dict()` writes the values in
SI. The five template plants have no values of their own: a design is its plant dict. A plant with no file raises `FileNotFoundError`
and a missing `inputs/` raises `inputs_missing`.

`ATESPlant` has one wiring for both seasons: the `split_fraction` of `source_valve` and `load_valve`
sends the flow to the exchanger or to the heat pump, and the one that stands still is called at zero
flow. `AquiferStorage` offers its produced stream, so its loop needs no iteration.

## Parameters by date and bindings

```python
plant.set_params("doublet.esp", {"stage_count": 14}, valid_from="2025-01-01")
plant.params_at("doublet.esp", time="2024-06-01")
plant.param_history("doublet.esp")
plant.bindable("doublet.esp")
plant.set_bindings("doublet.esp", {
    "frequency": "esp_hz",
    "fluid_in.p": {"column": "p_in", "unit": "bar"},
})
```

`set_bindings(path, bindings)` replaces the bindings of a module. A key is a declaration name: a
control, boundary, measured output or state, which are unique within a module, or `port.field` of
an inlet. A value is a column name, whose unit comes from the run input's metadata or else the
declaration's SI unit, or `{column, unit}`. A name declared twice would raise `ValidationError`
naming the clash; no shipped module has one. The plant dict holds the same flat form and reads only
that form: a section such as `controls` is an unknown name.
