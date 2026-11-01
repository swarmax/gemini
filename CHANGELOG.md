# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `gm.Case` and the folder `gm.case` replace `gm.Problem`, `gm.Constraint` and `gm.Assumptions`:
  fixed sections in a `case.json`, SI storage, no default for anything a user must decide. Every
  call takes `(plant, case)`, plus `results` when it reads a run. The plant dict holds only the
  plant.
- One unit format: a `Quantity` or `{"value", "unit"}`; unit text is refused and `gm.units.parse`
  is removed.
- `gm.optim` is `gm.study`; `gm.types.Cost` is removed, equipment declares `capex(finance)` and
  `fixed_opex(finance)` for its kind; `examples/` holds five flat scripts.

### Added
- `gm.evaluate.capacities`, `report` and `compare`; `gm.study.size` and `sensitivity`;
  `gm.plants.capabilities`; costs on every equipment kind; the hackathon example from case to
  compared designs.

The full list, with the removed names, is the change log of [api.md](.claude/docs/api.md).

## [0.2.0] - 2026-10-31

The API for the hackathon: see the change log of [api.md](.claude/docs/api.md). Checkpoints written
before 0.2.0 do not load; `gm.plants.migrate` converts a plant file of an older version.

### Changed
- Fluids: `density` and `viscosity` replace `liquid_density` and `liquid_viscosity`; reservoirs read
  their fluid.
- Plants: an unconnected port is an error, and the automatic plant ports are gone.
- Boilers and CHP burn from `fuel_in`; `ElectricBoiler` replaces `Boiler(fuel_type="electric")`.
- Economics: `co2` sums `co2_emission` and `methane_emission`; `gas_price` and `methane_gwp` replace
  `fuel_price` and `fuel_emission_factor`; a missing assumption has the code `missing_assumption`.

### Added
- `gm.data.get` with the demand of 2027; `gm.plants.Doublet`, designed from its depth;
  `GasGrid`, `GasMakeup`, `Flare`, `ElectricBoiler`; `Fluid.gas_liquid_ratio`, `gas_composition` and
  `kind="gas"`; `gm.schedule`; `gm.evaluate.Limits` and `gm.evaluate.limits`; `capex(assumptions)` on
  equipment with sourced cost factors.

### Fixed
- Wells: the two-phase gas superficial velocity follows the gas mass flow.

## [0.1.0] - 2026-10-30

First consistent API: see the change log of [api.md](.claude/docs/api.md). The version restarts at
0.1.0 from one source, `pyproject.toml`, and `gm.API_VERSION` is removed; the integer versions
below are the history before it. Checkpoints and results files written before 0.1.0 do not load.

### Changed
- Runs: `on_error` is `"raise"` by default, on the run functions and on `gm.Engine`.
- Returns: every public return is a value, a problem or a check, built by `gemini.types.shapes`,
  with a JSON Schema each in `docs/schemas/`; a number travels with its unit and `units` maps are
  gone. `Results.energy_report` is a dict and `to_frame(table="energy")` its table.
- Errors: seven public classes; what the others meant is a `code`. Every public call raises by
  default and `on_error="record"` reports instead. `error.problems` carries every problem.
- Parameters and bindings: `add(kind, name=None, params=None)`, flat `set_bindings` and plant files.
- `gm.evaluate` is a namespace of `compute` and `names`; `gm.evaluate.co2` takes `(plant, results)`.

### Added
- `units`, a map from quantity to unit, on every view of `Results`, on `gm.evaluate` and on
  `gm.analysis`.

The package was rebuilt as composable modules with handwritten plants, in-memory data and one
finite engine, and then cleaned up. Old import paths are not retained.

### Added
- Run functions `gm.simulate`, `gm.replay`, `gm.live` and `gm.resume` over the public `gm.Engine`,
  with `checkpoint` and `checkpoint_every` on `simulate` and `replay`. The plant holds its traced
  graphs, so repeated calls on one plant trace it once (`gm.API_VERSION = 5`).
