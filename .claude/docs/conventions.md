# Implementation conventions

Write for Python 3.11, the oldest supported version (3.11 to 3.14), and use Black, isort,
100-character lines and Flake8 with docstrings. Preserve captured numbers. Use SI internally: K, Pa,
kg/s, m, W, J and s. Record an intentional physical or numerical decision as a `NOTE(refactor):`
sentence in the docstring of the function, class or test that makes it, with its explanation and
regression evidence, and list lasting decisions in [refactor-notes.md](refactor-notes.md).

## General package

gemini is a general geothermal heating and cooling package: a sample case is only a test, never
the basis of an implementation, a default, a name or a structure, and nothing in `gemini/` knows one.
gemini's shapes are the best general form and inputs adapt to them, in the sample folder or a short
loader in `examples/`, never the other way round.

## Dependencies

A package may import only the packages to its left:

`gemini._utils`, `gemini.errors` ← `gemini.ops.kernels` ← `gemini.ops` ← `gemini.physics`
← `gemini.units`, `gemini.types` ← `gemini.runtime` ← `gemini.modules` ← `gemini.plants`
← `gemini.case` ← `gemini.run` ⇄ `gemini.engine` ← `gemini.compiler`, `gemini.data`, `gemini.study`,
`gemini.evaluate`, `gemini.analysis` ← `gemini/__init__`.

The **run folders** are `modules`, `plants`, `case`, `physics`, `ops`, `runtime`, `engine`, `run`, `types`,
`units`, `errors` and `_utils`. They import none of `compiler`, `data`, `study`, `evaluate` and
`analysis`, not even inside a function, and `modules` imports neither `plants` nor `run`.
Two imports below the rule stay inside a function, neither of them across these layers:

- `Stream.__init__` in `gemini.types.flows` imports `gemini.runtime` to read the default fluid,
  because a module-level import would form a cycle through `gemini.types.fluid`.
- `gemini.physics.hydraulics` imports `Stream` and `Fluid` for type checking only.

