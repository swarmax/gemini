# Public API

Use `import gemini as gm`. This page lists **every public name** at `gm.__version__ = "0.2.0"`, and
is the page the other repositories build against. Names not listed here (a helper method such as
`Results.commit`, anything in `gemini._utils`, any import of an internal path such as
`gemini.run.results`) are internal and may change. `tests/unit/test_public_api.py` pins the
names, their parameter names and the schema files, and `tests/integration/test_return_shapes.py`
walks the returns of this page against their schemas. Every name here is real: a feature is added to
this page when it is built (the planned ones removed are in [refactor-notes.md](refactor-notes.md#planned-features-removed-from-the-api)).

Conventions on every entry:

- Results are deterministic: the same input gives the same numbers on every backend.
- A value with a unit is a `gm.units.Quantity` or its dict `{"value": 150, "unit": "m3/h"}`; text such as `"150 m3/h"` is never accepted. Outputs are in SI by default.
- A plant and an engine are not shared across threads: each worker loads its own.
- Readers are `from_<format>` and writers `to_<format>`: `from_csv`, `from_json`, `from_dict`,
  `from_values`, `from_bytes`, `from_npz`, `to_json`, `to_dict`, `to_bytes`, `to_npz`. No `read_*`,
  `write_*`, `load_*`, `save_*`, `parse_*` or `dump_*` name is public.
- The documents exchanged between repositories have a JSON Schema and a sample in `docs/schemas/`:
  `value`, `problem`, `check`, `module_description`, `plant_dict`, `results_summary`, `profile`
  (`<name>.schema.json`, `<name>.sample.json`). Regenerate with `python scripts/write_schemas.py`.
  The schema `problem` is the shape of one error or failed row; it is not an input, and the input of
  a run is a `gm.Case` (`gm.Case.schema()`). The shape keeps the name `problem`.

## Return shapes

Every public return that carries data uses only three shapes, defined once in `gemini/types/shapes.py`
and built by one helper each, so no module assembles them by hand. The JSON form of a return is
plain: no NumPy types, NaN and infinity are `null` (`gemini._utils.jsonable.to_plain`), and
`json.dumps(to_plain(result), allow_nan=False)` works. `gm.call`, `Results` and `gm.analysis` return
that plain JSON. A result of `gm.evaluate` and `gm.study` is a `gm.units.Quantity` in SI (a
`Value`, below), and `to_plain` turns it into the dict `{value, unit}`.

1. **Value** `{value, unit}`. `value` is a number, an array or `null`; when it is `null`, a `reason`
   key says why. The key is `value` for arrays too. A time series is a value with a `time` key
   beside it: `{time, value, unit}`. Statistics are `{min, max, mean}`, each a value. An output that
   is a flag or a text keeps its boolean or string. An economics value adds the parts of its result
   as more keys, each a value or a text. In Python a result of `gm.evaluate` or `gm.study` is a
   `Value`, a `Quantity` with a `reason` and the `parts` of the result: `lcts(...).value`,
   `.unit`, `.to("EUR/MWh")`, `.parts["heat"]`. Money is in the unit `currency` (`currency/J`,
   `currency/yr`), whatever `assumptions.finance.currency` of the case labels, and a year is `yr`.
2. **Problem** `{path, code, message, suggestions}`, for every error, validation result and failed
   run row. A run row adds `time`. There is no `class` key: `code` is the stable key for machines.
3. **Check** `{name, passed, value, limit}`, where `value` and `limit` are values. A failed check is
   an answer, not an error. `passed` is `null`, with the reason in `value`, when there is nothing to
   judge.

A number always travels with its unit in the same dict: there is no separate `units` map. Counts of
skips by reason (`skip_counts`, `reasons`) and the state trees of `end_state` are the input of a next
call or plain tallies, not values. Public returns are plain dicts: a DataFrame comes only from a
method named `to_frame`, the one exception being run input (`gm.data.from_csv`, `from_values` and
`gm.schedule`), because the run-input format is a DataFrame. Text comes only from `help()` and
`summary()` of a plant, meant for people.

## Output units

Outputs stay SI by default. Every call marked *units* below takes an optional `units` argument, a map
from quantity to unit: `results.get("hx", "duty", units={"power": "MW"})`. Conversion uses `gm.units`
only, on the way out; nothing inside the run changes, and the returned `unit` keys say the unit
actually used (`frame.attrs["units"]` on a table). A key reaches the quantities of its family, the
first quantity defined with the same SI unit leading it: `power` reaches `duty`, `electricity` and
`heat_loss`, `pressure` a pressure difference, `temperature` a temperature difference. A key of the
quantity itself wins. A difference converts by scale only. An unknown quantity, or a unit that does
not fit it, raises `ValidationError` with suggestions.

## Freeze rule

`gm.__version__` is the one version of the package, read from `version` in `pyproject.toml`.
Semantic versioning, below 1.0: a breaking change to a public name or return field raises the
minor number (`0.2.0`); an addition or a fix raises the patch number (`0.1.1`). Every change has a
line in the change log below, in the same commit. The public-API test compares against a stored
snapshot (`tests/fixtures/public_api.json`) that records the version and may only change together
with it; its hash per version is held in the test.

**Module catalogue.** Adding, removing, moving or renaming modules is never a version matter. The
snapshot covers the package API (functions, types, return shapes), not the list of modules.

## Package

`gemini/__init__.py` exports exactly the names below, as `gm.__all__`; `gm.__version__` is an
attribute and not in `__all__`. Every folder exports its public names flat, `gm.<folder>.<Name>`,
from its own `__init__`; the files inside a folder are private.

| Name | Returns | Status |
| --- | --- | --- |
| `gm.__version__` | text, the version in `pyproject.toml` | real |
| `gm.Module`, `gm.Parameter`, `gm.Inlet`, `gm.Outlet`, `gm.Output` | see [modules.md](modules.md) | real |
| `gm.Plant` | see [plants.md](plants.md) | real |
| `gm.Stream`, `gm.Fluid`, `gm.BRINE`, `gm.WATER` | see [types.md](types.md) | real |
| `gm.Case` | see [Case](#case) | real |
| `gm.schedule`, `gm.simulate`, `gm.replay`, `gm.live`, `gm.resume`, `gm.call` | see [Running](#running) | real |
| `gm.Results`, `gm.Dataset`, `gm.Engine` | see [engine.md](engine.md) | real |
| `gm.modules`, `gm.plants`, `gm.case`, `gm.physics`, `gm.ops`, `gm.runtime`, `gm.units`, `gm.errors`, `gm.data`, `gm.study`, `gm.evaluate`, `gm.analysis`, `gm.compiler` | the folders, below | real |

Not at the top: `gm.Clock` is `gemini.engine.Clock`; `Control`, `Boundary` and `State` are
`gm.modules.Control`, `Boundary` and `State`; `gm.Quantity` is `gm.units.Quantity`; `Ports`,
`Profile` and the stream names (`streams.names()`) are in `gemini.types`. There is no `core`,
`base`, `registry`, `testing`, `backends`, `checks`, `economics`, `profiles`, `utils` or `graph`
folder at the top.

## Modules and streams

| Name | Returns | Status |
| --- | --- | --- |
| `gm.modules.names(category=None)` | sorted registry names; plant classes have category `plants` | real |
| `gm.modules.get(name)` | the class. Unknown: `ValidationError` with `suggestions` | real |
| `gm.modules.categories()` | `subsurface`, `wells`, `pumps`, `treatment`, `exchangers`, `heating`, `cooling`, `power`, `storage`, `piping`, `grids`, `environment`, `control`, `plants`, in display order; each is the folder that holds the module | real |
| `gm.modules.<Equipment>`, `Module`, `ModuleList`, `ModuleDict`, `collect_flows`, `emissions`, `energy_balance`, `mass_balance`, `trace_wiring` | classes and one-call audits, see [equipment.md](equipment.md) | real |
| `gm.modules.Parameter`, `Control`, `Boundary`, `State`, `Inlet`, `Outlet`, `Output`, `no_outputs()` | the declarations of a module class, see [modules.md](modules.md) | real |
| `gm.modules.check(cls, example=None)` | for developers of a new module class only: a report, never raises | real |
| `gm.modules.Boiler`, `ElectricBoiler`, `CHP`, `Flare`, `GasGrid`, `GasMakeup` | the gas chain: `boiler.fuel_in`, `boiler.gas_out`, see [equipment.md](equipment.md) | real |

A class that states a `category` registers itself when it is defined (`Module.__init_subclass__`);
`abstract = True` in its body leaves it out. A second class of a registered name raises
`ValidationError` (code `duplicate_name`). There is no `register` and no `load_file`.

On an instance of `Module`; a class answers through a new instance, `gm.modules.ESP().describe()`:

| Name | Returns | Status |
| --- | --- | --- |
| `describe()` | see below; schema `module_description` | real |
| `parameter_schema()` | JSON Schema draft 2020-12; each property has `unit`, `quantity`; dotted child names | real |
| `validate_params(params, on_error="raise")` | `[]`, or raises every problem; with `"record"` the list of problems | real |
| `help()` | text, on the class too | real |
| `missing_parameters()` | JSON list, one dict per unset parameter: `{path, type, quantity, unit, units, minimum, maximum, enum, description}`; `[]` when the tree can run | real |
| `get(path)` | the declaration at a dotted path, whatever its kind | real |
| `get_submodule(path)`, `named_modules()`, `modules()`, `children()`, `named_children()` | a module, or the tree | real |
| `state_dict()`, `set_state_dict(state, strict=True)` | the state tree of a stateful module, and its restore | real |
| `step(state, dt, inlets)`, `initial_state()` | advance the states over `dt`; a module author may override them | real |

```text
{name, type, category, summary, doc,
 parameters, controls, boundaries, measured, state:
   {name: {type, unit, quantity, default, minimum, maximum, enum, description, section}},
 inlets, outlets: {port: {kind, fields: {m_dot: {unit}, T: {unit}, p: {unit}}}},
 outputs: {name: {unit, quantity, soft_sensor}},
 children: {name: type},
 connections: [{source, target, kind, type}],
 values: {parameters, controls, boundaries}}
```

`kind` is `null` for a port that takes any stream; an output's `quantity` is the quantity or `null`;
`measured` is every output of the module, which is what a `measured` binding may name. `minimum`
and `maximum` are the closest limit, strict or not. `values` are keyed by dotted path.

## Plants

A leaf computes and a plant connects: see [plants.md](plants.md). Plants are Python classes; the
plant dict is the JSON form agents use, and `gm.plants.schema()` is its schema. The plant classes
are in `gm.plants`, not in `gm.modules`; `gm.modules` never imports `gm.plants`.

| Name | Returns | Status |
| --- | --- | --- |
| `gm.Plant(name)` | an empty plant; subclass it for a plant class | real |
| `gm.Plant.from_dict(data)` | a plant of a class or without one; one `ValidationError` carries every problem in `problems` | real |
| `gm.Plant.from_json(path)`, `p.to_json(path)` | reads or writes the plant dict as JSON | real |
| `gm.Plant.from_legacy(folder)` | a plant, from the folder of an old project; expected files in [legacy.md](legacy.md) | real |
| `p.add(type, name=None, params=None)` | the added module; `type` is a registry name or a class, `params` the dict `set_params` takes | real |
| `p.connect(source, target, type=None)` | nothing; `ValidationError` with candidates, see [plants.md](plants.md) | real |
| `p.constrain(target, by, bounds, equals=None, at_least=None)` | nothing; the engine solves `by` so that `target` reaches its value, see [plants.md](plants.md#constraints) | real |
| `p.loop_tolerance`, `p.loop_passes` | the settings of a loop, 1e-9 and 50, see [plants.md](plants.md#loops) | real |
| `p.summary()` | text table | real |
| `p.validate(on_error="raise")` | as `gm.plants.validate` | real |
| `p.set_inputs(values)` | the plant; sets inputs by path, the one public way: `{"heat_pump.temperature_setpoint": {"value": 100, "unit": "degC"}, "heating_return.T": {"value": 60, "unit": "degC"}}`, stored by `to_dict` under `inputs`, see [plants.md](plants.md#the-plant-dict) | real |
| `p.input_value(path)` | the input in SI, or `None` when it has no value | real |
| `p.target_of(source)`, `p.source_of(target)` | the `"path.port"` an outlet feeds, or that feeds an inlet; `None` for a plant port | real |
| `p.feeds(source)` | the paths of the modules an outlet reaches through its circuit, nearest first; it ends at a grid or a plant port | real |
| `p.to_dict(structure=False)` | the plant dict; `structure=True` gives the modules and connections of a plant of a class | real |
| `Output.difference(a, b)`, `Output.ratio(a, b)`, `Output.sum(a, b, ...)` | the outputs of a plant, combinations of paths, see [plants.md](plants.md#outputs) | real |
| `gm.plants.validate(data, on_error="raise")` | `[]`, or raises every problem; with `"record"` the list of problems, paths such as `connections[1].target` | real |
| `gm.plants.schema()` | JSON Schema of the plant dict, generated from the code | real |
| `gm.plants.names(category=None)` | plant names; `category` is `heating`, `cooling` or `both`, what a plant serves | real |
| `gm.plants.get(name)` | a new plant without values | real |
| `gm.plants.capabilities()` | `{plant class: {roles, schedulable, choices}}`, built from the code | real |
| `gm.plants.<Plant class>` | the plant classes, see [plants.md](plants.md#registered-plants). The five template plants take `doublets=n`, `size={"doublets": n}` in a plant dict, and a plant-level `depth` | real |

A `Doublet` with a `depth` and no geotherm waits for it, and a run that starts without it raises code
`missing_value` with the path: a plant holds the design, and the geotherm comes from the case
(`environment.ground`).

On any plant, `path` being a dotted module path (`""` is the root):

| Name | Returns | Status |
| --- | --- | --- |
| `set_params(path, params, valid_from=None)` | dated entry, validated; a complete snapshot | real |
| `params_at(path, time=None)` | `{name: value}` in force at `time`, latest without one | real |
| `param_history(path)` | `[{valid_from, params}]` | real |
| `bindable(path)` | `{controls: [name], boundaries: [name], inlets: {port: [field]}, measured: [name], state: [name]}` | real |
| `set_bindings(path, bindings)` | replaces them; flat `{name: column}` or `{name: {column, unit}}`, `name` a declaration or `port.field`; units checked | real |

## Units

| Name | Returns | Status |
| --- | --- | --- |
| `gm.units.names(quantity=None)` | unit names, of one quantity if given | real |
| `gm.units.convert(value, from_unit, to_unit, quantity=None)` | number | real |
| `gm.units.fits(unit, quantity)` | bool; an unknown unit is false, an unknown quantity raises | real |
| `gm.units.Unit` | the `str` enum of every unit of the table, generated from it: `Unit.M3_PER_H == "m3/h"` | real |
| `gm.units.Quantity(value, unit)` | the one shape of a value with a dimension; `.si`, `.to(unit, quantity=None)`, `to_dict()`, `Quantity.from_dict(d)`; equality compares SI values | real |

Every public input with a dimension takes a `Quantity` or its dict `{"value": 150, "unit":
"m3/h"}`. A text such as `"150 m3/h"` is `ValidationError` `invalid_value` everywhere, and a unit
of another dimension is `invalid_unit` that lists the units of the field. A dimensionless value (an
efficiency, a fraction, a rate, a count) stays a number. Nothing in the package parses unit text.
`gm.units.parse` and `split_quantity` are gone.

Known limit: a bare number with a dimension is **still accepted as SI** in `set_params`, the
parameters of `gm.call`, `gm.Stream` and `gm.Fluid`, because the engine and the plants pass derived
SI values through them. It is refused in a plant dict (`params`, `inputs`), in a `gm.Case`, and in
the variables, limits and distributions of `gm.study`. Write the dict form in anything a user or an
agent supplies.

A `Doublet` has `volume_imbalance`, a `HeatingGrid` and a `CoolingGrid` have `surplus`: see
[equipment.md](equipment.md).

## Runtime and ops

| Name | Returns | Status |
| --- | --- | --- |
| `gm.runtime.settings(backend=..., precision=..., display_units=..., default_fluid=..., processes=...)` | a context manager and decorator: the settings apply inside it and are restored after; `backend=None` restores the automatic choice; `processes` (a whole number, default 1) is the number of worker processes of the trials of `gm.study.sample`, `sensitivity` and `minimize`, with the numbers and the order of a serial run (a script needs the `if __name__ == "__main__":` guard); an unknown name or value raises `ValidationError` | real |
| `gm.runtime.state()` | a copy of the current settings, plain data | real |
| `gm.ops.register_backend(backend)` | adds a `Backend` object to the registry under its `name`; `gm.runtime.settings(backend=name)` then selects it | real |
| `gm.ops.<op>` | the math API of the ops, see [physics.md](physics.md) | real |
| `gm.compiler.compile(plant)` | the executor of a plant, which traces it into a computation graph; importing `gm.compiler` registers it as the executor of `Engine(..., compile=True)`, see [native-engine.md](native-engine.md) | real |

The setters and getters of the settings (`set_precision`, `set_display_units`, `set_default_fluid`,
`get_precision`, ...) are not public: change a setting with `gm.runtime.settings`.

## Case

`gm.Case` is the strict, typed entry boundary of every run. It replaces `gm.Problem`,
`gm.Constraint` and `gm.Assumptions`, which are gone. Fixed sections `time`, `environment`,
`demand`, `choices`, `constraints` and `assumptions`, in a `case.json` with its CSV files next to
it ([data.md](data.md#the-case) holds the file section by section). Every class is a frozen
pydantic model that refuses unknown keys, with `to_dict`, `from_dict` and `schema` (closed at
every level, `additionalProperties: false`). Everything is stored in SI as plain numbers or arrays
(`Quantity(12, "degC")` is 285.15) and written as `{"value", "unit"}` in the SI unit. No field has a
default but absent (`None`); only `time` is required. An absent value that a call needs raises
`missing_value` naming its path, `missing_assumption` below `assumptions`.

| Name | Meaning | Status |
| --- | --- | --- |
| `gm.Case(time, environment=None, demand=None, choices=None, constraints=None, assumptions=None)` | the case; `time` is required | real |
| `gm.Case.from_json(path)`, `case.to_json(path)` | reads a `case.json` and the CSV files named in it, or writes both | real |
| `gm.Case.from_dict(data, folder=None)`, `case.to_dict()`, `gm.Case.schema()` | plain data, files read from `folder`; JSON Schema | real |
| `gm.case.Time(start, end, step)` | `end` is excluded; `.index` is the UTC `DatetimeIndex` of the steps | real |
| `gm.case.Environment(ground, reservoir, fluid, air)` with `Ground`, `Reservoir`, `Fluid`, `Air` | `temperature_at(depth)`, `pressure_at(depth)` apply the two rules of `gemini/physics/ground.py` | real |
| `gm.case.Demand(file, time_column, heating, cooling)` with `Service(column, unit, supply_temperature, return_temperature)` | reads the CSV into `.frame`, in W on the index of `time` | real |
| `gm.case.Choices(doublets, depth)` with `Range(min, max)` | what a study may vary | real |
| `gm.case.Constraint(on, quantity, min=None, max=None, equals=None, over="each", when="always")` | a limit on a quantity of a role; `over` is `each`, `sum`, `mean`, `max`, `min` or `duration`; `when` is `always` or `running`; `over` and `when` are the only defaults of the case | real |
| `gm.case.Assumptions(finance, emissions)` with `Finance`, `Capex`, `Opex`, `Revenue`, `Allocation`, `Emissions`, `CO2`, `CH4` | prices, cost factors per equipment kind, rate, lifetime, emission factors; no default of any value | real |
| `gm.case.Uncertainty(kind, min, max, std)` | the `uncertainty` of a number of `environment` or `assumptions`, in SI, by dotted path in `case.uncertainty` | real |
| `gm.case.roles()` | `{role: [quantities]}`, the closed table a `Constraint` names | real |

A number of `environment` or `assumptions` may declare how uncertain it is, next to its value and in
its unit: `{"value": 0.10575, "unit": "EUR/kWh", "uncertainty": {"kind": "uniform", "min": 0.08,
"max": 0.14}}`. `kind` is required: `uniform` (`min`, `max`), `triangular` (the mode is `value`;
`min`, `max`) or `normal` (the mean is `value`; `std`, with `min` and `max` optional to truncate).
`value` lies inside `[min, max]`; an unknown or missing key raises `ValidationError` naming its path;
`time`, `demand`, `choices` and `constraints` cannot carry one. The case stays frozen and a run,
`size` and `minimize` use only `value`; `sample` and `sensitivity` read the declarations
([data.md](data.md#the-case)).

The plant dict holds only the plant ([plants.md](plants.md#what-the-plant-dict-holds)). A run sets
the values of the case on a copy of the plant by module class ([engine.md](engine.md#how-the-case-reaches-the-modules)).

## Running

Run input is one format: a pandas DataFrame or a `gm.Dataset` with a timezone-aware UTC index, columns
named by binding `column`, units from the binding. A missing bound column raises `ValidationError`
(code `missing_column`) listing them all. A NaN row is a row code and the run continues.

```python
import gemini as gm

case = gm.Case.from_json("inputs/examples/shallow_district/case.json")
plant = gm.Plant.from_json("inputs/examples/shallow_district/plant.json")
results = gm.simulate(plant, case)
print(results.summary(units={"power": "MW", "temperature": "degC"}))
```

Use the functions for a run that is one call (agents, backend workers, examples, scripts) and
`gm.Engine` for what must live across calls: a run held in memory, a callback that reads the engine,
a manual checkpoint. Each function builds an `Engine`, calls the matching method and returns its
`Results`, so the numbers are the same on every backend; see
[engine.md](engine.md#functions-or-engine).

| Name | Returns | Status |
| --- | --- | --- |
| `gm.schedule(plant, case)` | run input, a UTC DataFrame: the demand and one column per scheduled control, named after its dotted path; `attrs["units"]` states the unit of each driven column, `attrs["outages"]` is `{doublet path: [ISO time of each outage step]}` and `attrs["check_only"]` lists the constraints the schedule does not enforce; sources load from the cheapest to the dearest; see [engine.md](engine.md#schedule) | real |
| `gm.simulate(plant, case=None, plan=None, clock=None, checkpoint=None, checkpoint_every=None, backend="numpy", callbacks=None, on_error="raise", compile=True)` | `Results`; `case=None` only with a `plan` (a building block has no demand); without a `plan` it schedules; `compile=False` forces the eager run | real |
| `gm.replay(plant, data, start=None, end=None, state=None, clock=None, only=None, checkpoint=None, checkpoint_every=None, backend="numpy", callbacks=None, on_error="raise")` | `Results`; `results.end_state` is the `state=` of the next call | real |
| `gm.live(plant, source, checkpoint, step=None, now=None, sink=None, backend="numpy", callbacks=None, on_error="raise")` | `Results` of the new rows; `checkpoint` is a required path | real |
| `gm.resume(checkpoint, callbacks=None)` | `Results` of an interrupted `simulate` or `replay`; `RunError` (code `checkpoint`) on a live checkpoint | real |
| `gm.Engine(plant, backend="numpy", callbacks=None, on_error="raise", compile=True)` | one runner, for complex tasks | real |
| `engine.simulate(profile, clock=None)` | `Results` | real |
| `engine.replay(data, start=None, end=None, state=None, clock=None, only=None)` | `Results`; `results.end_state` is the `state=` of the next call | real |
| `engine.live(source, checkpoint=None, step=None, now=None, sink=None)` | `Results` of the new rows | real |
| `engine.to_checkpoint(path)`, `gm.Engine.from_checkpoint(path, callbacks=None)`, `engine.resume()` | see [engine.md](engine.md) | real |
| `AutoCheckpoint(path, every=100)` | a callback that saves every N steps or every duration | real |
| Callback `on_progress(engine, done, total)` | a callback may raise `gm.errors.Cancelled`; committed ticks stay in `engine.results` | real |
| `gm.call(module, parameters, inlets, controls, on_error="raise", units=None)` | `{outlets: {port: {field: value}}, outputs: {name: value}, errors: [problem]}`; *units*; a run at one point. An inlet takes `m_dot` for a mass flow or `flow` for a volume flow (`{"value": 150, "unit": "m3/h"}`, by the density of the inlet's `fluid`), with `T`, `p` and an optional `fluid`; a volume unit on `m_dot` raises code `invalid_call` with the suggestion `flow` | real |

`rules`, `order`, `cooling_order` and the list and fraction forms of `operating_time` of the old
`gm.schedule` are gone: limits are the `constraints` of the case.

| `Results` | Returns | Status |
| --- | --- | --- |
| `names()` | `{path: [field]}` | real |
| `get(path, field, start=None, end=None, units=None)` | the time series `{time, value, unit}`; *units* | real |
| `summary(path=None, start=None, end=None, units=None)` | `{path: {field: {min, max, mean}}}`, each a value; *units*; schema `results_summary` | real |
| `errors()` | `[{path, code, message, suggestions, time}]`, `code` from `gm.errors.ROW_CODES` | real |
| `to_frame(units=None, table="series")` | DataFrame. `"series"`: columns `path.field`, the calculated-tag names, *units*, with `attrs["units"]`. `"energy"`: the table of `energy_report`, one row per module and energy output | real |
| `to_dict(units=None)` | `{time, duration, series: {path: {field: value}}, errors, skip_counts, end_state}`, `duration` a value; *units* | real |
| `to_npz(path)`, `gm.Results.from_npz(path)` | `.npz` | real |
| `to_bytes()`, `gm.Results.from_bytes(data)` | `.npz` bytes | real |
| `end_state` | `{position, module_states}` | real |
| `energy_report(units=None)` | `{path: {output: {energy, peak, hours, operating_hours, alarms, alarm_rate, skipped, errors, peaks, reasons}}}`, every number a value; *units*. A path without an energy output has the entry `""` | real |
| `results[path].field`, `skip_counts` | a pandas Series, `{path: {reason: count}}` | real |

## Data

Readers are `from_<format>` and writers `to_<format>` everywhere. A reader that returns a gemini
class is a classmethod of it (`gm.Case.from_json`); only a reader that returns no gemini class,
a demand frame, is a plain function of its folder.

| Name | Returns | Status |
| --- | --- | --- |
| `gm.data.from_csv(path, columns, unit, time_column=None)` | run input read from a CSV file: a UTC DataFrame at any constant step, `heating_demand` and `cooling_demand` in W, `units` and `quantities` in `attrs`; `columns` is `{file column: quantity}`, `time_column` by default the first column. Problems: `unknown_name`, `invalid_unit`, `missing_column`, `missing_value`, `out_of_bounds`, and `RunError` code `invalid_data` for an index that is not monotonic or has gaps, repeats or a changing step | real |
| `gm.data.from_values(values, unit, start, step, quantity)` | the same frame with one column; `quantity` is `heating_demand` or `cooling_demand`, `step` a duration or seconds | real |
| `gm.data.profile_schema()` | JSON Schema of that frame as a document | real |

gemini ships no profile: a demand is the caller's.

## Analysis

Details and inputs are in the docstrings and [economics.md](economics.md). Every number of these
returns is a value; every entry here takes *units*, except where a coefficient has no quantity.

| Name | Returns | Status |
| --- | --- | --- |
| `gm.analysis.calibrate` with `plant, dataset, params, start=None, end=None, backend="numpy", apply=True` | a `gm.analysis.CalibrationResult`; fits only through replay. With `apply=True` a successful fit replaces the current parameter as an explicit override and adds no dated snapshot. Pass parameter objects declared `calibratable=True`, such as `plant.get("heat_exchanger.thermal_conductance")` | real |
| `gm.analysis.nodal(plant, well, conditions, on_error="raise", units=None)` | `{well, cases: [{conditions, ipr: {rate, pressure}, vlp: {rate, pressure}, operating_point: {rate, wellhead_pressure, sandface_pressure}, error}]}`; with `"record"` a failed case has its problem in `error`; an injection well or its aquifer has the same shape | real |
| `gm.analysis.pump_curve(plant, pump, measured=None, units=None)` | `{pump, frequency, curve: {flow, head}, measured: [{flow, frequency, head, theoretical_head}], correction: {slope, offset}}`, or `correction` a null value with its reason | real |
| `gm.analysis.corrosion_forecast(model, until, units=None)` | `{correlation, rate, thickness, minimum_thickness, years_left}`; `thickness` a time series, `rate` stays in mm/year | real |
| `gm.analysis.fit_head_coefficients(flows, frequencies, heads, stage_count, units=None)` | a value of six ESP head coefficients, on their own basis | real |
| `gm.analysis.fit_head_correction(measured, theoretical, units=None)` | `{slope, offset}` of the head correction | real |
| `gm.analysis.estimate_reservoir_pressure(flows, bottomhole_pressures, units=None)` | `{pressure, r_squared}` | real |
| `gm.analysis.estimate_conductance(hot_in_T, hot_out_T, cold_in_T, cold_out_T, m_dot_hot, m_dot_cold, *, cp_hot, cp_cold, arrangement, units=None)` | a value of the apparent UA of an exchanger | real |

## Evaluate and study

Every `gm.evaluate` function takes `(plant, case, results, ...)`; only `capex` has no results.
The cost functions return a value with the parts of the result as more keys. A value the inputs
cannot give raises `ValidationError` (code `no_value`, or `missing_assumption` for an assumption
nobody gave); with `on_error="record"` it is a `Value` whose `value` is `None` and whose `reason`
says why. Prices, rates and cost factors are those of `case.assumptions`; gemini holds none.
Equipment declares `capex(finance)` and `fixed_opex(finance)` from its design values and the cost
factor of its kind, see [economics.md](economics.md#costs). A violated constraint is a check, never an
error.

| Name | Status |
| --- | --- |
| `gm.evaluate.totals(plant, case, results)` | real: `{name: value}` of what crossed the plant's edge over the run, each read from the ports of the edge modules, heat and cold as delivered, useful (at most the demand) and surplus; `None` with a reason when no edge module shows it. It also gives the KPIs `heating_coverage`, `cooling_coverage`, `cop`, `peak_heat`, `peak_cold` |
| `gm.evaluate.constraints(plant, case, results)` | real: a list of checks `{name, role, unit_path, quantity, passed, value, limit, worst_step}`, one per unit of the role of each constraint of the case, plus the supply temperatures of the services; `value` the worst of the run; `passed` is `null` with a reason `no_value` when there is nothing to judge (a role with no unit in the plant gives one such check); a role or quantity not in `gm.case.roles()` raises `unknown_name` |
| `gm.evaluate.plant_balance(plant, case, results)` | real, a list of checks: mass and energy of every module within 1e-9 and of the root within 1e-6. The root's in and out are the ports of the grids and environment modules, the aquifers and the plant ports of a building block run alone; a replay does not close at the root |
| `gm.evaluate.energy_balance(plant, case, results)`, `mass_balance(plant, case, results)`, `bounds(plant, case, results)` | real, each a check; they are ledger checks, see [economics.md](economics.md) |
| `gm.evaluate.run_all(plant, case, results)` | real: `{passed, checks: [check]}` of the ledgers, the bounds and the constraints |
| `gm.evaluate.capex(plant, case, on_error="raise")` | real: the sum, each module in `parts["modules"]` |
| `gm.evaluate.opex(plant, case, results, on_error="raise")` | real: the fixed opex of each kind in `parts["fixed_by_kind"]` and the bills of energy; no variable opex |
| `gm.evaluate.lcoh(plant, case, results, discount_rate=None, lifetime=None, on_error="raise")` | real |
| `gm.evaluate.lcoc(plant, case, results, discount_rate=None, lifetime=None, on_error="raise")` | real |
| `gm.evaluate.lcts(plant, case, results, discount_rate=None, lifetime=None, on_error="raise")` | real |
| `gm.evaluate.annualised_cost(plant, case, results, discount_rate=None, lifetime=None, on_error="raise")` | real |
| `gm.evaluate.co2(plant, case, results, on_error="raise")` | real: stepwise; a factor is needed only when its source is non-zero |
| `gm.evaluate.npv(plant, case, results, discount_rate=None, lifetime=None, on_error="raise")` | real |
| `gm.evaluate.payback(plant, case, results, on_error="raise")` | real |
| `gm.evaluate.capacities(plant, case, results)` | real: `{path: {kind, capacity, peak, share}}`, each a `Value` but `kind`, for the equipment that has a rating |
| `gm.evaluate.report(plant, case, results)` | real: a `Report`, see [the contract](#the-geomind-contract) |
| `gm.evaluate.compare(reports, by)` | real: a `Comparison`, see [the contract](#the-geomind-contract) |
| `gm.evaluate.failures(results)` | real: a `Failures`, the failed and skipped rows of a run grouped by module path and row code, most frequent first: `groups` of `{path, code, kind, count, first, last, message}`, `total`, `to_dict()` (`{total, groups}`, JSON) and `to_frame()` |
| `gm.study.size(plant, case, backup)` | real: a new plant with first sizes under the policy `backup` (`"none"`: the boiler covers what the doublets cannot reach; `"peak"`: the whole heating peak with the doublets off; no default, `missing_value` without it); a rated unit has the capacity of the largest duty the case lets it run, so `share <= 1`; the notes are `plant.sizing` `{sized, unchanged, broken, simulation}` and `size` never hides an infeasible start |
| `gm.study.minimize(plant, case, objective, variables=None, constraints=None, evaluations=100, *, plan=None)` | real: `{best, feasible, fixed, history, evaluations}`, `best` a `Best` (a `Value`) whose `parts["parameters"]` are `{name: Quantity}` and whose `["plant"]` is the best plant; `Best.to_dict()` is plain JSON (the plant as its plant dict, quantities as `{value, unit}`) and `Best.from_dict` reads it back; the variables are those of `case.choices` (`size.doublets`, `depth`) unless given; a name is a plant `path.parameter`, `case.<path>`, `size.doublets` or `<role>.<parameter>` (every unit of a role of `gm.case.roles()`) |
| `gm.study.sample(plant, case, metrics, count, seed, *, plan=None)` | real: `Sample`, a dict `{samples, summary}`, `summary` per metric `{mean, p5, p50, p95, failed}`, each a `Value`, `failed` the draws left out because their run had failed steps (their metrics are `None` with the count and the top failure); draws only the `uncertainty` the case declares (`missing_value` if none), never a plant parameter; `seed` has no default; `to_dict()` / `Sample.from_dict` are JSON |
| `gm.study.sensitivity(plant, case, metrics, *, plan=None)` | real: a `Tornado`, a list sorted by effect with `to_frame()`, `to_dict()` and `Tornado.from_dict`; a bound whose run had failed steps is `None` with a reason, and so is the effect; each value the case declares an `uncertainty` for, at its `min` and `max` (`value ± std` for a `normal` without bounds) |

`case` of `gm.study.minimize` and `sample` plans the demand for each trial with `gm.schedule` on the
design of that trial, so a variable that changes the design changes the plan. A `plan` (run input, a
frame) stays fixed over the trials and lets `case` be `None` for a building block with no demand
and metrics that need no assumptions; with neither the call raises `ValidationError` code
`missing_value`. A case without prices gives an economic metric a reason, not a value.

Known limits of `gm.study`:

- `size.doublets` is searched only for a plant class that takes the structural size `doublets`
  (`gm.plants.capabilities()[class]["choices"]`). On a plant without it the count is not searched
  and is listed in `fixed` with its reason, and `size` keeps the doublets the plant has and lists
  that in `plant.sizing["unchanged"]`; `invalid_design` is raised only when nothing is left to search.
- A search that varies the doublet count, the flow or the depth leaves the rating of the
  injection pump at the value `size` gave it. Measured on the hackathon case, doubling its power
  moves LCTS by 0.13 EUR/MWh and quadrupling it by 0.38, under 0.5 EUR/MWh.
- `evaluations` counts the simulations **for each doublet count**; a trial costs about two
  simulations of the plant (0.15 s on the hackathon year); `gm.runtime.settings(processes=n)` runs the
  doublet counts of `minimize` in parallel.

Known limits of the cost model: a module without an equipment kind (`IceStorage`,
`ESP`, `LineShaftPump`, `AquiferStorage`, `ORC`, `Separator`, `GasCompressor`, ...) adds no capex,
see [equipment.md](equipment.md#cost-kinds-and-the-equipment-mixin).

## The geomind contract

geomind follows the list below. It is every call that `examples/hackathon.py` makes, in the order
of the flow, with its signature and its return shape. `python examples/hackathon.py` runs it (see
[examples/README.md](../../examples/README.md)); `tests/e2e/test_examples.py` runs it in CI.

| Step | Call | Returns |
| --- | --- | --- |
| Read the case | `gm.Case.from_json(path)` | `gm.Case`. `ValidationError` with `path` and `code` for a wrong file |
| Read a candidate | `gm.Plant.from_json(path)` | `gm.Plant`. `plant.to_dict()` is the plant dict |
| Fill a plant | `gm.plants.<Class>(...)`, then `plant.missing_parameters()` and `plant.set_params("", values)` | a list of `{path, type, quantity, unit, units, minimum, maximum, enum, description}`, one per value still unset (the reservoir and the wells that the case gives are in it until a run); a run with a value missing raises `missing_value` naming all of them |
| Make a value | `gm.units.Quantity(value, unit)`, with `unit` a text of the `Unit` table | `Quantity`: `.value`, `.unit`, `.si`, `.to(unit)`, `to_dict()` |
| Size | `gm.study.size(plant, case, backup)` | a new `gm.Plant`; `plant.sizing` is `{"sized": [{path, value, reason}], "unchanged": [{path, reason}], "broken": [{unit_path, role, quantity, value, limit, worst_step}], "simulation": str}` |
| Search | `gm.study.minimize(plant, case, objective, variables=None, constraints=None, evaluations=100, *, plan=None)`, called as `minimize(sized, case, "lcts", variables, evaluations=15)`, `variables` a list of `{path, parameter, lower, upper}` | `{"best": Value, "feasible": bool, "fixed": [{name, value, reason}], "history": [...], "evaluations": int}`; `result["best"]["plant"]` is the best `gm.Plant`, `best.parts["parameters"]` is `{name: Quantity}`. `feasible` says whether `best` passes every constraint of the case and has no failed step; with no feasible trial `best` is the least violating one that ran. `fixed` lists the variables the plant could not take (a role it lacks, `size.doublets` on a plant without it). Each `history` item is a `Value` whose `reason` is `None` for a feasible trial, else the first failed check of `gm.evaluate.constraints` (a dict) or a text for a metric limit or a failed run, and whose `parts["violation"]` is the relative violation. `ValidationError` code `invalid_design` when nothing is left to search |
| Simulate | `gm.simulate(plant, case, plan=None, ...)` | `gm.Results`, planned by `gm.schedule(plant, case)` |
| Report | `gm.evaluate.report(plant, case, results)` | `Report`, a `dict`, below |
| Read a value | `report[key].to(unit)`, with `unit` a text of the table (`"GWh"`, `"MEUR"`, `"MEUR/yr"`, `"EUR/MWh"`, `"kt"`) | `Value`: `.value` a number or `None`, `.unit`, `.reason` (why `value` is `None`), `.parts`, `.si` |
| Compare | `gm.evaluate.compare(reports, by=["lcts", "co2"])` | `Comparison`, below |
| Uncertainty | `gm.study.sample(plant, case, ["lcts", "co2"], count, seed)`: the case declares `uncertainty` next to its numbers | `Sample` `{samples, summary}`, `summary[metric]` `{mean, p5, p50, p95}`; a case with none raises `missing_value` |
| Why steps failed | `gm.evaluate.failures(results)` | `Failures`: `groups` of `{path, code, kind, count, first, last, message}`, most frequent first; `to_dict()`, `to_frame()`; `report["failures"]` holds it |
| Table | `comparison.to_frame()` | a DataFrame, one row per report, columns `<metric> [<unit>]` in display units (MWh, MW, MEUR, MEUR/yr, EUR/MWh, kt; `to_frame(units={"lcts": "EUR/MWh"})` chooses another), `rank_<metric>`, `pareto` and `feasible` |
| Sensitivity | `gm.study.sensitivity(plant, case, ["lcts"])`: the case declares `uncertainty` next to its numbers | a list of `{parameter, metric, low, high, at_low, at_high, effect}`; `.to_frame(units=None)` a DataFrame of columns `parameter, metric, low, high, at_low, at_high, effect, unit`, the metric in its display unit or the one in `units` |
| Save | `report.to_dict(units=None)`, `comparison.to_dict()`, `Comparison.from_dict(data)`, and `to_dict()` / `from_dict` of `Best`, `Sample`, `Tornado`; `failures.to_dict()` | plain JSON (`json.dumps` works); the report in display units (MWh, MW, MEUR, EUR/MWh, kt, m3/h, degC) or `{metric: unit}`; `str(report)` is that JSON; values inside stay SI |

`Report` is a `dict` subclass with these keys, each a `Value` in SI unless said: `heat_delivered`,
`cold_delivered`, `boiler_heat`, `electricity_bought`, `gas_bought` (J over the run),
`capacities` (`{path: {kind, capacity, peak, share}}`), `capex`, `opex`, `lcts`, `lcoh`, `lcoc`,
`co2`, `services` (the list of services the plant is asked to deliver, `"heating"` and `"cooling"`), `constraints` (a list of `{name, role, unit_path, quantity, passed, value, limit,
worst_step}`; `value` and `limit` are `Value`s), `passed` (`False` if any constraint failed,
`True` if none failed and one passed, else `None`) and `failed_steps` (an `int`). Its costs are
read with `on_error="record"`: a cost the case or the plant cannot give has `value` `None` and a
`reason`, and a plant that does not show a quantity (a cold delivered with no cooling grid) says so
in `reason`. `report.to_dict(units=None)` gives plain JSON with `{value, unit}` for every `Value`, in display units.

`Comparison` is a `list`, one entry per report in the order given: `{index, values, ranks,
pareto, feasible}` and, for an infeasible report, `reasons`. `values` are the metrics as `gm.units.Quantity` in SI
(a plain number stays a float, `None` for no value; only `to_frame` converts to display units), `ranks` start at 1
(equal values share a rank, the feasible come before the infeasible), `pareto` is `True` when no
other feasible report is at least as good in every metric and better in one. A report is
feasible when no step failed, no constraint failed and every service in `services` is delivered;
`reasons` are the failed items of `gm.evaluate.constraints` and `{name, reason}` for a failed step
or a service not delivered. `by` is a name, a list of names or `{metric: "min" | "max"}`; a report without a value
of a metric ranks last for it and is never on the front.

What the calls do not do, honestly: they accept a bare SI number in `set_params`, `gm.call`,
`gm.Stream` and `gm.Fluid`; `fluids` remains in a plant dict for a plant with no case; consumer
return pressure stays a design parameter of the plant; a search varying the doublets, flow or depth
leaves the injection pump at the rating of `size`.

## Errors

Every public call raises on failure by default. A call that can report instead takes
`on_error="raise" | "record"`: `validate` functions return the problems, `gm.call` returns them
under `errors`, a run records them in `results.errors()` and continues, a cost value is
`{value: null, reason}`. `gm.evaluate.*` checks return a check; a violated limit never raises.

`gm.errors` holds seven error classes and `GeminiWarning`, listed with their use in [errors.md](errors.md):
`GeminiError` with `ValidationError`, `DefinitionError`, `PhysicsError`, `RunError`, `Cancelled` and
`NotImplementedYet`. `to_dict()` is the problem
`{path, code, message, suggestions}` (schema `problem`; the return shape of an error, not an
input), `error.problems` lists every problem of an error, `CODES` is the fixed `code` list
and `ROW_CODES` the row codes with their meaning.

## Change log

The lines of the unreleased changes are in the order the work was done; the first line below sums
them up, and a later line wins over an earlier one where they differ (several older lines name
`gm.Problem`, `gm.kpi` or `gm.optim`, which are gone).

| Version | Date | Change |
| --- | --- | --- |
| 0.2.0, unreleased changes | | The study release. New: `gm.study.size(plant, case, backup)` (the policy has no default; rated units carry their duty; the notes list what the start breaks); `plant.missing_parameters()` and one error that lists every missing path with its meaning; the `uncertainty` of the case and `gm.case.Uncertainty`, `Sample`, `Tornado`; `gm.evaluate.failures(results)`, also in the report; `to_dict()` / `from_dict` of `Best`, `Sample`, `Tornado`, `Comparison`, `Report`; `report.to_dict(units=None)` in display units; `gm.runtime.settings(processes=n)` for parallel trials, one compiled graph for all trials of a study. `Comparison` values are `Quantity`. An `ESP` row outside its curve fails with `out_of_range`; an `InjectionPump` with a setpoint below its suction does not pump (`is_pumping`). Removed, with no alias: `gm.plants.example`, `gm.data.synthesize`, `gm.analysis.injectivity`, `calibrate_pump`, `calibrate_corrosion`, `erosion` (stubs that only raised `NotImplementedYet`; a name returns when it is built, the list is in [refactor-notes.md](refactor-notes.md#planned-features-removed-from-the-api)). Callers move with the table below. |
| 0.2.0, unreleased changes | | **The case.** `gm.Case` and the folder `gm.case` replace `gm.Problem`, `gm.Constraint` and `gm.Assumptions`; `gm.__all__` has `Case` and `case` and no `Problem`, `Constraint` or `Assumptions`; `gm.optim` is `gm.study`. Every call takes `(plant, case)`, plus `results` when it reads a run: `gm.schedule(plant, case)`, `gm.simulate(plant, case=None, plan=None, ...)`, `gm.evaluate.*`, `gm.study.*`. The input file is `case.json` with CSV profiles, not `problem.json`. A plant dict holds only the plant: the ground, reservoir, brine, air, return and supply temperatures are the case's, set on a copy of the plant by module class, and a plant dict that states one is refused. Nothing a user must decide has a default: an absent value raises `missing_value` (`missing_assumption` below `assumptions`). One unit format: a `Quantity` or `{"value", "unit"}`, no unit text anywhere, `gm.units.parse` is gone. Costs on every equipment kind, `capacities`, `report`, `compare`, `gm.study.size`, `sensitivity` and `gm.plants.capabilities` are built. Known limits: bare SI numbers remain accepted in `set_params`, `gm.call`, `gm.Stream` and `gm.Fluid`; `fluids` remains in the plant dict for a plant with no case; the consumer return pressure stays a plant parameter. |
| 0.2.0, unreleased changes | | `gm.Problem`, `gm.Constraint`, `gm.Assumptions` and `Problem.apply_site` are removed. `gm.schedule(plant, case)` and `gm.simulate(plant, case=None, plan=None, ...)` take a `gm.Case`: a run sets the values of the case on a copy of the plant by class (ground on `Formation`, reservoir and brine on each `Doublet` at its depth, air on `Atmosphere`, the return and the required supply temperature on `HeatingGrid` and `CoolingGrid`), and the schedule finds its limits by role and quantity (`doublet`, `production_flow`, `brine_cooling`). A value the plant needs and the case lacks raises `missing_value` (`missing_assumption` for a price) naming its path in the case. |
| 0.2.0, unreleased changes | | A parameter that the case holds (`Doublet.gradient`, `surface_temperature`, `permeability`, `thickness`, `Formation.geothermal_gradient`, `surface_temperature`, `HeatingGrid` and `CoolingGrid` `return_temperature` and `minimum_supply_temperature` or `maximum_supply_temperature`) is refused in a plant dict (`invalid_value`, naming the case path) and never written by `to_dict`. A value with a unit in a plant dict, `params` or `inputs`, is a `{"value", "unit"}`, and `to_dict` writes it so. `HeatingGrid`, `CoolingGrid` and `Cooler` carry water. An engine checkpoint of a plant stores its plant dict and its `state_dict`. |
| 0.2.0, unreleased changes | | New `gm.Case` and the folder `gm.case` (`Case`, `Time`, `Environment`, `Ground`, `Reservoir`, `Fluid`, `Air`, `Demand`, `Service`, `Choices`, `Range`, `Constraint`, `Assumptions`, `Finance`, `Capex`, `Opex`, `Revenue`, `Allocation`, `Emissions`, `CO2`, `CH4`, `roles()`): a strict, frozen, SI-stored entry boundary with `to_dict`, `from_dict`, `schema`, `from_json`, `to_json`. New `gm.physics.ground.reservoir_temperature` and `reservoir_pressure`; `gm.units` gains `EUR/m3`, the type `MoneyPerVolume`. The folder `gm.optim` is renamed `gm.study`. `gm.Problem`, `gm.Constraint` and `gm.Assumptions` stay until the schedule, the run and `gm.evaluate` are ported to `gm.Case`. |
| 0.2.0, unreleased changes | | Costs on every equipment kind. A module that is equipment declares `equipment_kind` (one of `gm.case.Capex`'s 19 kinds) and `capex(finance)` and `fixed_opex(finance)` in the currency of the case; grids, environment, control, mixers, splitters and valves have none. `Doublet` is the `production_pump` and the wells are `drilling`; a `HeatPump` in cooling mode is a `compression_chiller`. A factor or a fixed share the case lacks is `missing_assumption` naming `assumptions.finance.capex.<kind>` or `assumptions.finance.opex.fixed.<kind>`. `gm.evaluate.*` take `(plant, case, results, ...)`; `capex` gives the sum and each module in `parts["modules"]`, `opex` the fixed opex by kind in `parts["fixed_by_kind"]` (no variable opex any more), `co2` and the CO2 price follow the profiles of the case step by step. `constraints` checks the constraints by role and the supply temperatures of the services, each item `{name, role, unit_path, quantity, passed, value, limit, worst_step}` (the item had `path`). Built: `capacities`, `report` (a `dict` with `to_dict()`), `compare(reports, by)` (a list with `to_frame()`, ranks and `pareto`). `gm.types.Cost` is gone. `gm.data.legacy.results_to_frame` is `gm.data.legacy.to_frame`. |
| 0.2.0, unreleased changes | | `gm.study` takes the case: `minimize(plant, case, objective, variables=None, ...)` searches `case.choices` (`size.doublets` discrete, `depth`) by default, and a variable or a distribution may be a number of the case named `case.<path>`; `size`, `sensitivity` and `gm.plants.capabilities` are built. |
| 0.2.0, unreleased changes | | Examples: five flat scripts in `examples/` (`quickstart.py`, `hackathon.py`, `costs.py`, `uncertainty.py`, `plant.py`); `examples/basics`, `recipes` and `cases` are removed. The hackathon and shallow district samples hold a `case.json`; the hackathon candidates are in `plants/`. |
| 0.2.0, unreleased changes | | The COP estimate of the cost dispatch reads the module's `carnot_fraction`, or `lorenz_fraction` for a Lorenz machine, which it had read as the Carnot default. The default 0.5 cites H. U. Frutschi, ABB Review 5/1996, pp. 33-34; the sample plants state it. |
| 0.2.0, unreleased changes | | `plan.attrs["check_only"]` lists a constraint the schedule enforces in part with only the bounds left: a duration of `min` and `max`, of `equals` and another bound, or a brine cooling with a `min`. |
| 0.2.0, unreleased changes | | A `Doublet` with a `depth` and no `gradient` or `surface_temperature` when a run or a schedule starts raises `ValidationError` code `missing_value` with the path of each value, whatever `on_error` says; `missing_parameters` lists them. |
| 0.2.0, unreleased changes | | Private paths only: `gm.call` is `gemini/modules/call.py`, and the old project reader `gemini/plants/_utils/legacy/`, so no run folder imports above the run, in a function or not. No change to a name of this page. |
| 0.2.0, unreleased changes | | One folder per concern, flat public names. Top level: `gemini/modules`, `plants`, `physics`, `ops`, `runtime`, `engine`, `run`, `types`, `units`, `errors`, `data`, `study`, `evaluate`, `analysis`, `compiler`, `_utils`; `gm.__all__` is pinned. The folders `core`, `base`, `registry`, `testing`, `backends`, `checks`, `economics`, `profiles`, `utils` and `graph` at the top are gone. Run folders import none of `compiler`, `data`, `study`, `evaluate`, `analysis`; importing `gm.compiler` registers its executor, and a run works without it. |
| 0.2.0, unreleased changes | | One `gm.Problem` for every call: `gm.Problem`, `gm.Constraint`, `gm.Assumptions`, with `to_dict`, `from_dict`, `schema`; `Problem.from_json`, `to_json`, `apply_site`. `gm.schedule(plant, problem)`; `gm.simulate(plant, problem=None, plan=None, ..., compile=True)`; every `gm.evaluate` function takes `(plant, problem, results, ...)`, `gm.study.minimize` and `sample` `(plant, problem, ..., *, plan=None)`. A schedule loads sources by marginal cost and reads its limits from constraints; `attrs["check_only"]` lists the constraints it does not enforce. `Assumptions.prices` and `co2_price` replace the six flat price fields. A `Doublet` with a `depth` and no geotherm waits for the site. |
| 0.2.0, unreleased changes | | `gm.evaluate.constraints` replaces `Limits`, `limits` and `operating_time`; `gm.evaluate.totals` also gives `heating_coverage`, `cooling_coverage`, `cop`, `peak_heat` and `peak_cold`, the former `gm.kpi.compute`. `gm.checks.*`, `gm.economics.*` and `gm.kpi.*` are `gm.evaluate.*`, `gm.profiles.*` is `gm.data.*`, `calibrate` and `CalibrationResult` are in `gm.analysis`. |
| 0.2.0, unreleased changes | | Naming: readers `from_<format>`, writers `to_<format>`. `Plant.save`, `load` are `to_json`, `from_json`; `gm.plants.from_dict` is `gm.Plant.from_dict`; `gm.plants.convert_legacy` is `gm.Plant.from_legacy`, which returns a plant; `Results.save`, `load` are `to_npz`, `from_npz`; `Engine.save_checkpoint`, `load_checkpoint` are `to_checkpoint`, `from_checkpoint`; `Module.load_state_dict` is `set_state_dict`. `gm.evaluate(...)` is `gm.call(...)`; `gm.testing.check_module` is `gm.modules.check`. `gm.runtime` has `settings` and `state` only. |
| 0.2.0, unreleased changes | | A module class that states a `category` registers itself; `gm.modules.register` and `load_file` are gone, `abstract = True` leaves a class out. New codes `duplicate_name` and `conflicting_value`. Plant classes are in `gm.plants`, not `gm.modules`. |
| 0.2.0, unreleased changes | | New names whose work lands later: `gm.plants.capabilities`, `gm.data.synthesize`, `gm.evaluate.capacities`, `report`, `compare`, `gm.study.size`, `sensitivity`. New: `gm.compiler.compile`, `gm.ops.register_backend`. |
| 0.2.0, unreleased changes | | `InjectionPump.efficiency` has no default: without a value or head and power curves it raises `missing_value`, and `gm.plants.convert_legacy` raises it for a project without the pump's power column. |
| 0.2.0, unreleased changes | | gemini knows no sample problem. Removed: `gm.challenge_rules`, `HackathonPlant`, `gm.profiles.demand`, `gm.profiles.get`, `gm.profiles.names`, `gm.checks.operating_days`, `rules["operating_days"]`, `attrs["outage_days"]`, and `inputs/hackathon/`, now `inputs/examples/hackathon_2026/`. New: `gm.profiles.from_csv`, `gm.profiles.from_values`, `gm.checks.operating_time`, `rules["operating_time"]`, `attrs["outages"]`, `rules` on `gm.study.minimize` and `sample`, where `profile=None` now raises. `gm.schedule` has no default for `doublet_flow` or `max_brine_cooling`, and works on any constant step. `gm.plants.example` of the five template plants raises `NotImplementedYet`. `Doublet.gradient` and `surface_temperature` have no default: a `depth` without them raises `missing_value`. `gm.checks.run_all` takes `duration`. `normal_density` takes its reference conditions. `profile_schema` describes columns, time and values only. |
| 0.2.0, unreleased changes | | `gm.study.minimize` respects the case: a trial is feasible when no step fails and every constraint of the case passes; the result gains `feasible` and `fixed`, a `history` item has `reason` (the first failed check) and `parts["violation"]`, and the search ranks every feasible trial before every infeasible one. A variable `<role>.<parameter>` (a role of `gm.case.roles()`, for example `heat_pump.capacity`, `doublet.nominal_flow`) reaches every unit of the role after the doublet count; `depth` on a plant with no depth of its own is every doublet's; a role the plant lacks and `size.doublets` on a plant without it go to `fixed`, and `invalid_design` is raised only when nothing is left to search. `gm.study.size` gives a heat pump the part of the heating peak the reservoir cannot reach, not the peak, and rates the `InjectionPump`. `InjectionPump` has `nominal_flow` and `nominal_head` and is priced as `injection_pump`. `gm.evaluate.compare` entries gain `feasible` and `reasons`, feasible reports rank first and the front holds only feasible ones; `report` gains `services`. `to_frame(units=None)` of `Comparison` and of the sensitivity shows display units (MWh, MW, MEUR, EUR/MWh, kt), columns `<metric> [<unit>]`. Prices of `inputs/examples/hackathon_2026/case.json` cited: electricity, gas and CO2. |
| 0.2.0, unreleased changes | | `make sandbox-image` builds `gemini-sandbox:<version>`, the image of geomind's module sandbox, from `docker/sandbox.Dockerfile`. |
| 0.2.0, unreleased changes | | `gm.analysis.nodal` solves injection wells: the wellhead pressure of a rate, or the rate of a wellhead pressure. |
| 0.2.0, unreleased changes | | `gm.challenge_rules()` and `gm.profiles.demand()`. `profile=None` in `gm.study.minimize` and `sample` is the demand year under the challenge rules, and a demand frame is planned for each trial. Reading a finished run no longer builds the JSON of every column. |
| 0.2.0, unreleased changes | | `gm.plants.example` of the five template plants holds the challenge values on two doublets, with `inputs`, and runs the demand year (`examples/cases/challenge_year.py`); a value file may state `size`. A plan states the unit of its columns in `attrs["units"]`, and a run reads them: a binding in another unit no longer misreads a plan. On a root plant, which has no ports, a failing row is now an error: it passed unnoticed on a traced plant. A stopped drive circuit of `AdsorptionChiller` has no driving-temperature limit. |
| 0.2.0, unreleased changes | | `Doublet.volume_imbalance` and `InjectionReservoir.liquid_flow`. `gm.checks.Limits` takes a parameter. `gm.checks.limits` on a run whose every row failed gives `passed: null` with a reason `no_value` instead of a `KeyError`. |
| 0.2.0, unreleased changes | | `HeatingGrid.surplus` and `CoolingGrid.surplus`, what the water gives above the demand. `gm.kpi.totals` adds `heat_useful`, `heat_surplus`, `cold_useful`, `cold_surplus`; `gm.kpi.compute`, `gm.economics.lcoh`, `lcoc` and `lcts` read the useful energy. `HackathonPlant`, `HeatingCoolingPlant`, `HeatingFullCoolingPlant` and `HeatingAbsorptionCoolingPlant` return the drive water of their chillers through a bypass past the users (`loads` and `heat_return`, `drive_splitter` and `drive_mixer`), a loop the engine closes, and `gm.schedule` sets its split: the heating supply stays at its setpoint. |
| 0.2.0, unreleased changes | | `gm.schedule` finds roles from the wiring: a unit that feeds the `CoolingGrid` is a cooling unit, a `HeatPump` included. `rules["cooling_order"]`, heat-driven first by default, dispatches absorption, adsorption and compression chillers, each up to its capacity. `Plant.feeds`. |
| 0.2.0, unreleased changes | | Template plants take `size={"doublets": n}`, 1 to 3: `doublet` is now `d0`, with `d1`, `d2`, `production_mixers` and `injection_splitters`, and a plant-level `depth`. `Doublet.gradient` and `surface_temperature` default to the challenge values. |
| 0.2.0, unreleased changes | | `Plant.set_inputs`, `Plant.input_value`, `Plant.target_of`, `Plant.source_of`. The plant dict has one key `inputs`, `{path: value}`, in both forms; `gm.plants.from_dict`, `gm.schedule` and a run use it. `boundary[""]["inputs"]` and `boundary[""]["root_inputs"]` are gone: a plant inlet field is the path `port.field`. |
| 0.2.0, unreleased changes | | Leaves compute, plants connect. `_compute_outputs` is gone: a leaf computes once in `forward`. Every composite is a `Plant`, which never writes `forward`, with `HeatingSubstation`, `CoolingSubstation`, `NodalDoublet`, `DistrictEnergyPlant`, `BoilerChpPlant`, `ParallelExchangerPlant` and `ATESPlant` among them. The engine closes loops (`loop_not_converged`) and solves `Plant.constrain`. `CirculationPump` carries the flow of a building circuit, and its electricity is counted. Plant outputs are `Output.difference`, `Output.ratio` and `Output.sum` of paths; `Results` reads a path. |
| 0.2.0, unreleased changes | | No JSON file in `gemini/`: `gemini/assets/` is gone. A plant of a class stores `{type, size?, params}`, `to_dict(structure=True)` its structure. Templates are the plant classes `HeatingPlant`, `HeatingCoolingPlant`, `HeatingFullCoolingPlant`, `HeatingAbsorptionCoolingPlant` and `HeatingHeatPumpCoolingPlant`, and `DistrictNetwork` and `MultiWellPlant` take their size. Removed names are listed below. Code `loop_without_state` and `migration_failed` are gone, `loop_not_converged` is new. |
| 0.2.0, unreleased changes | | `gm.study.minimize` and `gm.study.sample` are built, on the metrics of `gm.kpi` and `gm.economics`; each takes `assumptions`. |
| 0.2.0, unreleased changes | | `gm.evaluate`: a volume unit on `m_dot` names `flow` in its message, `path` and `suggestions`; the code stays `invalid_call`. |
| 0.2.0, unreleased changes | | `gm.economics.annualised_cost` and `gm.economics.lcts`, the levelised cost of heat and cold together. |
| 0.2.0, unreleased changes | | `rules["operating_days"]` of `gm.schedule` is built: a count or a list of outage dates, `attrs["outage_days"]`, the column `<heat pump>.is_running`. New `gm.checks.operating_days`, since replaced; `gm.checks.run_all` takes `days`. |
| 0.2.0, unreleased changes | | File layout of `gemini/modules/`: `plant.py` and `container.py` beside `module.py`, the plant tools in `plants/_utils/`, `heating/_burner.py`, `cooling/_sorption.py`. Private paths only: no change to a name of this page. |
| 0.2.0, unreleased changes | | Data layout: `gemini/assets/` (installed: plant structures, templates) and `inputs/` (repository only: hackathon inputs, example values, measured data, legacy project); `datasets/` is gone. New code `inputs_missing`: `gm.profiles.get` and `gm.plants.example` raise it outside a source checkout. Templates `DistrictNetwork` and `MultiWellPlant` are now `district_network` and `multi_well`. `gm.plants.example("Doublet")` is the registered class, with the outputs of its structure file. No change to a name of this page. |
| 0.2.0, unreleased changes | | Plants `NodalDoublet`, `ParallelExchangerPlant`, `BoilerChpPlant`, `DistrictEnergyPlant`, `HackathonPlant`: catalogue only, no change to a name of this page. |
| 0.2.0, unreleased changes | | `gm.kpi.totals(plant, results)`: heat and cold delivered, electricity bought and sold, gas bought, emissions, waste, chemicals and losses, read from the ports of the edge modules. The hackathon example has all seven edge modules, a desander and inhibitor dosing. |
| 0.2.0, unreleased changes | | `gm.checks.plant_balance(plant, run)`: a `Check` of mass and of energy per module and for the plant, whose in and out are the ports of the grids and environment modules. `Flare` has `fuel` and `loss_out`. |
| 0.2.0, unreleased changes | | Port quantities are in `Results`: `<port>.mass_flow`, `.volume_flow`, `.temperature`, `.pressure`, `.enthalpy_flow`, `.gas_flow`, `.co2_flow`, `.chemical_flow`, and a `Power` port under its name. Outputs a port shows are gone (`useful_duty`, `condenser_duty`, `electricity`, `electricity_generated`, `heat_loss`, `heat_supplied`, ...), and so are automatic sums, the `sum` key of a plant's `outputs` and the quantities `ElectricityGenerated`, `HeatLoss`, `HeatSupplied` and `HeatAbsorbed`. `gm.kpi` and `gm.economics` read the edge modules; `waste_disposal_price`, `chemical_price`. |
| 0.2.0, unreleased changes | | Port names follow `<role>_in` and `<role>_out` (`gm.plants.migrate` converts stored specs). `Inlet(Stream, kind=...)` replaces `stream=`, the first argument of a declaration is `type`, `p.add(type, ...)`, `p.connect(source, target, type=None)`, a connection's `type: "state"`; `describe()` gives ports `{kind, fields}`, outputs `{unit, quantity, soft_sensor}`, connections `{source, target, kind, type}`. |
| 0.2.0, unreleased changes | | Losses are ports: wells, pipes, storage, boilers, `CHP`, `ORC`, `FlashTurbine`, `CentrifugalPump`, `GasCompressor`, `BoreholeField` and `DownholeHeatExchanger` have `loss_out`, signed, to `Atmosphere.heat_in` or `Formation.heat_in`; `DistrictNetwork` and `ATESPlant` expose one `loss_out`. |
| 0.2.0, unreleased changes | | Category `environment`: `Atmosphere` holds the ambient conditions and computes `co2_emission` and `methane_emission`; `Formation` is created by `Doublet`. `Vent` is gone: its inlet connects to `Atmosphere.gas_in`. `Boiler`, `CHP` and `Flare` have `flue_out`; `Pipe`, `Cooler`, `ThermalStorage` and `ORC` have `air_in` instead of `ambient_temperature`; `Cooler` has `air_out` and may close a water loop (`loop_pressure`, `flow`). |
| 0.2.0, unreleased changes | | Category `grids`: `ElectricityGrid` (from `GridConnection`, without prices), `GasGrid`, `HeatingGrid` (from `HeatConsumer`), `CoolingGrid` (from `CoolingConsumer`), `WasteGrid`, `ChemicalGrid`; category `demand` removed. `GasMakeup` has `gas_in`, `grid_in`, `fuel_out`, `excess_out`; a burner's `fuel_in` shows what it burned and `gas_out` is gone. `gm.schedule` writes `<grid>.flow`. `validate` reports `root_plant_port`. |
| 0.2.0, unreleased changes | | Ports carry a `Power`: `Inlet(Power, kind="electricity")`, `Outlet(Power, kind="heat")`; `many=True`, `drawn=True`, `offered=True`; consumers get `power_in`, generators `power_out`; a plant port may list several ends. `gm.streams.names()` adds `heat`, `air`, `waste`, `chemical`. |
| 0.2.0, unreleased changes | | Layout: helpers in `gemini/modules/_utils/`, physics of one category in its `_physics.py`. Public names unchanged. |
| 0.2.0, unreleased changes | | One unit format. New `gm.units.Unit`, a `str` enum generated from the unit table, and `gm.units.Quantity(value, unit)` is the one shape of a value with a dimension: `.si`, `.to(unit)`, `to_dict`, `from_dict`, equality on SI. Removed: `gm.units.parse`, `split_quantity`, and every reading of unit text: `"150 m3/h"` is `ValidationError` `invalid_value` in `set_params`, the plant dict, `gm.call`, `gm.Stream`, `gm.Fluid`, `gm.Problem`, `gm.Constraint` and `gm.Assumptions`, which take a `Quantity` or `{"value", "unit"}`. A unit of another dimension is `invalid_unit` and lists the units of the field; the schema of a parameter with a unit offers `{"value": number, "unit": enum}`. New units `yr`, `%/yr`, `g/kWh`, `kg/J`, `J/yr`, `1/yr`, `EUR`, `EUR/MWh`, `EUR/kWh`, `EUR/kg`, `EUR/t`, `EUR/W`, `EUR/m`, `EUR/(W/K)` (the currency is a label: nothing converts between currencies), and quantities `MoneyPerMass`, `MoneyPerPower`, `MoneyPerLength`, `MoneyPerConductance`, `MassPerEnergy`, `AnnualEnergy`, `AnnualRate`. `currency/year` is `currency/yr`. |
| 0.2.0, unreleased changes | | `Assumptions`: `co2_price`, `electricity_emission_factor` and every cost factor are a `Quantity` (the price profile `{"unit", "values"}` is a `Quantity` with an array), and a bare number raises. `Constraint` bounds, `Problem.site` values and the `gm.study` variables, limits and distributions are `Quantity` for a field with a unit. `Assumptions.emission_factor()` gives the factor in SI. |
| 0.2.0, unreleased changes | | `Results.units` is `{"<path>.<field>": unit}` for every column of `to_frame`; the former `{path: {field: unit}}` is `Results.declared` (and the constructor argument). New units `MWh`, `GWh`, `TWh`, `MJ`, `GJ`, `GW`, `kt`, `Mt`, `kg/yr`, `t/yr`, `kt/yr`, `Mt/yr`, `kWh/yr`, `MWh/yr`, `GWh/yr`, `kEUR`, `MEUR`, `EUR/J`, `EUR/yr`, `kEUR/yr`, `MEUR/yr`. |
| 0.2.0, unreleased changes | | Outputs: each value of `gm.evaluate`, each check `value` and `limit`, and the results of `gm.study.minimize` and `sample` are a `Value`, a `Quantity` in SI with `reason` and `parts`; `to_plain` gives the JSON of before, with `currency` for money and `yr` for years. `Value` and `measure` are in `gemini/types/shapes.py`. `gm.study.minimize` returns `Value` objects, not JSON. |
| 0.2.0, unreleased changes | | Behaviour users see, no name changed: `gm.analysis.estimate_conductance` requires `cp_hot`, `cp_cold` and `arrangement`; `years_left` returns years (`yr`); on the Python backend `ops.maximum` and `ops.minimum` return NaN for a NaN operand and `ops.floor` and `ops.ceil` return floats, as on NumPy; `ops.brentq` raises the `PhysicsError` of a failed check instead of swallowing it; `gm.call` reports an error raised inside `forward` as itself, not as `invalid_value`; `report()["boiler_heat"]` is a value with no number and a reason where the run has no series of a boiler; the plant dict schema offers a number or a quantity for an input, no unit string. |
| 0.2.0 | 2026-10-31 | Demand profiles: `gm.profiles.get` reads the two organiser files of 2027; `profile_schema` describes what `get` returns. |
| 0.2.0 | 2026-10-31 | No dangling ports: an unconnected port is `unconnected_port`; plant ports exist only when named, the automatic `<path>_<port>` ports are gone. |
| 0.2.0 | 2026-10-31 | A module may set its children's values: every parameter route reaches an overridden `set_params`; `to_dict` stores no derived value. |
| 0.2.0 | 2026-10-31 | `Fluid`: `density` and `viscosity` replace `liquid_density` and `liquid_viscosity`; `gas_liquid_ratio`, `gas_composition`, `kind="gas"`; reservoirs lose both parameters. |
| 0.2.0 | 2026-10-31 | Gas chain: `Boiler` and `CHP` get `fuel_in` and `gas_out`; `ElectricBoiler` replaces `fuel_type="electric"`; `GasGrid`, `GasMakeup`, `Flare`; `gm.economics.co2` sums the emission outputs; `gas_price` and `methane_gwp` replace `fuel_price` and `fuel_emission_factor`; code `missing_assumption`. |
| 0.2.0 | 2026-10-31 | `gm.plants.Doublet`: a doublet designed from its depth; `gm.modules.get("Doublet")` gives that class. |
| 0.2.0 | 2026-10-31 | Two-phase well check: the gas superficial velocity follows the gas mass flow, at the gas density of the section. |
| 0.2.0 | 2026-10-31 | `gm.schedule`; a root inlet field binds to a column named `port.field`. |
| 0.2.0 | 2026-10-31 | `gm.checks.Limits` and `gm.checks.limits`; `Doublet.flow`, `Doublet.brine_cooling`, `HeatConsumer.supply_in_T`, `ProductionReservoir.liquid_flow`, `InjectionWell.wellhead_temperature`, `Output.difference`. |
| 0.2.0 | 2026-10-31 | Costs: `capex(assumptions)` on equipment, cost factors in `Assumptions`, `heat_cost_share`. |
| 0.2.0 | 2026-10-31 | Hackathon example `examples/cases/hackathon.py`. |
| 0.2.0 | 2026-10-31 | Version 0.2.0: a checkpoint written before 0.2.0 raises `old_format`; `gm.plants.migrate` converts its plant file. |
| 0.1.0 | 2026-10-30 | First consistent API. |

Names removed or renamed in the unreleased changes of 0.2.0:

| Name | Replaced by |
| --- | --- |
| `gm.Problem`, `Problem.from_json`, `to_json`, `from_dict`, `to_dict`, `schema`, `apply_site`; `problem.json` | `gm.Case` and the same methods (`apply_site` is internal: a run sets the case on a copy by module class); `case.json` |
| `gm.Constraint(path, min, max, over, when)` | `gm.case.Constraint(on, quantity, min, max, equals, over, when)`: a role and a quantity of it, from `gm.case.roles()`, not a module path |
| `gm.Assumptions(...)`: `prices`, `co2_price`, `electricity_emission_factor`, `methane_gwp`, `discount_rate`, `lifetime_years`, `heat_cost_share`, `currency`, the cost factors `drilling_cost`, `heat_pump_cost`, `boiler_cost`, ... | `gm.case.Assumptions(finance, emissions)`: `finance.opex.*`, `opex.co2`, `emissions.CO2.electricity`, `emissions.CH4.gwp`, `finance.discount_rate`, `lifetime`, `allocation.heat_cost_share`, `finance.currency`, `finance.capex.<kind>`, `finance.opex.fixed.<kind>`; no sourced defaults: the values are stated in the case |
| `Problem.site`, `site` values by parameter path | `case.environment` (ground, reservoir, fluid, air) |
| `gm.optim` | `gm.study`: `minimize`, `sample`, `size`, `sensitivity` |
| `gm.units.parse`, `gm.units.split_quantity`, every unit text such as `"150 m3/h"` | `gm.units.Quantity(150, "m3/h")` or `{"value": 150, "unit": "m3/h"}` |
| `gm.types.Cost`, `total_cost`, `scaled_cost`; `capex(assumptions)` returning a `Cost` | `capex(finance)` and `fixed_opex(finance)` of the mixin `Equipment` returning an amount; `gemini.physics.costs.scaled`; `gm.evaluate.capex` |
| `gm.data.legacy.results_to_frame(results, project)` | `gm.data.legacy.to_frame(results, project)` |
| `Results.units` as `{path: {field: unit}}` | `Results.declared`; `Results.units` is `{"<path>.<field>": unit}` for every column of `to_frame` |
| Plant dict keys and parameters the case holds: `Doublet.gradient`, `surface_temperature`, `permeability`, `thickness`; `Formation.geothermal_gradient`, `surface_temperature`; `HeatingGrid` and `CoolingGrid` `return_temperature` and the required supply temperature | `case.environment.ground`, `reservoir`, `demand.<service>`: refused in a plant dict with `invalid_value` naming the case path |
| `gm.evaluate.constraints` item key `path` | `unit_path`, with `role` and `quantity` |
| `gm.evaluate.compare(plant, problem, results, other)` (a stub) | `gm.evaluate.compare(reports, by)` |
| `gm.plants.example(name)` | a stored plant dict, `gm.Plant.from_json(path)` (`inputs/examples/*/plant.json`, `inputs/doublet_heat/plant.json`), or the class `gm.plants.<Class>(...)` and `plant.missing_parameters()` to see what to `set_params` |
| `gm.study.size(plant, case)` | `gm.study.size(plant, case, backup="peak" or "none")`; the policy has no default |
| `gm.study.sample(plant, case, distributions, metrics, count, seed=0)` | `gm.study.sample(plant, case, metrics, count, seed)`: the distributions are the `uncertainty` of the case, a plant parameter is never drawn, `seed` has no default |
| `gm.study.sensitivity(plant, case, parameters, metrics)` | `gm.study.sensitivity(plant, case, metrics)`: every value the case declares an `uncertainty` for, at its `min` and `max` |
| A `Comparison` value as a `float` in display units | `gm.units.Quantity` in SI: `entry["values"]["lcts"].to("EUR/MWh").value`; `to_frame()` keeps the display units |
| `report.to_dict()` in SI | `report.to_dict(units=None)` in display units (MWh, MW, MEUR, EUR/MWh, kt, m3/h, degC), or `{metric: unit}`; the values inside the report stay SI |
| The plant dict key `pipe_path` of a well, the structural `esp_depth` | the lists `section_length`, `section_inclination`, `section_diameter`, `section_roughness`; `esp_depth` is an ordinary number |
| `example_plant(name)` read by a README or doc snippet | `gm.Plant.from_json(path)`; the test fixture stays in `tests/` |
| `gm.data.synthesize`, `gm.analysis.injectivity`, `calibrate_pump`, `calibrate_corrosion`, `erosion` | none: stubs removed, see refactor-notes |
| `examples/basics/`, `examples/recipes/`, `examples/cases/` | five flat scripts in `examples/` |
| `Module._compute_outputs` | `forward` assigns the outputs |
| `Output.of`, `Outlet.field` | a path: `results["sub.consumer.unmet_demand"]`, `results["sub.pipe.fluid_out.T"]`, `result.children[...]` |
| `Doublet.flow`, `.production_temperature`, `.injection_temperature`; the outputs of `ATESPlant`, `HeatingSubstation`, `CoolingSubstation`, `DoubletHeatPlant`, `BoilerChpPlant`, `ParallelExchangerPlant`, `DistrictEnergyPlant`, `MultiWellPlant`, `DistrictNetwork` | the same path below the plant: `d0.reservoir.liquid_flow`, `sub.consumer.unmet_demand` |
| `HeatingSubstation.building_flow`, `.building_pressure`, same on `CoolingSubstation` | `pump.flow`, `pump.loop_pressure`, with `pump.pressure_rise` |
| `ATESPlant.groundwater_pressure`, `.groundwater_flow` | `storage.groundwater_pressure`, `storage.groundwater_flow`, with `source_valve` and `load_valve` |
| `NodalDoublet.produce`, `.inject` | `Plant.constrain` in the class |
| `to_spec`, `from_spec`, `spec_schema` | `to_dict`, `from_dict`, `schema` |
| `gm.plants.templates`, `from_template` | `gm.plants.names(category=...)`, `gm.plants.get(name)`; a size is a constructor argument |
| `gm.plants.migrate`, `scripts/migrate_plants.py` | none: nothing that remains needs it |
| `Module.to_dict`, `from_dict`, `save`, `load` | on `Plant` only; a single module is stored by wrapping it in a plant |
| `update_params`, `apply_params_at`, `clear_param_overrides` | `set_params` with `valid_from`; attribute assignment for an override |
| `get_parameter`, `get_control`, `get_boundary` | `get(path)` |
| `get_module` | `get_submodule` |
| `boundary[""]["inputs"]`, `boundary[""]["root_inputs"]` | the key `inputs` of the plant dict; `{"return_in": {"T": 293.15}}` is `{"return_in.T": 293.15}` |
| `offer`, `has_input_value`, `add_module`, `extra_repr` | private; assign a control or boundary on its module, `plant.get(path).owner` |
| `offered_outlets`, `start_states`, `trial_outlets`, `calibratable_parameters` | gone |
| `describe`, `parameter_schema`, `validate_params` on a class | on an instance, `gm.modules.ESP().describe()` |
| `docs/schemas/plant_spec.*` | `docs/schemas/plant_dict.*` |
| `gm.challenge_rules` | a `rules` dict of the caller |
| `HackathonPlant` | a plant dict, as `plant_with_treatment.json` of `inputs/examples/hackathon_2026/` |
| `gm.profiles.demand`, `gm.profiles.get`, `gm.profiles.names` | `gm.profiles.from_csv`, `gm.profiles.from_values` |
| `gm.checks.operating_days`, `rules["operating_days"]`, `days` of `run_all` | `gm.checks.operating_time`, `rules["operating_time"]`, `duration` |
| `attrs["outage_days"]` of a plan | `attrs["outages"]` |
| `profile=None` of `gm.study.minimize`, `sample` | the caller's demand and `rules` |
| `gm.plants.from_dict(data)` | `gm.Plant.from_dict(data)` |
| `Plant.save(path)`, `gm.Plant.load(path)` | `Plant.to_json(path)`, `gm.Plant.from_json(path)` |
| `Results.save(path)`, `gm.Results.load(path)` | `Results.to_npz(path)`, `gm.Results.from_npz(path)` |
| `gm.plants.convert_legacy(folder)` | `gm.Plant.from_legacy(folder)`, which returns a plant |
| `Engine.save_checkpoint`, `Engine.load_checkpoint` | `Engine.to_checkpoint`, `Engine.from_checkpoint` |
| `Module.load_state_dict` | `Module.set_state_dict` |
| `gm.runtime.load_state`; `set_precision`, `set_display_units`, `set_default_fluid` and the getters | internal `set_state`; `gm.runtime.settings(...)` and `gm.runtime.state()` |
| `gm.evaluate(module, ...)` | `gm.call(module, ...)` |
| `gm.testing.check_module` | `gm.modules.check` |
| `gm.checks.*`, `gm.economics.*`, `gm.kpi.*` | `gm.evaluate.*`; `gm.kpi.compute` is in `gm.evaluate.totals` |
| `gm.checks.Limits`, `gm.checks.limits`, `gm.checks.operating_time` | `gm.case.Constraint` and `gm.evaluate.constraints` |
| `gm.economics.Assumptions` | `gm.case.Assumptions` |
| `electricity_price`, `gas_price`, `waste_disposal_price`, `chemical_price`, `heat_price`, `cold_price` of `Assumptions` | `assumptions.finance.opex` and `revenue` of the case |
| `rules` of `gm.schedule`, `gm.study.minimize`, `sample`; `order`, `cooling_order`, `operating_time` as a list or a fraction | the `constraints` of the case; `gm.schedule(plant, case)` |
| `gm.schedule(plant, demand, rules)`, `gm.simulate(plant, profile)` | `gm.schedule(plant, case)`, `gm.simulate(plant, case)` |
| `gm.profiles.*` | `gm.data.*` |
| `gm.study.calibrate`, `gm.study.CalibrationResult` | `gm.analysis.calibrate`, `gm.analysis.CalibrationResult` |
| `gm.modules.register`, `gm.modules.load_file` | none: a class that states a `category` registers itself in `Module.__init_subclass__`; `abstract = True` leaves it out; a second class of a name raises `duplicate_name` |
| `gm.modules.<Plant class>` | `gm.plants.<Plant class>` |
| `gm.backends.settings(backend)` | `gm.runtime.settings(backend=...)` |
| `gemini.types.Parameter`, `Control`, `Boundary`, `State`, `Inlet`, `Outlet`, `Output` | `gm.modules.*` |
| `gm.Clock` | `gemini.engine.Clock` |
| `gm.Ports`, `gm.Profile`, `gm.streams` | `gemini.types.Ports`, `Profile`, `streams` |
| `gm.Quantity` | `gm.units.Quantity` |
| `gm.no_outputs` | `gm.modules.no_outputs` |

Before 0.1.0 the API counted integer versions 1 to 5: the first frozen list, `category` as the
folder of a module, `gm.legacy` moved behind `gm.plants.convert_legacy`, the fits moved to
`gm.analysis` with one name per concept ([glossary.md](glossary.md)), and the run functions over
`gm.Engine`. Checkpoints and results files written before 0.1.0 do not load: they raise
`ValidationError` with code `old_format`.
