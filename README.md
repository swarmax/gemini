# GEMINI geothermal suite

Composable geothermal equipment, plants built from data, in-memory data, and one finite engine for
simulation, historical replay, and externally scheduled live updates.

## Quickstart

The short form, on a sample case of the repository:

```python
import gemini as gm

case = gm.Case.from_json("inputs/examples/shallow_district/case.json")
plant = gm.Plant.from_json("inputs/examples/shallow_district/plant.json")
results = gm.simulate(plant, case)
report = gm.evaluate.report(plant, case, results)
print(report["heat_delivered"].to("MWh").value, report["lcts"].to("EUR/MWh").value)
```

A `gm.Case` holds what a plant is asked to do and the world around it: the time, the environment,
the demand, the choices of a study, the constraints and the assumptions (prices, cost factors,
emission factors) of a run, in a `case.json` with its CSV files. The plant dict holds only the
plant. Every value with a unit is a `{"value": 150, "unit": "m3/h"}` or a `gm.units.Quantity`, text
such as `"150 m3/h"` is refused, and nothing a user must decide has a default: a value that is
missing raises `missing_value` naming its path. For measured inputs, `gm.simulate(plant, plan=frame)`
runs a DataFrame or `gm.Dataset` of the plant's inputs.

`gm.simulate`, `gm.replay`, `gm.live` and `gm.resume` cover a run in one call; `gm.Engine` is the
level for complex tasks, such as a run held in memory or a callback that reads the engine.

[examples/README.md](examples/README.md) lists the five examples, starting with
`python examples/quickstart.py`; `python examples/hackathon.py` sizes, searches, simulates, checks,
reports and compares six candidate plants on a case. The longer tour, from the repository root with Python 3.11, 3.12,
3.13 or 3.14:

```python
import pandas as pd

import gemini as gm

plant = gm.Plant.from_json("inputs/doublet_heat/plant.json")
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
`gm.plants.names()` lists the plant classes, `gm.plants.get(name)` returns one without values.
The plant dict is the JSON form agents read and write: `plant.to_dict()`, `gm.Plant.from_dict`, `gm.plants.schema()`, and
`plant.to_json(path)`, `gm.Plant.from_json(path)` for a file. `gm.data` reads your demand, from a CSV
file (`gm.data.from_csv`) or from values (`from_values`). Readers are `from_<format>` and writers
`to_<format>` everywhere.

gemini holds no data file. The example values of the plants are in `inputs/`, which is in a
source checkout and not installed; read a stored plant with `gm.Plant.from_json(path)`:

```text
inputs/             # repository only
  examples/         # sample cases: case.json, demand CSV, plant dicts; examples and tests only
  plants/           # example values of plants
  doublet_heat/     # measured data and the plant dict that fits it
  legacy_project/   # an old project folder
```

A plant can be designed from its depth. A `Doublet` derives its reservoir, wells and pump from a few
design values; the ground, the reservoir and the brine belong to the case, so one design runs on
several cases. `gm.schedule` plans each step from the demand of the case with no bindings to write,
`gm.evaluate.constraints` judges the run against the `constraints` of the case, and `gm.study`
sizes a design and searches the choices of the case:

```python
case = gm.Case.from_json("inputs/examples/shallow_district/case.json")
plant = gm.Plant.from_json("inputs/examples/shallow_district/plant.json")
sized = gm.study.size(plant, case, backup="peak")
results = gm.simulate(sized, case)
checks = gm.evaluate.constraints(sized, case, results)
print([check["name"] for check in checks if check["passed"] is False])
```

`examples/hackathon.py` runs that path on the sample case of `inputs/examples/hackathon_2026/`, and
`examples/quickstart.py` on `inputs/examples/shallow_district/`, an hourly demand on one shallow
doublet, each with its own constraints. A stored design keeps its setpoints:
`plant.set_inputs({"peak_boiler.temperature_setpoint": {"value": 100, "unit": "degC"}})` is part of `plant.to_dict()`, and
a template plant takes its size, `gm.plants.HeatingCoolingPlant(doublets=2)`.

Everything in the energy flow is a module and everything that crosses between modules goes through
a port. A plant starts at its edge modules: `ElectricityGrid`, `GasGrid`, `HeatingGrid`,
`CoolingGrid`, `WasteGrid`, `ChemicalGrid`, `Atmosphere` and `Formation`. Totals are read from them
(`gm.evaluate.totals(plant, case, results)`) and `gm.evaluate.plant_balance(plant, case,
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
