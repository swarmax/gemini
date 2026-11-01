# GEMINI Python package

GEMINI is a composable geothermal digital-twin package. Preserve captured numerical behaviour.

## Start here

Test with the development profile (`make test`); see
[Testing: Test profiles](.claude/docs/testing.md#test-profiles).

A leaf module computes and a plant connects; no class does both
([modules](.claude/docs/modules.md), [plants](.claude/docs/plants.md)). A leaf has physics calls and
one method, `forward`. Every composite is a `Plant`: it declares children, ports and connections in
`__init__` and never writes `forward`. The engine closes loops and solves constraints.

Physics lives in `gemini/physics/` or `gemini/modules/<category>/_physics.py`: a module declares and
calls physics functions. `gemini/modules/` holds `Module`, the declarations, `ModuleList`,
`ModuleDict` and `gm.modules.check`; `gemini/plants/` holds `Plant` and the plant classes. Machinery
goes in an `_utils/` folder, code of one category in a private file of its folder
([where a file goes](.claude/docs/conventions.md#module-rules)). Public names are flat,
`gm.<folder>.<Name>`, exported by the folder's `__init__`; inner files are private. The run folders
(`modules`, `plants`, `case`, `physics`, `ops`, `runtime`, `engine`, `run`, `types`, `units`, `errors`,
`_utils`) import none of `compiler`, `data`, `study`, `evaluate`, `analysis`
([dependencies](.claude/docs/conventions.md#dependencies)).

**Read/write naming.** Every reader is `from_<format>` and every writer `to_<format>`: `from_csv`,
`from_json`, `from_dict`, `from_values`, `from_bytes`, ... and `to_csv`, `to_json`, `to_dict`,
`to_bytes`, .... A reader is a classmethod on the class it returns (`gm.Case.from_json(path)`); a
writer is a method of the object (`case.to_json(path)`). Only a reader that returns no gemini
class (a demand frame) is a plain function in its folder (`gm.data.from_csv`). No `read_*`,
`write_*`, `load_*`, `save_*`, `parse_*` or `dump_*` names; `tests/unit/test_code_quality.py` rejects
those prefixes ([conventions](.claude/docs/conventions.md#public-names-and-readwrite-naming)).

Learn the package from [examples/README.md](examples/README.md): five flat scripts, `quickstart.py`
first, then `hackathon.py`. gemini holds no data file: plants are Python classes, and JSON is only the
plant dict agents use (`gm.Plant.from_dict`, `plant.to_dict`, `gm.plants.schema`). Data lives in
`inputs/`, never `examples/`, and is not installed ([data](.claude/docs/data.md#where-data-lives)).

One `gm.Case` carries what a plant is asked to do, for every call: the sections `time`,
`environment`, `demand`, `choices`, `constraints` and `assumptions`, strict and typed, read from a
`case.json` with `gm.Case.from_json` ([case](.claude/docs/data.md#the-case)). A plant dict holds only the
plant. Run a plant with `gm.simulate(plant, case)`, `gm.replay`, `gm.live` and `gm.resume`; keep
`gm.Engine` for complex tasks ([functions or engine](.claude/docs/engine.md#functions-or-engine)).
`gm.schedule(plant, case)` plans the run input of a design from the demand of the case, at any
constant step: sources load from the cheapest to the dearest, limits and outages come from the
constraints, and the role of each unit is read from the wiring
([schedule](.claude/docs/engine.md#schedule)). The `gm.evaluate` functions take
`(plant, case, results)`: `totals`, `constraints`, the costs, `report` and `compare`. `gm.study`
sizes (`size`), searches (`minimize`), samples and ranks the influence of a value (`sensitivity`).

gemini is a general package and knows no sample: `inputs/examples/` holds sample cases, each a
`case.json`, a demand CSV and the plant dicts, and only `examples/` and `tests/` read them
([conventions](.claude/docs/conventions.md#general-package)). A whole run is:

```python
case = gm.Case.from_json("inputs/examples/shallow_district/case.json")
plant = gm.Plant.from_json("inputs/examples/shallow_district/plant.json")
results = gm.simulate(plant, case)
print(gm.evaluate.report(plant, case, results)["heat_delivered"].to("MWh").value)
```

**Standing rules.** They apply to every change, in code, tests and docs.

- *One unit format.* A value with a unit is a `gm.units.Quantity` with a unit of the
  `gm.units.Unit` enum, or its dict `{"value": 150, "unit": "m3/h"}`; a string such as
  `"150 m3/h"` is never accepted, and nothing in the package parses unit text. A dimensionless value
  is a number. Known limit: a bare number with a dimension is still read as SI in `set_params`,
  `gm.call`, `gm.Stream` and `gm.Fluid`, which the engine uses for derived values
  ([units](.claude/docs/conventions.md#units)).
- *No defaults.* Nothing a user must decide has a default value in gemini: not a price, a
  temperature, a limit, a factor or an efficiency. Such a field is required, or absent (`None`),
  and a call that needs an absent value raises `missing_value` (`missing_assumption` below
  `assumptions`) naming its path. The only defaults of `gm.case` are `over="each"` and
  `when="always"` of `Constraint`; `tests/unit/test_code_quality.py` checks this
  ([no defaults](.claude/docs/conventions.md#no-defaults)).
- *The input is a case, never a problem.* The word `problem` is only the return shape of an error;
  `tests/unit/test_code_quality.py` rejects it as a name in `gemini/`.
- *Update the code, never wrap it.* When a refactor changes a name or a shape, every caller is
  changed in the same task, and no wrapper, alias or shim is written
  ([one implementation](.claude/docs/conventions.md#one-implementation-per-concept)).
- `.claude/` holds no separate rules file: this page is the coding rules for Claude.

Everything in the plant's energy and mass flow is a module, everything that crosses between modules
goes through a port, and a plant total is read from the ports of the modules at the plant's edge
([energy flow](.claude/docs/modules.md#energy-flow)). Check a run with `gm.evaluate.plant_balance(plant, case, results)`.

Every port of a module is connected or named as a plant port; there are no automatic plant ports
([plants](.claude/docs/plants.md#the-builder)). What a design holds beside its parameters, such as a
setpoint, is set with `plant.set_inputs` and stored in the plant dict under `inputs`. A plant may derive its children's values by
overriding `set_params`
([modules](.claude/docs/modules.md#a-plant-that-sets-its-childrens-values)).

Every public return uses one of three shapes, value, problem (the shape of an error) or check, built by
`gemini/types/shapes.py` ([return shapes](.claude/docs/api.md#return-shapes)). Every public call
raises by default; `on_error="record"` reports instead ([errors](.claude/docs/errors.md)).

Read every file in `.claude/docs/` before changing the repository:

- [Public API](.claude/docs/api.md): every frozen public name, its return shape and status; start
  here to use the package.
- [Plants](.claude/docs/plants.md): plant classes, the builder, the plant dict, loops, constraints,
  outputs, dates and bindings.
- [Conventions](.claude/docs/conventions.md): dependencies, naming, comments and code quality.
- [Data](.claude/docs/data.md): read/write naming, in-memory datasets, sampling, gaps, `case.json`, the unit format
  and where data lives.
- [Engine](.claude/docs/engine.md): clocks, runs, callbacks, results, checkpoints and live.
- [Economics](.claude/docs/economics.md): `gm.evaluate` costs, totals, KPIs, constraints and checks, `gm.study` and well analysis.
- [Equipment](.claude/docs/equipment.md): every shipped module, its model and energy audit.
- [Errors](.claude/docs/errors.md): the rule for raising, the seven `gm.errors` error classes and `GeminiWarning`, the codes.
- [Glossary](.claude/docs/glossary.md): one name per concept for parameters, outputs and ports.
- [Legacy](.claude/docs/legacy.md): the old-format boundary and conversion rules.
- [Modules](.claude/docs/modules.md): declarations, listings, calls, outputs, hooks and state.
- [Native engine](.claude/docs/native-engine.md): the computation-graph design and its status.
- [Physics](.claude/docs/physics.md): every physics function by file, SI correlations and numerical
  constraints.
- [Refactor notes](.claude/docs/refactor-notes.md): retained numbers and known limitations.
- [Runtime](.claude/docs/runtime.md): context-local process settings.
- [Testing](.claude/docs/testing.md): tiers, test profiles, datasets, budgets, fixtures and CI.
- [Types](.claude/docs/types.md): streams, fluids, declarations, profiles and balances.
- [Utilities](.claude/docs/utils.md): the `gemini._utils` helpers and how to add one.

When a commit changes behaviour, structure or conventions, update the relevant document in the
same commit. The public API is frozen: a breaking change to a public name or return field raises the minor
number of `gm.__version__` ([freeze rule](.claude/docs/conventions.md#public-api-freeze)).

## Branching

- `main` is the stable line (competition delivery, releases). Change it only on the user's
  request.
- `dev` is the development line: commit there and push `origin dev`.
- `feature/<name>`, `fix/<name>` and `docs/<name>` hold one task each, with a short lowercase name
  joined by hyphens (`feature/study-speed`, `fix/budget-tests`). Branch from `dev`, merge back into
  `dev`, then delete the branch locally and on `origin`.
- Temporary worker branches and worktrees of a coordinator session stay local, are never pushed,
  and are removed at the end of the task.
- Never name a branch `dev/...`: git cannot hold both `dev` and `dev/<name>`.
- Open a pull request only when asked.

## Layout

```text
gemini/
├── __init__.py       # curated import gemini as gm API: gm.__all__ is pinned
├── _utils/           # general helpers and registry.py; leaf, imports nothing else from gemini (but errors)
├── errors/           # the gm.errors classes and codes; leaf package that imports nothing else from gemini
├── ops/              # math API and dispatcher, backend.py (registry, select), kernels/ (python, numpy, scalars, solvers)
├── physics/          # shared formulas: SI correlations; gm.physics.<topic>
├── units/            # unit conversions and Quantity
├── types/            # quantities, streams, fluids, profiles, bindings, return shapes
├── runtime/          # context-local backend, precision, display units and default fluid
├── modules/          # module.py, declarations.py, container.py, call.py, check.py, _utils/; one folder per category with its _physics.py
├── plants/           # plant.py (Plant) and the plant classes, one file each; _utils/ holds the plant tools
├── case/             # Case and its sections (time, environment, demand, choices, constraints, assumptions), roles; _utils/ (demand frame, fields, profiles, access)
├── engine/           # Engine, Clock, executor.py, eager.py, rows.py, loader, runner, chunks, checkpoint, callbacks
├── run/              # schedule, simulate, replay, live, resume, call, Results, Dataset; _utils/ (apply: the case on a plant copy, roles, limits, sources)
├── compiler/         # graph/ (Tracer, Graph, passes, cache), executor.py, gm.compiler.compile; optional, registers itself
├── data/             # from_csv, from_values, profile_schema, legacy/ (old CSV files and the way back to the old project)
├── study/            # size, minimize, sample, sensitivity; _utils/ (trial, choices, target)
├── evaluate/         # totals, constraints, balances, bounds, run_all, capex, opex, lcoh, lcoc, lcts, annualised_cost, co2, npv, payback; capacities, report, compare
└── analysis/         # calibrate, nodal, pump curve, corrosion forecast, fits
docs/schemas/         # generated JSON Schemas and samples of the exchanged documents
inputs/               # not installed: examples/ (sample cases), plants/ (example values), doublet_heat/, legacy_project/
examples/             # five flat scripts: quickstart, hackathon, costs, uncertainty, plant
scripts/              # test_changed.py, write_schemas.py
docker/               # sandbox.Dockerfile, the image of a module sandbox (make sandbox-image)
tests/                # unit mirror, integration, e2e (expected/ holds example outputs), fixtures
```

Modules declare parameters and ports in `__init__`; `forward(self, inlets)` receives one
immutable `Ports` mapping (`gemini.types.Ports`) while controls and boundaries are pre-applied and read from `self`. A leaf
assigns its outputs there and returns a dictionary of outlets; the combinations of a plant run
automatically afterward. Pre-hooks receive `(module, inlets)` and forward hooks receive
`(module, inlets, outlets)`. Plants ([plants.md](.claude/docs/plants.md)) own persistence, bindings,
and dated design. `gemini.run` holds the run objects and reads files only for a `Results`. No engine loop sleeps or schedules itself.
Keep the public
API small and examples outside the package. Details are in
[conventions.md](.claude/docs/conventions.md) and [modules.md](.claude/docs/modules.md).
