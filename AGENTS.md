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
(`modules`, `plants`, `physics`, `ops`, `runtime`, `engine`, `run`, `types`, `units`, `errors`,
`_utils`) import none of `compiler`, `data`, `optim`, `evaluate`, `analysis`
([dependencies](.claude/docs/conventions.md#dependencies)).

**Read/write naming.** Every reader is `from_<format>` and every writer `to_<format>`: `from_csv`,
`from_json`, `from_dict`, `from_values`, `from_bytes`, ... and `to_csv`, `to_json`, `to_dict`,
`to_bytes`, .... A reader is a classmethod on the class it returns (`gm.Problem.from_json(path)`); a
writer is a method of the object (`problem.to_json(path)`). Only a reader that returns no gemini
class (a demand frame) is a plain function in its folder (`gm.data.from_csv`). No `read_*`,
`write_*`, `load_*`, `save_*`, `parse_*` or `dump_*` names; `tests/unit/test_code_quality.py` rejects
those prefixes ([conventions](.claude/docs/conventions.md#public-names-and-readwrite-naming)).

Learn the package from [examples/README.md](examples/README.md): quickstart, basics 01 to 06, any
recipe, then the cases. gemini holds no data file: plants are Python classes, and JSON is only the
plant dict agents use (`gm.Plant.from_dict`, `plant.to_dict`, `gm.plants.schema`). Data lives in
`inputs/`, never `examples/`, and is not installed ([data](.claude/docs/data.md#where-data-lives)).

One `gm.Problem(demand, site, constraints, assumptions)` carries what a plant is asked to do, for
every call (`gm.Problem.from_json`, `gm.Constraint`, `gm.Assumptions`). Run a plant with
`gm.simulate(plant, problem)`, `gm.replay`, `gm.live` and `gm.resume`; keep `gm.Engine` for complex
tasks ([functions or engine](.claude/docs/engine.md#functions-or-engine)). `gm.schedule(plant,
problem)` plans the run input of a design from its demand, at any constant step: sources load from
the cheapest to the dearest, limits and outages come from the constraints, and the role of each unit
is read from the wiring ([schedule](.claude/docs/engine.md#schedule)). A demand comes from
`gm.data.from_csv` or `from_values`; gemini ships none. The `gm.evaluate` functions take
`(plant, problem, results)`; `gm.evaluate.totals` and `gm.evaluate.constraints` judge a run.

gemini is a general package and knows no problem: `inputs/examples/` holds sample problems, each a
`problem.json`, a demand CSV, a `plant.json` and a README, and only `examples/` and `tests/` read
them ([conventions](.claude/docs/conventions.md#general-package)). A whole run is:

```python
problem = gm.Problem.from_json("inputs/examples/hackathon_2027/problem.json")
plant = gm.Plant.from_json("inputs/examples/hackathon_2027/plant.json")
results = gm.simulate(plant, problem)
```

Everything in the plant's energy and mass flow is a module, everything that crosses between modules
goes through a port, and a plant total is read from the ports of the modules at the plant's edge
([energy flow](.claude/docs/modules.md#energy-flow)). Check a run with `gm.evaluate.plant_balance(plant, problem, results)`.

Every port of a module is connected or named as a plant port; there are no automatic plant ports
([plants](.claude/docs/plants.md#the-builder)). What a design holds beside its parameters, such as a
setpoint, is set with `plant.set_inputs` and stored in the plant dict under `inputs`. A plant may derive its children's values by
overriding `set_params`
([modules](.claude/docs/modules.md#a-plant-that-sets-its-childrens-values)).

Every public return uses one of three shapes, value, problem or check, built by
`gemini/types/shapes.py` ([return shapes](.claude/docs/api.md#return-shapes)). Every public call
raises by default; `on_error="record"` reports instead ([errors](.claude/docs/errors.md)).

Read every file in `.claude/docs/` before changing the repository:

- [Public API](.claude/docs/api.md): every frozen public name, its return shape and status; start
  here to use the package.
- [Plants](.claude/docs/plants.md): plant classes, the builder, the plant dict, loops, constraints,
  outputs, dates and bindings.
- [Conventions](.claude/docs/conventions.md): dependencies, naming, comments and code quality.
- [Data](.claude/docs/data.md): read/write naming, in-memory datasets, sampling, gaps, `problem.json`
  and where data lives.
- [Engine](.claude/docs/engine.md): clocks, runs, callbacks, results, checkpoints and live.
- [Economics](.claude/docs/economics.md): `gm.evaluate` costs, totals, KPIs, constraints and checks, `gm.optim` and well analysis.
- [Equipment](.claude/docs/equipment.md): every shipped module, its model and energy audit.
- [Errors](.claude/docs/errors.md): the rule for raising, the seven `gm.errors` classes, the codes.
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

Work directly on `refactor`: commit there and push `origin refactor`. Do not create another
branch unless the user explicitly asks for one, and open a pull request only when asked.

## Layout

```text
gemini/
├── __init__.py       # curated import gemini as gm API: gm.__all__ is pinned
├── _utils/           # general helpers and registry.py; leaf, imports nothing else from gemini (but errors)
├── errors/           # the gm.errors classes and codes; leaf package that imports nothing else from gemini
├── ops/              # math API and dispatcher, backend.py (registry, select), kernels/ (python, numpy, scalars, solvers)
├── physics/          # shared formulas: SI correlations; gm.physics.<topic>
├── units/            # unit conversions and Quantity
├── types/            # quantities, streams, fluids, profiles, bindings, costs, return shapes
├── runtime/          # context-local backend, precision, display units and default fluid
├── modules/          # module.py, declarations.py, container.py, call.py, check.py, _utils/; one folder per category with its _physics.py
├── plants/           # plant.py (Plant) and the plant classes, one file each; _utils/ holds the plant tools
├── engine/           # Engine, Clock, executor.py, eager.py, rows.py, loader, runner, chunks, checkpoint, callbacks
├── run/              # Problem, Constraint, Assumptions, schedule, simulate, replay, live, resume, call, Results, Dataset; _utils/ (demand, roles, limits, sources)
├── compiler/         # graph/ (Tracer, Graph, passes, cache), executor.py, gm.compiler.compile; optional, registers itself
├── data/             # from_csv, from_values, profile_schema, synthesize (stub), legacy/ (old CSV files and the way back to the old project)
├── optim/            # minimize, sample, size (stub), sensitivity (stub)
├── evaluate/         # totals, constraints, balances, bounds, run_all, capex, opex, lcoh, lcoc, lcts, annualised_cost, co2, npv, payback; capacities, report, compare (stubs)
└── analysis/         # calibrate, nodal, injectivity, pump curve, corrosion, erosion, fits
docs/schemas/         # generated JSON Schemas and samples of the exchanged documents
inputs/               # not installed: examples/ (sample problems), plants/ (example values), doublet_heat/, legacy_project/
examples/             # quickstart.py, basics/, recipes/, cases/, scripts only
scripts/              # test_changed.py, write_schemas.py
docker/               # sandbox.Dockerfile, the image of a module sandbox (make sandbox-image)
tests/                # unit mirror, integration, e2e (expected/ holds example outputs), fixtures
```

Modules declare parameters and ports in `__init__`; `forward(self, inlets)` receives one
immutable `Ports` mapping (`gemini.types.Ports`) while controls and boundaries are pre-applied and read from `self`. A leaf
assigns its outputs there and returns a dictionary of outlets; the combinations of a plant run
automatically afterward. Pre-hooks receive `(module, inlets)` and forward hooks receive
`(module, inlets, outlets)`. Plants ([plants.md](.claude/docs/plants.md)) own persistence, bindings,
and dated design. `gemini.run` holds the run objects and reads files only for a `Problem` and `Results`. No engine loop sleeps or schedules itself.
Keep the public
API small and examples outside the package. Details are in
[conventions.md](.claude/docs/conventions.md) and [modules.md](.claude/docs/modules.md).