`engine` imports `run` for `Results` and `Dataset`, and `run` imports `engine.engine`.
`gemini/engine/__init__.py` imports `gemini.run` first and never `.engine`, which keeps one import
order from either side. `gemini/compiler/__init__.py` registers its executor when it is imported,
and `gemini/__init__.py` imports it; the run works without it, see
[engine.md](engine.md#folders-and-imports). `gemini/case/_utils/demand.py` holds the demand frame,
because a `Case` reads it and `case` imports no `data`; `gm.data` exports `from_csv` and
`from_values` from it. `gemini.case` sits above `plants`, because it finds the units of a role by
module class, and below `run`: it imports none of `run`, `engine`, `evaluate`, `study`, `compiler`,
`data` and `analysis` (`tests/unit/test_code_quality.py` enforces it).

`gemini/runtime/context.py` and `gemini/run/` sit in a package lower in the order than their own
place. They stay safe because neither `gemini/ops/kernels/__init__.py` nor
`gemini/_utils/__init__.py` imports them, so importing the lower package never loads them.

`gemini.ops.kernels` and `gemini.ops` sit below the physics because physics is written with the
ops; `gemini.compiler.graph` sits above `gemini.modules` because its tracer runs module calls (see
[native-engine.md](native-engine.md)).

`gemini._utils` (its topic files, not `data/` and `legacy/`) and `gemini.errors` are leaf packages:
they import only the standard library, installed dependencies and themselves, never another part
of `gemini` (`tests/unit/test_package_boundaries.py` enforces this). One topic file differs:
`gemini/_utils/paths.py` imports `gemini.errors`, the other leaf, because a missing `inputs/` folder
raises `inputs_missing` wherever it is needed.
`tests/unit/test_code_quality.py` enforces the run-folder rule and the rule on `modules`
([testing.md](testing.md#structure-and-quality-tests)).

Packages outside `gemini/plants/_utils/legacy/` and `gemini.data.legacy` never interpret old
project names, tags, tables or node mappings. The reader that builds a plant is in the first, the
CSV files and the way back to the old project in the second; both are internal, and the one public
entry is
`gm.Plant.from_legacy(folder)`.
Equipment performs no file or database access. Calibration predicts only through public replay.
A leaf module computes and a plant connects; no class does both. A leaf `Module` has physics calls
and `forward`. Every composite is a `Plant`, a class that declares children, ports and connections
and never writes `forward`, or `gm.Plant(name)` with `add` and `connect`. gemini keeps no JSON file:
the plant dict (`to_dict`, `gm.Plant.from_dict`) is the interface agents use.

## Public names and read/write naming

A folder exports its public names flat from its `__init__`: `gm.<folder>.<Name>`. Inner files are
private and no caller imports from them. There is no `core`, `base`, `registry`, `testing`,
`backends`, `checks`, `economics`, `profiles`, `utils` or `graph` folder at the top of `gemini/`.

**Read/write naming.** Every reader is `from_<format>` and every writer `to_<format>`: `from_csv`,
`from_json`, `from_dict`, `from_values`, `from_bytes`, ... and `to_csv`, `to_json`, `to_dict`,
`to_bytes`, .... A reader is a classmethod on the class it returns (`gm.Case.from_json(path)`); a
writer is a method of the object (`case.to_json(path)`). Only a reader that returns no gemini
class, such as a demand frame, is a plain function in its folder (`gm.data.from_csv`). No `read_*`,
`write_*`, `load_*`, `save_*`, `parse_*` or `dump_*` name exists, public or private;
`tests/unit/test_code_quality.py` rejects those prefixes.

## Units

**One unit format.** A value with a unit is a `gm.units.Quantity(value, unit)` whose unit is a member
of the `gm.units.Unit` enum (generated from the unit table, so `Unit.M3_PER_H == "m3/h"`), or its
dict `{"value": 150, "unit": "m3/h"}`. Text such as `"150 m3/h"` is never accepted: it raises
`invalid_value` showing the dict form, and a unit of another dimension raises `invalid_unit`
listing the units of the field. No code parses unit text (`units.parse` is gone;
`tests/unit/test_unit_boundary.py` finds any string of the package that is a number followed by a
unit). A dimensionless value (an efficiency, a share, a count) is a number. Inside the code a
value is SI.

Known limit: the boundary refuses bare numbers with a dimension in the case, the plant dict
(`params`, `inputs`), the bounds of `gm.study` and `Value`s; but `set_params`, `gm.call`,
`gm.Stream` and `gm.Fluid` still take a bare number as SI, because the engine and the plants pass
derived SI floats through them. Do not write a bare number with a dimension in new user-facing
input.

## No defaults

Nothing that a user must decide has a default in gemini: not a price, a temperature, a limit, a
cost factor, an efficiency, a depth. A field is required or absent (`None`), and a call that needs
an absent value raises `ValidationError` (`missing_value`, or `missing_assumption` below
`assumptions` of the case) naming its path in the case or the plant. The only defaults in `gm.case`
are `over="each"` and `when="always"` of `Constraint`, the signature the case gives;
`test_the_case_has_no_default_but_absent` in `tests/unit/test_code_quality.py` allows exactly these
two. A default that is a physical constant or a cited model constant (the Carnot fraction of a
heat pump, with its source) is a parameter of its module, not a user decision.

## Signatures

Every function that runs, judges or studies a design takes `(plant, case)` first, and `results`
after them when it reads a run: `gm.schedule(plant, case)`, `gm.simulate(plant, case=None,
plan=None, ...)`, `gm.evaluate.<name>(plant, case, results, ...)` (`capex(plant, case)` has no
results), `gm.study.<name>(plant, case, ...)`. The plant dict holds only the plant; everything that
does not describe the plant is in the case ([data.md](data.md#the-case)).

## Public API freeze

The public API is frozen: [api.md](api.md) lists it. `gm.__version__` is the one version, read from
`version` in `pyproject.toml`. Below 1.0 a breaking change to a public name or a return field raises
the minor number (`0.2.0`) and an addition or a fix raises the patch number (`0.1.1`), in the same
commit, with a line in the change log of [api.md](api.md). `tests/unit/test_public_api.py` compares
against the stored snapshot `tests/fixtures/public_api.json`, which records the version and may only
change together with it: regenerate it with `tests/fixtures/capture_public_api.py` and add its hash
to `SNAPSHOTS` for the new version; never edit the hash of a released version.

## Module rules

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

**Where a file goes under `gemini/modules/`.** There are four homes:

- A file that defines a core class users subclass or build goes directly in `gemini/modules/`:
  `module.py` (`Module`), `declarations.py` (`Parameter`, `Inlet`, `Outlet`, `Output`, `Control`,
  `Boundary`, `State`), `container.py` (`ModuleList`, `ModuleDict`), `call.py` (`gm.call`) and `check.py`
  (`gm.modules.check`). `Plant` is `gemini/plants/plant.py`.
- Machinery goes in an `_utils/` folder, even if some of its functions are exported publicly:
  `gemini/modules/_utils/` (`balance`, `description`, `design`, `serialization`, `wiring`),
  `gemini/plants/_utils/` for the plant tools and `gemini/_utils/registry.py` for the registry.
- Code shared by the modules of one category goes in that category folder as a private file:
  `heating/_burner.py`, `cooling/_sorption.py`.
- `gemini/plants/` holds only plant classes.

`tests/unit/test_code_quality.py` checks the first and the last. A class in `_utils` belongs to no
category, and the public names stay in `gm.modules`. Fitting and calibration belong in `gm.analysis`
or `gm.study`, not in modules; a plant class belongs in `gemini/plants/`, never in `modules`.

1. Assign declarations and children only in `__init__`, after `super().__init__()`.
2. Constructor sections are `# Parameters`, `# Inlets`, `# Controls`, `# Boundaries`, `# States`,
   `# Outputs`, `# Outlets` for a leaf and `# Modules`, `# Parameters`, `# Inlets`, `# Boundaries`,
   `# Outlets`, `# Connections`, `# Constraints`, `# Outputs` for a plant, in that order, with empty
   sections omitted. The `__init__` of a plant class has no length limit. Stateful equipment declares `State(kind, default=...)` values and implements
   `_advance_states(self, inlets, outlets, dt)`; see [modules.md](modules.md#state-and-health).
3. Controls are settable commands; boundaries are uncontrollable external conditions.
4. `forward` is exactly `forward(self, inlets)` and reads declared streams through the immutable
   `Ports` mapping (`gemini.types.Ports`), such as `inlets.fluid_in`. Controls and boundaries are applied before the call
   and read as plain attributes such as `self.frequency`.
5. `forward` sections are `# Outlets` and `# Outputs`, in that order with empty sections omitted;
   `forward` assigns on `self` only its declared outputs, and computes each thing once. No subclass
   of `Plant` defines `forward`, and no `Module` but a `Plant` or a group holds children.
6. A plant's own outputs are `Output.difference`, `Output.ratio` and `Output.sum` of paths; a parent
   never sums its children, a total is read from the ports of the modules at the plant's edge.
7. End every `forward` with `outlets = dict(...)`, the outlets in declaration order and then the
   drawn inlets, then `return outlets`.
   Zero- and one-outlet modules use the same dictionary shape.
8. Do not construct `ModuleResult` in module code; `Module.__call__` creates it.
9. Keep value arguments out of `__init__`; structural tree-shape arguments are the exception.
   Build a configured module with `ESP().set_params("", {...})`.
10. Never declare metadata or lists that `Module` derives.
11. Inlets and outlets carry a `Stream` or a `Power`: see [ports](modules.md#ports). A single
    `Power` inlet is drawn: the module computes it in `forward` and returns it under the port's
    name.
12. Pre-hooks are exactly `(module, inlets)` and forward hooks are exactly
    `(module, inlets, outlets)`.

Use dotted module paths consistently. Binding groups are `controls`, `boundaries`, `inlets`,
`measured` and `state`. Reject unknown ports and parameters. In replay a missing observation
skips only its measured twin; in simulation it skips the step. Never disguise a thermal-only
audit as full first-law closure or tune against a holdout merely to meet a threshold.

Examples live in `examples/`, five flat scripts: `quickstart.py`, `hackathon.py`, `costs.py`,
`uncertainty.py` and `plant.py` ([README](../../examples/README.md)). An example is a script for a new reader: a module docstring
that says what it shows, the names it uses and how to run it, then constants, small functions and
`main()` under the `__main__` guard. It runs alone from any folder, with paths from `__file__`;
it uses the public API (`gemini`, and `gemini.types` for the declarations of a new module); values
are quantities, prints are labelled in MW, kW, °C, bar and m³/h, and an assumption that is not
source data is printed as one. An example stays within about 150 lines: plant building beyond that
belongs in gemini, as a registered plant. `GEMINI_EXAMPLE_DATASET` is the one way to change the
dataset, the fast month by default. `tests/unit/test_code_quality.py` checks what can be checked.
Generated output goes under ignored `runs/`.

## Data files

There is no data file inside `gemini/`: a plant is a class. `inputs/` holds everything code reads, is
not installed, and raises `inputs_missing` when absent. `docs/schemas/` is generated documentation.
There is no other home for data ([data.md](data.md#where-data-lives)). `gemini/_utils/paths.py` is the
only code that builds a path to `inputs/`, except an example, which finds it from `__file__` because
it uses the public API alone. `tests/unit/test_code_quality.py` checks these rules.

## Naming

Every port name is `<role>_in` or `<role>_out`. A module with one circuit uses `fluid_in` and
`fluid_out`. Splitter and mixer branches are `branch1_out`, `branch2_out` and `branch1_in`,
`branch2_in`, with `fluid_in` or `fluid_out` for the common side. The roles are:

| Group | Roles |
| --- | --- |
| Two sides of an exchanger or a machine | `hot`, `cold`, `source`, `sink`, `generator`, `chilled`, `cooling` |
| Storage and circuits | `charge`, `discharge`, `supply`, `return`, `production`, `injection` |
| Carriers | `gas`, `liquid`, `fuel`, `grid`, `excess`, `flue`, `power`, `heat`, `loss`, `air`, `wet_air`, `waste`, `chemical` |
| Wells and rock | `wellhead`, `bottom`, `sandface` |
| One circuit and branches | `fluid`, `branch<N>` |

Add a role only when no existing one fits, here and in [glossary.md](glossary.md).
`test_every_port_follows_the_naming_rule` in `tests/unit/test_code_quality.py` checks every port of
every registered module against the rule and this list. A port's label says what may be connected:
`Inlet(Stream, kind="hot_water")`, one of `gm.types.streams.names()`; `kind` means only this label, and the
first argument of every declaration is its `type`.

Outputs derived from a port field are named `<port>_<field>`, for example `hot_out_T`. Controls
and boundaries name the commanded quantity in full words (`frequency`, `production_rate`);
setpoints are `<quantity>_setpoint` (`pressure_setpoint`, `temperature_setpoint`). The `Stream`
field symbols `m_dot`, `T` and `p` are reserved for `Stream` fields and binding field keys.

[glossary.md](glossary.md) holds the one name of each concept. Elsewhere use full words, not
abbreviations. Booleans read as questions (`is_leaf`,
`is_initialized`). Add an SI unit suffix only where the type does not carry the
unit, for example the summary column `energy_J` or the constant `TEST_BUDGET_S`; declared
quantities carry their unit and never repeat it in the name.

Never name the framework the module design resembles, in code, docstrings, examples or
documents; describe the concept itself. `test_no_framework_names_in_tracked_text_files` in
`tests/unit/test_code_quality.py` fails on any occurrence in a tracked file.

## Comments

The only comments allowed in code are:

- the fixed section headers: in `__init__` `# Modules`, `# Parameters`, `# Inlets`,
  `# Controls`, `# Boundaries`, `# States`, `# Outputs`, `# Outlets`, `# Connections` and
  `# Constraints`; in `forward` `# Outlets` and `# Outputs`;
- tool directives with a specific code: `# noqa: <code>`, `# type: ignore[<code>]` and
  `# pragma: no cover`.

Everything worth explaining (why, units, sources, non-obvious physics or numerics) goes into
docstrings. Intentional physical or numerical decisions are a `NOTE(refactor):` sentence in the
docstring, never a comment. `test_only_section_headers_and_tool_directives_are_comments` in
`tests/unit/test_code_quality.py` checks every Python file in `gemini/`, `examples/`, `tests/` and
`scripts/`.

## Code quality

- Flat code: nest at most three blocks deep (an `elif` chain counts once), prefer guard clauses
  and write no `else` after `return` or `raise`.
- Small functions: about 40 lines of body and one job each. The documented exceptions, each with
  its reason, are listed in `LONG_FUNCTIONS` in `tests/unit/test_code_quality.py`.
- McCabe complexity at most 10 (`max-complexity = 10` in the `[tool.flake8]` section of
  `pyproject.toml`).
- Just enough code: no dead code, unused options or parameters, speculative generality or golfed
  one-liners.
- Clear names, as in [Naming](#naming).
- Explicit errors: raise a `gm.errors` class (see [errors.md](errors.md)), never a bare
  `except`, and no silent fallback that hides a failure.
- A bug gets a failing test first; the fix makes it pass.

A module holds no `*`, `/`, `**`, numeric literal other than 0 and 1, `math.*`, NumPy maths or
`ops.exp`-style call: `test_modules_hold_no_formulas` scans `gemini/modules/` except `plants/`, with
the exceptions and their reasons in `FORMULA_EXCEPTIONS`. Bookkeeping of like quantities (`inlet.p -
drop`, `m_1 + m_2`) stays in a module; a default value is a named physics constant.
`test_no_two_physics_functions_share_a_body` compares the normalised bodies of the physics functions,
so a copy with renamed arguments fails; a body of one operator on two names is a definition and is
not compared, and different relations of one form are listed in `SAME_FORM`.
`tests/unit/modules/test_glossary.py` checks every name against [glossary.md](glossary.md).

Enforcement: `tests/unit/test_code_quality.py` checks nesting
(`test_functions_nest_at_most_three_blocks`), function length
(`test_functions_are_short_or_documented_exceptions`), `else` after an early exit
(`test_no_else_after_an_early_exit`), builtin raises (`test_package_code_raises_gemini_errors`),
comments and framework names. Flake8
(`make lint` and the Lint workflow) checks complexity (C901), bare `except` (E722), unused imports
and variables (F401, F841) and docstrings. The remaining points (just enough code, names and
test-first bug fixes) are checked in review.

## One implementation per concept

- No concept has two implementations; the only thing that differs is the backend. A rule, a
  formula, a check, a message or a result structure is written once, with `gemini.ops`, and every
  caller runs that source.
- Behaviour is identical on every backend: values, error class and message, skips, `Results`
  structure with children, output types, callbacks and health, bit-identical on the Python path and
  within `1e-12` on NumPy.
- A direct call (`esp(fluid_in=...)`, `pumps.head(...)`) is **eager**: the same `forward`, the same
  ops, no graph, on the Python backend. It is not a second implementation. The eager scope below
  makes plain operators safe in it; a function never has a "checked" and an "unchecked" version.
- Physics code uses plain operators (`/`, `**`, `-`) where the Python and NumPy results agree. A
  public function of `physics` carries `@ops.physics`; a module method that a user can call
  directly with raw operators carries it too. Do not add `Failed` handling anywhere in physics or
  modules.

## Implicit mechanisms

The package avoids hidden behaviour. These are the only implicit mechanisms left, each with the
reason it is needed:

- `Module.__setattr__` registers what `__init__` assigns: a `Parameter`, `Inlet`, `Control`,
  `Boundary`, `State`, `Output` or `Outlet` goes to its ordered registry and a `Module` becomes a
  child with a dotted path. Assigning to a declared name sets the parameter, persists the control or
  boundary (inside a running call, it changes that call only) or records the output of the running
  call. Constructors therefore read as plain assignments in section order, and `esp.frequency = 50`
  persists a command.
- `Module.__getattr__` resolves names that are not ordinary attributes: parameter values, the
  current control and boundary values (running call, then persisted value, then default),
  outputs recorded in the running call, state values at the start of the running step (the
  initial states outside a step), and otherwise the port and output declarations. This lets
  `forward` read `self.thermal_conductance` or `self.frequency` as plain values.
- The values of one call live in one `_Call` record held in the `_current_call` context variable
  of `gemini/modules/module.py`. Modules keep no per-call state on `self`, so nested,
  re-entrant and concurrent calls stay separate and the combinations of a plant can read the results
  of their children's calls. During `Module.step` each call record also points to the one `_Step`
  record (time step and state trees), so a composite steps its stateful descendants through its
  ordinary `forward` instead of a second, hand-written step method.
- `gm.modules.no_outputs()` and `gm.runtime.settings()` are context settings built on
  `gemini._utils.context.ContextSetting`: a context variable change usable as a `with` block and
  as a decorator, restored on exit.
- `Module.category` is `_FolderCategory` in `gemini/modules/module.py`, a descriptor that reads
  the folder from the import path of the class, so the folder is the one source of a module's
  category; a class in `gemini/plants/` reads `plants`. A class from outside assigns `category`
  itself, which replaces the descriptor.
- `Module.__init_subclass__` registers every class that has a category under its class name
  (`gemini/_utils/registry.py`); `abstract = True` in its own body leaves it out, and a second class
  of a registered name raises `duplicate_name`. There is no `register` call and no file loader.
- `class_path`/`import_class` in `gemini/modules/module.py` are the only import-by-string.
  Only checkpoints use them: a checkpoint names the plant class whose `from_dict` rebuilds the tree
  from the plant dict it stores. A plant dict names registry types.
- A plant child that sits in a cycle of composites but not of leaves is *opened*: the parent's
  `forward` calls its children directly, in the order the connections give (see
  [native-engine.md](native-engine.md), section 14). The call order is never configured by hand.
- A child assigned on a `Plant` is noted as `add` notes it, and `Plant.fluid` passes the fluid to
  every module below it.
- Attribute access on mappings: `Ports` and `Values` derive from
  `gemini._utils.mappings.AttributeMapping`, so `result.outlets.fluid_out` equals
  `result.outlets["fluid_out"]`, and `Results[path].field` returns a pandas Series through
  `ModuleSeries.__getattr__`.
- `Plant.forward` runs a module with an `offered` outlet twice in one step: its offer first, which
  no call records, then its call. A module whose outlet is offered only as it is set says so in
  `_offers`, and the plan follows. The modules of a loop or a constraint run in trial calls, which
  no running call records, then once for the record (`Module._trial`). A drawn inlet takes its value from what `forward` returns,
  so `ModuleResult.inlets` shows what was drawn. Both are needed because the value on a connection
  can travel against the energy ([ports](modules.md#ports)).
- Two optional method protocols: a module that is equipment (the mixin `Equipment` of
  `gemini/modules/_utils/cost.py`) sets `equipment_kind`, one of the kinds of `gm.case.Capex`, and
  defines `capex(finance)`, an amount in the currency of the case from its own design values and the
  factor of its kind; `fixed_opex(finance)` is the share of the kind times that capex
  ([economics.md](economics.md#costs)). A module that overrides `health(result, measured)` gets a
  diagnostic, which the engine calls after each replayed twin (the base method returns `None`,
  meaning not assessed).

- Operator overloading on `gemini.ops.Operators`: a `Constant` (`physics/constants.py`)
  and a traced `gemini.compiler.graph.Proxy` route `+`, `*`, `<`, ... through `gemini.ops.dispatch`, so
  one physics source runs on floats, arrays and traced values. A constant acts as its float on
  concrete values and becomes a named graph input in a trace. The math functions (`ops.log`,
  `ops.sqrt`, `ops.maximum`, ...) and `ops.truediv`/`ops.pow` never raise or warn on an operand
  that is invalid in the branch a `where` does not select: they return `inf` or `nan` as NumPy
  does. `where` branches are plain values, never callables; `None` is allowed as a branch.
  For speed the op functions evaluate plain scalars (`float`, `int`, `bool`, `None`, NumPy
  `float64`/`bool_`) directly on the Python backend and a `Constant` computes its operators on its
  value without `dispatch`; arrays, other NumPy scalars, traced values and an active
  `gm.runtime.settings(backend=...)` take the full `dispatch` path. A `Constant` is not a `float`.
- The eager scope (`gemini/ops/scope.py`, `gemini/ops/failed.py`), entered by `@ops.physics` and
  by `Module._run`, is what makes a direct call behave like the graph. The outermost entry enters
  `np.errstate(all="ignore")` and gives plain Python numbers to the function as NumPy scalars (an exact
  `float` as `np.float64`, an exact `int` as `np.int64`; a module call wraps its parameters, on
  first read, its controls, states and inlet fields), so `/` by zero, an invalid `**` and an overflow give `inf` or `nan` silently, as
  on arrays. Leaving the outermost scope converts scalars back to `float` and `int`, `np.bool_` to `bool`,
  recursively, so results, outputs and outlet streams never hold NumPy scalars. Recorded outputs
  read back inside a call are wrapped too; results of child calls stay plain floats, so a
  composite that divides child values uses `ops.truediv`. Arrays or traced values among the
  arguments leave the scope unwrapped. `Module._scalar_mode()` (`WRAP` by default) lets a module
  ask for `PLAIN`: the ESP does under `precision="float32"`, the one module that honours it,
  because an `np.float64` scalar would promote the float32 coefficients; its
  `pumps.esp_efficiency` keeps `ops.truediv` for that reason. A nested scope costs a
  context-variable read.
  A failing `ops.check` on concrete scalars raises the real error marked as coming from a check;
  `@ops.physics` returns it as a `Failed` value at the function boundary, so
  `where(stopped, 0.0, checked_function(x))` drops the error of the unselected branch and keeps the
  selected one, like the graph's error codes. A `Failed` carries through every op, raises when used
  as a number (`bool`, `float`, `int`, `format`, a `Stream`, a `Declaration`) and raises its error
  when it leaves the outermost scope. A failing `check` on an eager array raises at once, for the
  first failing row; tests compare arrays through `gemini.compiler.graph.run_function`. In a trace the graph
  does the same: a check recorded in a physics function guards that function's traced results (all
  of them, through an `identity` node for a passed-through argument) and reaches an outer function
  through data, and a check outside any physics function (inline in `forward`) guards every graph
  output, as it raises at once when eager. Never put the `repr`
  of a physical value in a message (it reads `np.float64(1.0)`) and use `ops.round`, not `round`.
- A module holds its `GraphCache` in `_graph_cache` (`None` until `gemini.compiler.graph.graph_cache` first
  asks for it), so traced graphs outlive an engine and a run function does not trace the plant
  again. It sits on the module because a graph refers to its module, so a cache outside would keep
  the module alive; a copied or pickled module starts with an empty cache
  (`GraphCache.__reduce__`).
- During a trace the `_Call` record carries the traced parameter values, which
  `Module.__getattr__` returns instead of the stored values, and records outputs without
  validating them (`gemini/compiler/graph/tracer.py`).

Adding another implicit mechanism needs a reason of the same weight and an entry here.
