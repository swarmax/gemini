# GEMINI geothermal suite

Composable geothermal equipment, plants built from data, in-memory data, and one finite engine for
simulation, historical replay, and externally scheduled live updates.

## Quickstart

The short form, on a sample problem of the repository:

```python
import gemini as gm

problem = gm.Problem.from_json("inputs/examples/hackathon_2027/problem.json")
plant = gm.Plant.from_json("inputs/examples/hackathon_2027/plant.json")
results = gm.simulate(plant, problem)
print(gm.evaluate.totals(plant, problem, results), gm.evaluate.constraints(plant, problem, results))
```

A `gm.Problem` holds the demand, the site, the constraints and the assumptions of a run; for
measured inputs, `gm.simulate(plant, plan=frame)` runs a DataFrame or `gm.Dataset` of the plant's
inputs.

`gm.simulate`, `gm.replay`, `gm.live` and `gm.resume` cover a run in one call; `gm.Engine` is the
level for complex tasks, such as a run held in memory or a callback that reads the engine.

[examples/README.md](examples/README.md) lists every example in reading order, starting with
`python examples/quickstart.py`. The longer tour, from the repository root with Python 3.11, 3.12,
3.13 or 3.14:

```python
import pandas as pd

import gemini as gm

plant = gm.plants.example("DoubletHeatPlant")
design = {name: parameter.value for name, parameter in plant.doublet.esp.named_parameters()}
esp = gm.modules.ESP().set_params("", design)
stream = gm.Stream(flow={"value": 150, "unit": "m3/h"}, T={"value": 80, "unit": "C"}, p={"value": 20, "unit": "bar"})
out = esp(fluid_in=stream, frequency={"value": 50, "unit": "Hz"})
assert out.outputs.head == esp({"fluid_in": stream}, frequency={"value": 50, "unit": "Hz"}).outputs.head
assert out.outputs.head == esp(stream, frequency={"value": 50, "unit": "Hz"}).outputs.head
print(out.outputs.get("head", unit="bar"), out.outlets.fluid_out)
assert out.outlets.fluid_out is out.outlets["fluid_out"]

with gm.modules.no_outputs():
    fluid_only = esp(fluid_in=out.outlets.fluid_out, frequency={"value": 50, "unit": "Hz"})
assert dict(fluid_only.outputs) == {}

esp.frequency = 50.0
plant.doublet.esp.frequency = {"value": 50, "unit": "Hz"}

frame = pd.read_csv("inputs/doublet_heat/doublet_2024_15min.csv", parse_dates=["time"])
data = gm.Dataset.from_frame(frame, time_column="time")

results = gm.replay(plant, data, checkpoint="runs/replay.ckpt")
print(results.to_frame(table="energy"))
print(results["doublet.esp"].power)
assert len(gm.resume("runs/replay.ckpt")) == len(results)

fit = gm.analysis.calibrate(plant, data, params=[plant.get("heat_exchanger.thermal_conductance")])
print(fit)
```

A module is built without arguments and configured with `set_params`, which returns it. Calls
accept inlets by keyword, mapping or position; controls given at the call apply to that call only,
while assignment (`esp.frequency = 50.0`) persists them.

A leaf module computes and a plant connects: every composite is a `Plant` class that declares its
children, ports and connections, and `gm.Plant(name)` builds one with `add` and `connect`.
`gm.plants.names()` lists the plant classes, `gm.plants.example(name)` returns one with real values,
and `gm.Plant.from_legacy(folder)` turns an old project folder into a plant. The plant dict is the
JSON form agents read and write: `plant.to_dict()`, `gm.Plant.from_dict`, `gm.plants.schema()`, and
`plant.to_json(path)`, `gm.Plant.from_json(path)` for a file. `gm.data` reads your demand, from a CSV
file (`gm.data.from_csv`) or from values (`from_values`). Readers are `from_<format>` and writers
`to_<format>` everywhere.

gemini holds no data file. `gm.plants.example` reads `inputs/`, which is in a
source checkout and not installed, and outside one it raises `inputs_missing`:

```text
inputs/             # repository only
  examples/         # sample problems: problem.json, demand CSV, plant.json; examples and tests only
  plants/           # example values of plants
  doublet_heat/     # measured data
  legacy_project/   # an old project folder
```

A plant can be designed from its depth. A `Doublet` derives its reservoir, wells and pump from a few
design values. The site (geotherm, permeability, thickness) belongs to the problem, so one design
runs on several sites. `gm.schedule` plans each step from the demand with no bindings to write, and
`gm.evaluate.constraints` judges the run:

```python
plant.add("Doublet", name="d0", params={"depth": {"value": 2500, "unit": "m"}, "well_diameter": {"value": 0.244, "unit": "m"}})
problem = gm.Problem(
    demand,
    site={"d0.gradient": {"value": 30, "unit": "K/km"}, "d0.surface_temperature": {"value": 12, "unit": "degC"},
          "d0.permeability": {"value": 200, "unit": "mD"}, "d0.thickness": {"value": 100, "unit": "m"}},
    constraints=[
        gm.Constraint("d0.reservoir.liquid_flow", min={"value": 50, "unit": "m3/h"}, max={"value": 300, "unit": "m3/h"}, when="running"),
        gm.Constraint("d0.brine_cooling", max={"value": 40, "unit": "K"}),
    ],
)
results = gm.simulate(plant, problem)
checks = gm.evaluate.constraints(plant, problem, results)
```

`examples/cases/challenge_year.py` and `examples/cases/hackathon.py` run that path on the sample
problem of `inputs/examples/hackathon_2027/`, and `examples/cases/shallow_district.py` on a different
one, an hourly demand on one shallow doublet, each with its own constraints. A stored design keeps its setpoints:
`plant.set_inputs({"peak_boiler.temperature_setpoint": {"value": 100, "unit": "degC"}})` is part of `plant.to_dict()`, and
a template plant takes its size, `gm.plants.HeatingCoolingPlant(doublets=2)`.

Everything in the energy flow is a module and everything that crosses between modules goes through
a port. A plant starts at its edge modules: `ElectricityGrid`, `GasGrid`, `HeatingGrid`,
`CoolingGrid`, `WasteGrid`, `ChemicalGrid`, `Atmosphere` and `Formation`. Totals are read from them
(`gm.evaluate.totals(plant, problem, results)`) and `gm.evaluate.plant_balance(plant, problem,
results)` closes mass and energy on them.

The application, not the package, reads CSV, databases, or APIs. `Dataset` accepts pandas, dicts,
records, NumPy, and profiles already in memory. A plant owns bindings and dated parameters, so
engine and optimizer calls never take a separate configuration.

See [api.md](.claude/docs/api.md), [modules.md](.claude/docs/modules.md),
[data.md](.claude/docs/data.md), [engine.md](.claude/docs/engine.md),
[legacy.md](.claude/docs/legacy.md) and [errors.md](.claude/docs/errors.md). Report bugs with the
output of `python -m gemini._utils.collect_env`.

## Testing

```bash
make test           # development profile: tests of what changed and what imports it
make test-release   # release profile: every tier on the full-year dataset
make lint           # flake8, black and isort
```

Always test what changed and everything that imports it; never run the full suite locally. See
[testing.md](.claude/docs/testing.md) for the profiles, markers, fixtures and golden-generation
rules.