- The public API is frozen at `gm.API_VERSION = 1` ([api.md](.claude/docs/api.md)). New: the plant
  builder `gm.Plant` and the JSON plant spec (format 2, `gm.plants.from_spec`, `validate`,
  `spec_schema`, `migrate`, `from_template`, `example`); `describe`, `parameter_schema`,
  `validate_params`; one registry with categories and stream types; `gm.evaluate`; `gm.analysis`,
  `gm.evaluate`, `gm.evaluate`, `gm.evaluate`, `gm.testing`, `gm.data`; `gm.errors` codes and
  `to_dict`; JSON Schemas and samples in `docs/schemas/`.
- Physics and leaf modules are written with `gemini.ops`, so one source runs on floats, arrays and
  traced graphs, and `Engine.replay` evaluates each twin as one traced call with identical results.
  `gemini.compiler.graph.settings(traced=False)` selects the old tick-by-tick path.
- Composable `Module` equipment with declared parameters, ports, controls, boundaries and
  outputs, the handwritten `Doublet` plant and the example `DoubletHeatPlant`, portable plant
  JSON with dated parameters and bindings, and the `gm.plants.convert_legacy` bridge from old GEMINI projects.
- `Engine.simulate`, `Engine.replay` and `Engine.live` with callbacks, results, checkpoints and
  resume; bounded calibration through replay; quantity declarations, immutable fluids, profiles,
  costs and mass/energy audits. Eight runnable examples under `examples/`.
- Leaf packages `gemini._utils` (shared string, time, hook, mapping, context and file helpers;
  `python -m gemini._utils.collect_env`) and `gemini.errors` (every error class, also deriving
  from the matching built-in exception, as `gm.errors`).
- Development and release test profiles: `make test` runs `scripts/test_changed.py` on what
  changed and what imports it within a 300 s budget, `make test-release` runs every tier on the
  full-year data; CI runs the development profile on feature branches and the release profile
  for `main`.
- Quality gates: `tests/unit/test_code_quality.py` (comments, nesting, function length,
  framework name), flake8 `max-complexity = 10` without ignoring bare `except`, the package
  boundary test and mirror tests for every source file.
- Equipment classes in `gm.modules`, each described in `.claude/docs/equipment.md`:
  - pumps `CentrifugalPump`, `LineShaftPump`, `GasCompressor`;
  - piping `Pipe`, `Valve`, `Splitter`, `Mixer`, `PressurizationTank`;
  - treatment `Desander`, `InhibitorDosing`, `Vent`;
  - heat `HeatPump`, `AbsorptionUnit`, `AdsorptionChiller`, `CHP`, `Cooler`;
  - subsurface `ThermalDecline`, `AquiferStorage`, `BoreholeField`, `DownholeHeatExchanger`;
  - storage `ThermalStorage`, `IceStorage`; control `PIDController`;
  - power `ORC`, `Separator`, `FlashTurbine`, `GridConnection`;
  - demand `HeatConsumer`, `CoolingConsumer`.
- Composite plants in `gm.plants`: `MultiWellPlant`, `HeatingSubstation`, `CoolingSubstation`,
  `DistrictNetwork` (heating or cooling) and `ATESPlant`, with the example
  `examples/cases/district_heating_cooling.py`; `Module.trial_outlets` and
  `Module.start_states` for loops closed within one call.
- Physics modules `compression`, `refrigeration`, `steam` (IAPWS-IF97), `ground` and
  `psychrometrics`.
- `State(kind, default=...)` declarations with `_advance_states(inlets, outlets, dt)`: any module
  steps with `module.step(state, dt, inlets)`, and a composite steps every stateful descendant
  through its own `forward`, without a hand-written step method.
- Energy-balance terms beyond `electricity`, `fuel` and `heat_loss`: `heat_absorbed`,
  `heat_supplied`, `electricity_generated` and the signed stored-heat rate `heat_accumulation`
  (`ENERGY_INPUTS` and `ENERGY_OUTPUTS` in `gemini/modules/balance.py`).
