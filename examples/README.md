# GEMINI examples

Read them in this order: [quickstart.py](quickstart.py), then [basics](basics) 01 to 06, then any
recipe, then the cases.

## Run an example

```bash
python examples/quickstart.py
python examples/recipes/calibrate.py
```

Each file runs alone from any folder, with `gemini` installed (`pip install -e .`); it needs no
`PYTHONPATH`. It finds its data through its own path, in `inputs/`, or through `gm.plants.example`, and writes nothing to
the repository.

## The dataset

The examples that read measurements use the fast dataset, the July 2024 month. Point
`GEMINI_EXAMPLE_DATASET` at another file to change that, for example at the full source:

```bash
GEMINI_EXAMPLE_DATASET=inputs/doublet_heat/doublet_2024_15min.csv python examples/quickstart.py
```

## Quickstart

| File | What it shows | Main names |
| --- | --- | --- |
| [quickstart.py](quickstart.py) | Simulate the doublet heat plant on a month of data | `gm.plants.example`, `gm.Dataset.from_frame`, `gm.simulate`, `Results.summary` |

## Basics

| File | What it shows | Main names |
| --- | --- | --- |
| [01_streams_and_fluids.py](basics/01_streams_and_fluids.py) | Streams, fluids and quantities | `gm.Stream`, `gm.Fluid`, `gm.units` |
| [02_modules.py](basics/02_modules.py) | Call one module and read its outlets, outputs and port quantities | `gm.modules.ESP`, `describe`, `Stream.quantities`, `gm.modules.no_outputs` |
| [03_build_a_plant.py](basics/03_build_a_plant.py) | A plant class and the builder; validate and fix an `unconnected_port` | a `gm.Plant` subclass, `add`, `connect`, `validate` |
| [04_parameters.py](basics/04_parameters.py) | Dated parameters, controls, boundaries and bindings | `set_params`, `params_at`, attribute assignment, `set_bindings` |
| [05_simulate_and_results.py](basics/05_simulate_and_results.py) | Simulate and read the results in your units | `gm.simulate`, `Results`, `units=`, `to_frame` |
| [06_save_and_load.py](basics/06_save_and_load.py) | A plant as a plant dict and as a file | `to_dict`, `gm.Plant.from_dict`, `to_json`, `gm.Plant.from_json` |

## Recipes

One task each, in any order.

| File | What it shows | Main names |
| --- | --- | --- |
| [replay_measurements.py](recipes/replay_measurements.py) | Replay measured data and read the soft sensors | `gm.replay`, `to_frame(table="energy")` |
| [live_update.py](recipes/live_update.py) | Process new rows once each, as a scheduler would | `gm.live` |
| [calibrate.py](recipes/calibrate.py) | Fit the exchanger conductance on seven days | `gm.analysis.calibrate` |
| [schedule_demand.py](recipes/schedule_demand.py) | Plan a year from the heating demand | `gm.data.from_csv`, `gm.Problem`, `gm.schedule` |
| [check_limits.py](recipes/check_limits.py) | Judge a run against your own limits | `gm.Constraint`, `gm.evaluate.constraints` |
| [energy_balance.py](recipes/energy_balance.py) | Check module and plant balances, read the edge totals | `gm.modules.energy_balance`, `gm.evaluate.plant_balance`, `gm.evaluate.totals` |
| [economics.py](recipes/economics.py) | Investment, yearly cost, levelised cost and CO2 | `gm.Assumptions`, `gm.evaluate.capex`, `opex`, `lcoh`, `co2` |
| [write_a_module.py](recipes/write_a_module.py) | Write a module and use it in a plant | `gm.modules.Module`, `gm.modules.check` |
| [sweep_esp_frequency.py](recipes/sweep_esp_frequency.py) | Compare a simulated day at three pump frequencies | `gemini.engine.Clock`, `gemini.types.Profile`, `gm.simulate` |
| [legacy_project.py](recipes/legacy_project.py) | Convert an old project folder | `gm.Plant.from_legacy` |

## Cases

Whole plants. The competition example is the short form of any sample problem:

```python
problem = gm.Problem.from_json("inputs/examples/hackathon_2027/problem.json")
plant = gm.Plant.from_json("inputs/examples/hackathon_2027/plant.json")
results = gm.simulate(plant, problem)
print(gm.evaluate.totals(plant, problem, results), gm.evaluate.constraints(plant, problem, results))
```

A case takes a registered plant with its design values from `gm.plants.example`, or a
sample problem of `inputs/examples/`: a `problem.json` with its demand CSV, and a `plant.json`.

| File | What it shows | Main names |
| --- | --- | --- |
| [parallel_exchangers.py](cases/parallel_exchangers.py) | A nodal-solved doublet on three parallel exchangers | `ParallelExchangerPlant`, `NodalDoublet` |
| [boiler_chp.py](cases/boiler_chp.py) | A nodal-solved doublet with a boiler and a CHP | `BoilerChpPlant`, `NodalDoublet`, `gm.modules.emissions` |
| [district_heating_cooling.py](cases/district_heating_cooling.py) | Heating and cooling networks on an aquifer store, stepped by the hour | `DistrictEnergyPlant`, `Module.step` |
| [hackathon.py](cases/hackathon.py) | A sample problem from schedule to economics | `gm.Problem.from_json`, `gm.Plant.from_json`, `gm.simulate`, `gm.evaluate.totals`, `gm.evaluate.lcoh` |
| [challenge_year.py](cases/challenge_year.py) | The demand year of a sample problem, every requirement checked | `gm.Problem.from_json`, `gm.Plant.from_json`, `gm.evaluate.constraints`, `gm.evaluate.lcts` |
| [shallow_district.py](cases/shallow_district.py) | An hourly demand on one shallow doublet, a different sample problem | `gm.Problem.from_json`, `gm.Plant.from_json`, `gm.simulate`, `gm.evaluate.constraints` |
