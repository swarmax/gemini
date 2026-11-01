# Writing modules

A leaf module computes and a plant connects; no class does both. A leaf `Module` has physics and one
method, `forward`: it computes once, assigns its outputs and returns its outlets. Every composite is
a `Plant` ([plants.md](plants.md)): it declares children, ports and connections in `__init__` and
never writes `forward`. `forward` receives a read-only `Ports` mapping and returns a dictionary
containing exactly the declared fluid outlets. Controls and boundaries are applied by the base class
and read from `self`.

Write a module with `Module` and the declarations (`Parameter`, `Inlet`, `Outlet`, `Output`,
`Control`, `Boundary`, `State`) from `gemini.modules` (`gm.modules.Module`), and the quantity types
and streams from `gemini.types`. The base class has no string catalogue, sequential
container, fidelity flag or cost method. The shipped equipment, with each model's ports, parameters, equations and energy-audit status, is
listed in [equipment.md](equipment.md); its classes are good references for new modules.

**Physics lives in `gemini/physics/` or a `_physics.py`.** Modules declare and wire; they never
define physics. `gemini/physics/` keeps the textbook formulas and anything more than one category,
or `analysis`, `study` or `evaluate`, reads. Physics of one category lives in
`gemini/modules/<category>/_physics.py`, which imports only `gemini.physics`, `gemini.ops`,
`gemini.types` and `gemini.errors`, never another category's `_physics.py`; when a second category
needs a function it moves up into `gemini/physics/`. Its functions keep `@ops.physics` and stay
traceable on every backend. Reuse existing physics functions wherever possible and combine them; add
a new physics function only when nothing existing can do the job, and generalise an existing one
rather than writing a second copy. Never write a formula inside a module, and never write the same
formula twice.
Fitting and calibration belong in `gm.analysis` or `gm.study`, not in modules. A plant class
belongs in `gemini/plants/`; `gemini.modules` never imports `gemini.plants`.

**Where a file goes under `gemini/modules/`.** There are four homes:

- A file that defines a core class users subclass or build goes directly in `gemini/modules/`:
  `module.py` (`Module`), `declarations.py` (`Parameter`, `Inlet`, `Outlet`, `Output`, `Control`,
  `Boundary`, `State`), `container.py` (`ModuleList`, `ModuleDict`) and `check.py`
  (`gm.modules.check`). `Plant` is `gemini/plants/plant.py`.
- Machinery goes in an `_utils/` folder, even if some of its functions are exported publicly:
  `gemini/modules/_utils/` (`balance`, `description`, `design`, `serialization`, `wiring`),
  `gemini/plants/_utils/` for the plant tools and `gemini/_utils/registry.py` for the registry.
- Code shared by the modules of one category goes in that category folder as a private file:
  `heating/_burner.py`, `cooling/_sorption.py`.
- `gemini/plants/` holds only plant classes.

## Construction and metadata

Construct a module without arguments and set its values afterwards; `set_params` returns the
module, so `ESP().set_params("", {"stage_count": 12, ...})` builds a configured pump. Only structural
tree-shape arguments (for example `ModuleList(modules)`, `DistrictNetwork(consumers=3)`) go to
`__init__`. There is no
class-creation hook: `module.name` is the snake_case class name computed on access,
`Module.help()` reads the first paragraph of the class docstring and lists the declarations, and
any number of classes may share a name. `module.path` is the dotted position in the tree, or the
name for a standalone module. `module.fluid` is a validated property saved by `state_dict()`. Checkpoints
store the root class as `module:qualname` through `class_path`/`import_class` in `module.py`, the
only import-by-string in the package.

## Registry, categories and streams

`gemini/_utils/registry.py` is the one registry of module and plant classes. A class that states a
`category` joins it under its class name when it is defined (`Module.__init_subclass__`), so every
shipped equipment class is registered when `gm.modules` is imported and a new class needs no call.
`abstract = True` in the body of a class leaves it out (`Module` and `Plant` are abstract); a
subclass does not inherit it. A second class of a registered name raises `ValidationError` (code
`duplicate_name`); defining the same class again replaces it. `gm.modules.names(category=None)`,
`get(name)` and `categories()` read the registry; an unknown name raises `ValidationError` with its
close matches in `suggestions`. A class in a file of the user is a class like any other: import the
file, and a plant dict can then name it by `type`. There is no `register` and no `load_file`.