- Quantities `Elevation`, `MassConcentration`, `MoneyRate`, `LinearThermalResistance`,
  `TemperatureGradient`, `Speed`, `Mass`, `SpecificEnthalpy`, `HeatCapacity`,
  `VolumetricHeatCapacity`, `ThermalDiffusivity` and `LinearPower`; units `g/m3`, `mg/l`, `ppm`,
  `currency/s`, `currency/h`, `m.K/W`, `K/m`, `K/km`, `kJ/kg`, `kWh/K`, `MJ/m3/K`, `t` and
  `m3/h/bar^0.5`; the `Fluid` kind `"steam"` and the `STEAM` constant.
- `Degasser.separation_efficiency` (default 0, which keeps the former results).
- Python 3.12, 3.13 and 3.14 support (was 3.11 only). The Test workflow runs its profile on each
  of them with the newest dependencies and on 3.11 and 3.14 with the declared lower bounds
  (`uv pip install --resolution lowest-direct`); free-threaded 3.14t and the 3.15 beta run as
  non-blocking jobs, and a manual run (`workflow_dispatch`) runs the release profile on any
  branch. CI installs with uv; `poetry install` still works.

### Changed
- `gm.API_VERSION = 2`: one classification. A module's `category` is the folder that holds it, the
  class attribute is gone, `heat/` became `exchangers/`, `heating/` and `cooling/`, the wells moved
  to `wells/` and `AquiferStorage` to `storage/`. The old to new names are in the change log of
  [api.md](.claude/docs/api.md).
- `gm.Engine(plant, ...)` owns its plant: `engine.simulate(profile)`, `engine.replay(data)`,
  `engine.live(source)`. `Results` are JSON views and `.npz` files, `to_frame()` has `path.field`
  columns, the old `summary()` is `energy_report()`, and the `parquet` extra is gone. Plant files are
  format 2; `gm.plants.migrate` converts older ones. `Doublet`, `MultiWellPlant`, `DistrictNetwork`
  and `DoubletHeatPlant` are specs, no longer classes.
- The `Module` base class is explicit: modules are built without arguments and configured with
  `update_params`, which returns the module; there is no class registry or `__init__` wrapping;
  the values of one call live in a single `_Call` context record; `fluid` is a validated
  property; plant files and checkpoints import classes only through `class_path`/`import_class`.
- Declaration listings recurse by default and key results by dotted path; `inlets()` and
  `outlets()` list the module's own ports. `health(result, measured)` receives the call's
  `ModuleResult`; `load_state_dict` takes `strict`; `has_input_value` and
  `clear_param_overrides` were added.
- Ports and controls follow one naming rule: `ProductionReservoir.production_rate` (was `m_dot`),
  `DoubletHeatPlant.secondary_in` (was `secondary`, also in `plant.json` and the data columns),
  `Doublet.return_in`/`supply_out` (were `return_stream`/`supply`) and
  `Boiler.temperature_setpoint` (was `setpoint_T`). `MissingMeasurement` became
  `gm.errors.MissingMeasurementError`, and costs are summed by
  `gemini.types.cost.total_cost(plant)` over modules that define `capex()`.
- Physics consists of plain functions with one unit table; `ConstantWater` became
  `FluidProperties`, and `Profile.constant(value, unit=, clock=)` is the only constant form.
- Runtime settings are context-local; ESP efficiency is a fraction; undefined radial
  diagnostics are reported as unavailable.
- `Blowdown` is a bleed split: `feed_in` -> `retained_out`, `blowdown_out` under the
  `blowdown_fraction` control (was a pass-through `inlet` -> `outlet` with a `modelled`
  output). `FlowCoefficient` allows zero, so a closed valve reports it.
- Dependencies are version ranges instead of exact pins: pandas >= 2.2.2, including pandas 3;
  scipy >= 1.13.0; numpy >= 2.0.0; pydantic >= 2.5.0; pytz >= 2020.1 (>= 2023.4 on Python
  3.12+); the `parquet` extra's pyarrow >= 16.0.0. On Python 3.13 and 3.14 the floors rise to
  the first releases with wheels for them (for example numpy >= 2.3.2 on 3.14). Package metadata
  is in the PEP 621 `[project]` table.