Once a new class is written, run `gm.modules.check(cls, example=None)`. It never raises
and returns `{module, passed, checks}`, each check `{name, passed, message}` with `passed` `True`,
`False` or `None` (undecided). The checks are `is_module`, `instantiate` (the declaration rules
run in `__init__`), `category`, `forward_signature` (exactly `forward(self, inlets)`), `units`
(every scalar numeric parameter, control, boundary and output is declared with a quantity type
that has a unit; coefficient arrays are exempt), `describe` (plain JSON) and `call` (one
`gm.call` call). A module that needs parameters, controls or inlet streams is undecided on
`call` until `example` gives them in the shape of `gm.call`:
`{"parameters": {...}, "inlets": {...}, "controls": {...}}`.

There is one classification: a shipped module's category is the name of the folder of
`gemini/modules/` that holds its file, and a new module goes in the folder of what it does.
`CATEGORIES` of `gemini/_utils/registry.py` is the fixed list of those folders, one word each, in display order;
[equipment.md](equipment.md#overview) lists the modules of each. `Module.category` reads the folder
from the import path of the class, so a shipped class never declares it and the two cannot disagree
(`tests/unit/_utils/test_registry.py` checks the folders, the list and every class). The classes of
`gemini/plants/` read `plants`. A class from outside has no folder: it states the class attribute
`category`, one of the list, and a subclass of a shipped class states its own.

A port declares its label: `Inlet(Stream, kind="brine")`, one of `gm.types.streams.names()`.
A port without one, `kind=None`, takes whatever flows through it: piping, `CentrifugalPump`,
`HeatExchanger` and the source side of `HeatPump`. Labels never change a calculation; they say what may be connected.

## Ports

A port carries a `Stream` or a `Power`, and connections check that their `kind`s match:
`Inlet(Power, kind="electricity")`, `Outlet(Power, kind="heat")`. `many=True` lets several ports
connect to one port; its value is the list of what arrives, and the module sums it with an explicit
function (`energy.total_power`). A `many` port may stay empty.

A plant runs its modules in the order the values travel, and on some connections the value travels
against the energy, because the module that receives the energy decides how much it takes:

- **A drawn port.** A single `Power` inlet is drawn: a call needs no value for it, `forward` computes
  it and returns it under the name of the port, beside the outlets, and `result.inlets.power_in`
  shows it. A stream inlet is drawn with `Inlet(Stream, drawn=True)`: it receives the conditions the
  source offers and `forward` returns the stream it took. A `many` outlet is drawn, as is any
  `Outlet(..., drawn=True)`: the module receives what its takers drew under the name of the outlet
  (`inlets.power_out` in `forward`). The taker runs before
  the source.
- **An offered outlet.** `Outlet(Stream, offered=True)` exists before the other modules run. Its
  module defines `_offer(self, inlets)`, reading parameters, controls, boundaries and the inlets it
  names in `offer_inlets`, and the plan gives the module one offer step and one call. This is how an
  edge module both feeds modules and receives from them without a cycle, and how a connection back
  to such a module is no loop. A direct call that leaves a drawn outlet out gets its offer, and one
  that leaves out a `many` port an empty list.

A sub-plant exposes one port for what several children share: `plant.connect("power_in",
"esp.power_in")` twice, or `"inlets": {"power_in": ["esp.power_in", "pump.power_in"]}` in the plant dict.
Its value is the sum of what the ends carry (`energy.total_power`), so from outside a sub-plant reads
like a leaf. Several ends may share a plant port that carries a power or air, never a plain stream.

## Describing a module

`describe()`, `parameter_schema()` and `validate_params(params)` are instance methods: a module's
declarations exist only once `__init__` has run, so a class answers through a new instance,
`gm.modules.ESP().describe()`. They live in `gemini/modules/_utils/description.py`, return plain
JSON (`json.dumps(..., allow_nan=False)`) and never change the module.

`describe()` returns `{name, type, category, summary, doc, parameters, controls, boundaries,
measured, state, inlets, outlets, outputs, children, connections, values}`:

- `name` is `module.path`, `type` the class name (a plant shows its given name), `summary` the
  first paragraph of the docstring and `doc` all of it.
- `parameters`, `controls`, `boundaries`, `measured` and `state` map a name to `{type, unit,
  quantity, default, minimum, maximum, enum, description, section}`. A missing item is `null`;
  `default` is `null` for `UNSET`. `minimum` and `maximum` are the closest limit, so a strict bound
  (`gt`, `lt`) shows as the bound itself. `enum` comes from a `Literal`. Only the module's own
  declarations are listed; children appear under `children`.
- `measured` lists every output of the module itself: replay (`engine/step.py`) takes a measured
  binding for any output name and compares it with that output; no narrower rule exists.
- `inlets` and `outlets` map a port to `{kind, fields: {m_dot: {unit: "kg/s"}, T: {unit: "K"},
  p: {unit: "Pa"}}}`; `kind` is `null` for a port that takes any stream.
- `outputs` maps a name to `{unit, quantity, soft_sensor}`; `quantity` is the quantity name
  (one of the nine) or `null`.
- `children` is `{name: type}` and `connections` is `[{source, target, kind, type}]`, both empty
  for a leaf. A plant exposes its wiring through `_connection_list()`.
- `values` holds the current `parameters`, `controls` and `boundaries`; unset ones are left out
  and a child's values are keyed by dotted path.

`parameter_schema()` is JSON Schema draft 2020-12: `$schema`, `title`, `type: object`,
`properties`, `required` (parameters with no default) and `additionalProperties: false`. A child's
parameters appear under their dotted path. Each property has the standard keywords (`type` or
`anyOf`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `enum`, `default`,
`description`) plus `unit` and `quantity`. A number with a unit is `anyOf` number and string,
because inputs accept `{"value": 150, "unit": "m3/h"}`.

`validate_params(params, on_error="raise")` checks every entry and raises one `ValidationError` that
carries every problem; with `on_error="record"` it returns them, each
`{path, code, message, suggestions}`. `path` is the parameter name; the codes are `unknown_name` (with `suggestions`),
`invalid_unit`, `out_of_bounds` and `invalid_value`. It runs `declaration.validate` once per entry
and tells the failures apart by the exception and its cause.

## Listing declarations

Every declaration listing takes `recurse` with default `True` and keys its result by dotted path
relative to the module (`"doublet.esp.frequency"` from the root): `parameters()` and
`named_parameters()` iterate, and `controls()`,
`boundaries()`, `inputs()`, `outputs()` and `soft_sensors()` return dicts. Pass `recurse=False`
for the module's own declarations under their local names. `inlets()` and `outlets()` take no
`recurse`: a child's ports are internal connections, not ports of the parent.
`children()`/`named_children()` list direct children and `modules()`/`named_modules()` walk the
tree. `get(path)` returns the declaration at a dotted path, whatever its kind, and
`get_submodule(path)` the module; both suggest a close match for a typo.

## Leaf modules

A leaf computes once, in `forward(self, inlets)`: it calls physics, assigns its outputs under
`# Outputs` and returns its outlets. `self.flow = ...` records the output of the running call, and
reading `self.flow` afterwards gives it back.

```python
from gemini.modules import Control, Inlet, Module, Outlet, Output, Parameter
from gemini.physics import pumps
from gemini.types import (
    Count, Electricity, Frequency, Power, PressureDifference, Stream, VolumeFlow,
)


class Pump(Module):
    """Example fluid pump."""

    def __init__(self):
        super().__init__()

        # Parameters
        self.stage_count = Parameter(Count)
        self.head_coefficients = Parameter(list[float], shape=(6,))
        self.power_coefficients = Parameter(list[float], shape=(6,))

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.frequency = Control(Frequency)

        # Outputs
        self.flow = Output(VolumeFlow)
        self.head = Output(PressureDifference)
        self.power = Output(Power)
        self.electricity = Output(Electricity)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Raise the suction pressure."""

        # Outlets
        suction = inlets.fluid_in
        flow = suction.volumetric_flow()
        head = pumps.head(flow, self.frequency, self.stage_count, self.head_coefficients)
        discharge = suction.with_(p=suction.p + head)

        # Outputs
        self.flow = flow
        self.head = head
        self.power = pumps.power(flow, self.frequency, self.stage_count, self.power_coefficients)
        self.electricity = self.power

        outlets = dict(fluid_out=discharge)
        return outlets
```

Every declared output, including one whose value is `None`, must be assigned on every call.
Under `gm.modules.no_outputs()` the assignments still run; nothing validates them and the result drops them.
Do not cache call data on `self`: it belongs in a local variable of `forward`.

## Plants

A composite is a `Plant`: its shape, connections, loops, constraints and outputs are in
[plants.md](plants.md). `module.is_leaf` is true exactly when the module has no registered
children. Composites built from a variable number of children use the containers
`ModuleList(modules)` (children named `"0"`, `"1"`, ...; inserting or removing renumbers the later
children) and `ModuleDict(mapping)` (caller-chosen keys that must not shadow module or mapping
attributes). Containers compare and hash by identity like every module.

### A plant that sets its children's values

A plant may derive its children's parameters from its own. It overrides `set_params`, computes the
child values with functions from `gemini/physics/` and calls `super().set_params` with them:

```python
from gemini.modules import Parameter, ProductionReservoir
from gemini.physics import hydraulics
from gemini.plants import Plant
from gemini.types import Density, Length


class Column(Plant):
    """A reservoir whose pressure comes from the height of its water column."""

    def __init__(self):
        super().__init__()

        # Modules
        self.reservoir = ProductionReservoir()

        # Parameters
        self.height = Parameter(Length | None, default=None)
        self.density = Parameter(Density | None, default=None)

    def set_params(self, path, params, valid_from=None):
        """Derive the reservoir pressure, unless the same call states it."""
        if path:
            return super().set_params(path, params, valid_from)
        values = self._own_values(params, valid_from)
        derived = {}
        if values["height"] is not None and values["density"] is not None:
            pressure = hydraulics.hydrostatic_dp(values["density"], values["height"])
            derived["reservoir.pressure"] = pressure
        return super().set_params("", self._keep_derived(derived, params) | params, valid_from)
```

`_own_values(params, valid_from)` gives the module's own values in force at that date with the ones
of this call, in SI, so a dated call derives from the design of its date. A value that has not been
given yet derives nothing: the values may arrive one call at a time. `_keep_derived(derived, params)`
does the bookkeeping: an explicit child value in the call wins, now and in later calls
(`{"depth": {"value": 3000, "unit": "m"}, "well.pipe_path": [...]}` keeps the given pipe path), and it records the names
it keeps.

Every route that sets parameters reaches this method: `add(..., params=)`, `from_dict`,
`set_params(path, ...)` at any depth, a dated `set_params(..., valid_from=)`, a `param_history`
section and attribute assignment. Setting the fluid of a plant passes it to every child and derives
again.

All of this is done once, in `Plant`: the formulas go into physics (`gemini/physics/doublet.py`) and
the plant keeps a short `set_params`. `to_dict` stores the plant's own parameters and the explicit
child values, never a derived value: `from_dict(p.to_dict())` derives them again and rebuilds the
same numbers. Dated entries of a child that only hold derived values are left out in the same way.

## Values

Parameters, controls and boundaries are set by attribute assignment or in bulk:

- `set_params(path, params, valid_from=None)` validates parameters by local or dotted name and
  stores them, in the undated base entry or from a date on, and returns the module; `params_at(path,
  time)` returns the values active at an instant.
- `module.frequency = 50` persists one control or boundary, and `module.stage_count = 12` sets a
  parameter as an override that wins over every date.
- `missing_parameters()` lists uninitialized parameters and `is_initialized` is true when there
  are none.
- `state_dict()` returns JSON-safe parameter values and the fluid of every module path, and
  `set_state_dict(state, strict=True)` validates all of them before applying any. With
  `strict=False` only the modules named in `state` are filled; unknown paths are always rejected.
  `to_dict()`/`from_dict()` and `save(path)`/`load(path)` of a `Plant` add dated histories,
  overrides, bindings and boundary defaults; a single module is stored by wrapping it in a plant.

```python
curve = [1, 0, 0, 0, 0, 0]
pump = Pump().set_params(
    "", {"stage_count": 10, "head_coefficients": curve, "power_coefficients": curve}
)
pump.frequency = {"value": 50, "unit": "Hz"}
```

## Calling modules and `Ports`

Keyword, mapping and positional inlet calls are equivalent. Positional streams follow inlet
declaration order; controls and boundaries remain optional call keywords that apply to this call
only. Do not combine an inlet mapping with inlet keywords.

```python
import gemini as gm

stream = gm.Stream(flow={"value": 150, "unit": "m3/h"}, T={"value": 80, "unit": "C"}, p={"value": 20, "unit": "bar"})
a = pump(fluid_in=stream, frequency={"value": 50, "unit": "Hz"})
b = pump({"fluid_in": stream}, frequency={"value": 50, "unit": "Hz"})
c = pump(stream, frequency={"value": 50, "unit": "Hz"})
assert a.outputs.head == b.outputs.head == c.outputs.head
assert a.outputs.get("head", unit="bar") == a.outputs.head / 1e5
```

`inlets` and `result.outlets` are immutable `Ports`. They preserve
declaration order and support both `ports.fluid_in` and `ports["suction"]`. Unknown names report
the module path, valid names and a close-match suggestion. A call returns a `ModuleResult` with
`outputs` (a `Values` mapping whose `get(name, unit=...)` converts from the declared unit),
`outlets`, `inlets`, the resolved `inputs` and the `children` results of the call.

## Call order and hooks

One call performs these steps:

1. validate inlets and resolve controls and boundaries (call keyword, persisted value, default);
2. run forward pre-hooks;
3. run `forward`, which assigns the outputs, and validate its fluid outlet dictionary;
4. evaluate the combinations of a plant in declaration order;
5. run forward hooks;
6. verify every output was assigned and build `ModuleResult`.

Pre-hooks always receive `(module, inlets)` and forward hooks always receive
`(module, inlets, outlets)`:

```python
def clamp(module, inlets):
    module.frequency = min(module.frequency, 45)


def observe(module, inlets, outlets):
    print(module.head, inlets.fluid_in.p, outlets.fluid_out.p)


pre_handle = pump.register_forward_pre_hook(clamp)
handle = pump.register_forward_hook(observe)
clamped = pump(fluid_in=stream, frequency=50)
assert clamped.inputs["frequency"] == 45
pre_handle.remove()
handle.remove()
```

Hook return values are ignored. Any non-fixed hook signature fails at registration with a
`ValidationError`. Remove a hook with `handle.remove()`; removing twice does nothing. Assigning a
control inside a hook changes only the running call.

A pre-hook makes its module a graph break, and so does a forward hook that only reads: the tracer
calls such a hook once on traced values to classify it, then the module runs for real, row by row,
hooks included. A forward hook that writes an output is part of the graph. `EventLog` registers no
hook: it reads the results of each tick.

## Per-call values

The values of one call (resolved controls and boundaries, recorded outputs and the results of
child calls) live in one `_Call` record held in a context variable while the call runs. Attribute
access on a module returns parameter values, the control/boundary value of its running call
(even from a descendant's hook), the persisted value or the default, outputs recorded in its
running call, and port declarations otherwise. Child calls made from pre-hooks are recorded on
the module whose call is running. A module keeps no result after the call returns: use the
returned `ModuleResult`.

## Traced calls

While `gemini.compiler.graph` traces a module, its `_Call` carries the running `Trace` (`call.trace`) and a
child call made inside it is recorded in the graph by `Trace.child` instead of evaluated: the child's controls, boundaries
and numeric parameters become graph inputs named `<path below the root>.<name>`, supplied keyword
values win without validation, and the `ModuleResult` of traced values joins the parent's call
records, so the combinations of a plant and `ModuleResult.leaves()` work
unchanged. `Output.ratio` is `where(bottom == 0, None, top / bottom)` with the division written as
`ops.truediv`, which gives `None` on plain floats. A leaf child that is stateful,
has a pre-hook, has a read-only hook or raises `TraceError` becomes one **break node**:
the graph is rolled back to where the child call started and the child runs on the plain path
(`module(**row)`, a stateful one from its initial states, hooks included) once per row while the
graph is evaluated, its outputs and outlet fields being `break_output` nodes. The outlet fluids
come from one probe of `forward` on representative inlets; a row with another fluid fails. A
failed row is NaN and carries an error code that raises the child's own exception. A composite
child that cannot be recorded makes the whole root a graph
break (`graph.breaks` lists the leaf breaks with their reasons).

An output of a list or tuple of traced values (the per-section profiles of the wells) is a vector
output of fixed length: `Graph.output` records each item as `<name>[<index>]`, `graph.vectors`
keeps the length, and `gemini.compiler.graph.run` returns one array of shape `(rows, length)`.

A traced call is not validated, so the tracer adds the validation as graph checks. For every
traced call (children included, break nodes excepted) each control, boundary and output with
bounds (`Declaration.limits()`: `ge`/`gt`/`le`/`lt` read once from the quantity metadata and the
declared bounds, applied to each item of a list; an `X | None` kind lets NaN pass) gets an
`ops.check` raising `ValidationError`, and the root inlets carry the `Stream` limits (finite
`m_dot`, `T > 0`, `p >= 0`). These checks are attached to every graph output, so a row that
violates a bound fails even where the arithmetic never reads the bad value.

## Skipping outputs

`gm.modules.no_outputs()` is a nestable, context-local context manager and decorator. It skips validating
what `forward` assigns, the combinations of a plant, forward hooks and output completeness checks.
`forward`, pre-hooks and outlet validation still run; the result has an empty `outputs` mapping.

```python
with gm.modules.no_outputs():
    fast = pump(fluid_in=stream, frequency={"value": 50, "unit": "Hz"})

assert dict(fast.outputs) == {}
assert fast.outlets.fluid_out == a.outlets.fluid_out
```

## State and health

Stateful equipment declares its carried values as `State(kind, default=...)` in the `# States`
section; `default` is the initial state. `forward` reads a state as a plain attribute
(`self.temperature`), which gives its value at the start of the step. A stateful leaf implements
`_advance_states(self, inlets, outlets, dt)`, returning the end-of-step value of every state, after
`forward`; a state is never assigned directly. `module.stateful` is true
when a module declares states, and `states(recurse=True)` lists them by dotted path.

`step(state, dt, inlets)` returns `(next_state, result)` for any module; `step` and `initial_state`
stay public, because a module that sets `stateful = True` without declaring states overrides them. `initial_state()` and
`state` are the module's own `{name: value}` mapping for a leaf and nest by child name for a
composite, for example `{"storage": {"temperature": 330.0}}`; `None` means the initial states.
A composite needs no `step` method: its `forward` runs once, every stateful descendant it calls
starts from its entry and records its end-of-step entry, and a descendant that is not called
keeps its state. A stateful module called twice in one step raises `ValidationError`. Outside
`step`, a call evaluates at the initial states. The engine integrates these steps; see
[engine.md](engine.md). A module that sets `stateful = True` without declaring states must
override `step` itself, and a composite refuses to step such a descendant. The shipped stateful
leaves (`ThermalDecline`, `AquiferStorage`, `BoreholeField`, `ThermalStorage`, `IceStorage`,
`PIDController`) and how each integrates over `dt` are described in
[equipment.md](equipment.md).

```python
from gemini.physics import heat_transfer
from gemini.modules import State
from gemini.types import Power, Temperature


class Tank(Module):
    """Mixed tank whose temperature follows the inlet."""

    def __init__(self):
        super().__init__()

        # Parameters
        self.heat_capacity = Parameter(float, gt=0)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # States
        self.temperature = State(Temperature, default=300)

        # Outputs
        self.duty = Output(Power)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Leave at the tank temperature of the start of the step."""

        # Outlets
        outlet = inlets.fluid_in.with_(T=self.temperature)

        # Outputs
        self.duty = self._duty(inlets.fluid_in)

        outlets = dict(fluid_out=outlet)
        return outlets

    def _advance_states(self, inlets, outlets, dt):
        heat = heat_transfer.heat_rate(self._duty(inlets.fluid_in), dt)
        rise = heat_transfer.temperature_change(heat, self.heat_capacity)
        return {"temperature": self.temperature + rise}

    def _duty(self, inlet):
        return heat_transfer.heat_rate(inlet.heat_capacity_rate(), inlet.T - self.temperature)


tank = Tank().set_params("", {"heat_capacity": 4.2e5})
state, result = tank.step(None, 60, {"fluid_in": stream})
assert result.outlets.fluid_out.T == 300 and state["temperature"] > 300
```

A module with a diagnostic model overrides `health(self, result, measured)`. It receives the
call's `ModuleResult` and the measured outputs of that tick and returns a `Health` (`assessed`,
`score`, `alarm`, `message`, `metrics`); the base method returns `None`, which the engine records
as `assessed=False`. A module that declares its own cost defines `capex(assumptions)` returning a `Cost`;
see [types.md](types.md#profiles-and-costs).

## Energy flow

Everything in the plant's energy and mass flow is a module; everything that crosses between modules
goes through a port.

```text
 ElectricityGrid --power_out--> power_in  ......................
 GasGrid --gas_out--> GasMakeup --fuel_out--> Boiler ---flue_out--> Atmosphere.gas_in
 ChemicalGrid --chemical_out--> InhibitorDosing    |
 Atmosphere --air_out--> air_in (Pipe, Cooler)     +---loss_out--> Atmosphere.heat_in
                                                           wells --> Formation.heat_in
 reservoir --> wells --> treatment --> exchangers --> wells --> reservoir
                             |
                             +---waste_out--> WasteGrid
 HeatingGrid.return_out --> heat pump, boiler --> HeatingGrid.supply_in
 CoolingGrid.return_out --> chiller           --> CoolingGrid.supply_in
```

- **Edge rule.** The grids (`ElectricityGrid`, `GasGrid`, `HeatingGrid`, `CoolingGrid`, `WasteGrid`,
  `ChemicalGrid`) and the environment (`Atmosphere`, `Formation`) are the plant's edge. A plant
  total is read from their ports (`gm.evaluate.totals`), never summed by a parent;
  `gm.evaluate.plant_balance` closes the root on them. The aquifers are the one other open boundary.
- **Supply rule.** A root plant has no plant port (`root_plant_port`): what it buys comes from a
  grid, and an unconnected inlet is `unconnected_port`. A registered plant is a building block and
  has plant ports. Nothing supplies itself: there is no default fuel, power or air.
- **Port rule.** A port's name is `<role>_in` or `<role>_out`; its `kind` labels what it carries. A
  value that travels back to its source goes by who decides it: a single `Power` inlet is drawn, a
  `drawn=True` inlet shows what the module took of what was offered, and an `offered=True` outlet
  exists before the modules around it run. A `many` port takes the list of what is connected.
- **Output rule.** An output holds only what is on no port ([types.md](types.md#port-quantities)).

## Structure

Constructor sections of a leaf are ordered `Modules`, `Parameters`, `Inlets`, `Controls`,
`Boundaries`, `States`, `Outputs`, `Outlets`, with empty sections omitted; those of a plant are in
[plants.md](plants.md#a-plant-class). `forward` uses `# Outlets` when outlets exist and `# Outputs`
when it assigns outputs, in that order. It assigns only declared outputs on `self` and ends with
`outlets = dict(...)` followed by `return outlets`. Method order is `__init__`, `forward`,
`_advance_states` when the module has states, then private helpers. The signature is always
`forward(self, inlets)`, including modules with no ports; parameters have no defaults or variadic
forms.

Inlets and outlets accept a `Stream` or a `Power`. What crosses a port is shown by the port, see
[types.md](types.md#port-quantities). Results keep the same dotted
`<module path>.<name>` addressing scheme. Port, control and output names follow the naming rule
in [conventions.md](conventions.md#naming).