- Development tools are PEP 735 dependency groups (`test`, `lint`, `docs` and `dev` with all
  three): pytest 9.2.0, pytest-xdist 3.8, flake8 7.5.0, Flake8-pyproject 1.2.4, black 26.10.1,
  isort 9.0.2, sphinx-rtd-theme 3.1.0 and Sphinx 9.2.0 (9.1.1 on Python 3.12 and 9.0.4 on 3.11,
  the last releases for them).
  Under pandas 3, results have a microsecond time index and `str` text columns, ambiguous local
  times raise `ValueError` instead of pytz's `AmbiguousTimeError`, and CSV decimals parse
  correctly rounded, which moves replays of the example data by up to 1.7e-13 relative (see
  `.claude/docs/refactor-notes.md`).

### Removed
- `plant.simulate(profile)`: use `gm.simulate(plant, profile)`.
- `gm.modules.list/get/create`, the module catalogue and engine registry, `Sequential`,
  `fidelity`, `apply`, `column_units`, `last_result(s)`, `Module.cost`, keyword-value
  construction, `runtime.dtype` and `runtime.manual_seed`, `gemini.design`, `gemini.agentic`, the
  legacy `nodes=` options and `plant.legacy_info`, `Results.save_csv/save_parquet`,
  `Dataset.frame/describe/reopen`, `Progress`, `AlarmCollector` and `Output(optional=)`.
- `BoosterPump` (a pass-through placeholder with `modelled=False`); use `CentrifugalPump`.
- The Flask interface, application/UI workflows, container stack, platform launcher scripts and
  UI-only dependencies.

### Fixed
- Engine: resume gives the same results as an uninterrupted run; daily clocks follow local
  midnight across DST; offset timestamps load across DST switches; the event log no longer turns
  NaN into errors and always removes its hooks; live runs anchor their grid at the committed
  position, reuse the checkpointed step for single rows and keep the caller's plant and error
  policy; NumPy integer durations are seconds; text time axes are accepted.
- Modules: redefining a module class or reusing a built-in class name no longer fails; assigned
  fluids are kept; slicing a `ModuleList` no longer re-paths its children; `UNSET` keeps its
  identity under copy and pickling.
- Physics: differences convert without unit offsets; the Beggs–Brill map covers its exact
  regime boundaries; two-phase reverse flow uses mirrored friction; zero flow, zero CO2, NaN and
  out-of-range inputs raise `PhysicsRangeError` instead of crashing; `Stream(flow="10")` raises
  `UnitError`.
- Legacy: conversion reads the in-memory project; `write_csv` writes midnight timestamps;
  calibration tolerates a NaN duty row; the t/h ESP head guess is correct; `check_wiring` works
  on a copy; `barg` converts from SI correctly; an ambiguous data CSV and unknown runtime keys
  raise explicit errors; mixed timestamp spellings parse.
- Data: replay, simulation and clocks work with timestamp indexes of any resolution (s, ms, us,
  ns). Under pandas 3, which parses text times as microseconds, the loader compared them with
  nanosecond tick values, so every tick looked like a gap and replay silently skipped every twin;
  `native_step` and clock durations were also 1000 times too short.
- Clocks: daily `Clock.days`/`Clock.year` steps follow local midnight across DST under pandas 3,
  which reads a `Timedelta` frequency as a fixed 24 hours.

## [1.0.3] - 2026-10-13
### Added
- parameters and tag names of the original doublet example using CSV data
### Fixed
- fix influxdb writing data float

## [1.0.2] - 2026-10-12
### Fixed
- fix grafana reverse-proxy authentication inside iframe

## [1.0.1] - 2026-08-20
### Fixed
- add python-dotenv package to pyproject.toml
### Changed
- more info for setting up environment variables in documentation
- change naming environment variables of OLLAMA and CHROMADB


## [1.0.0] - 2026-07-19

### Added
- Initial open-source release of the GEMINI Geothermal Suite.
- Initial release of the GEMINI Geothermal Model.
- Initial release of the GEMINI Geothermal Framework.
- Initial release of the GEMINI Geothermal Application.
  - Diagram Builder Application
  - ESP Monitoring Application
  - Productivity Application
  - Injectivity Application
  - Well Schematic Application
  - Well Integrity Monitoring Application
  - Time-series Visualization Application
  - Report Generation Application
  - Chatbot Application
- Initial release of the GEMINI Geothermal Interface.
