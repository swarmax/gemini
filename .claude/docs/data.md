# Data

Readers are `from_<format>` and writers `to_<format>`. A reader is a classmethod of the class it
returns (`gm.Case.from_json(path)`, `gm.Plant.from_json(path)`, `gm.Results.from_npz(path)`,
`Dataset.from_frame(...)`); a writer is a method of the object (`case.to_json(path)`,
`results.to_npz(path)`, `plant.to_dict()`). Only a reader that returns no gemini class, a demand
frame, is a plain function in its folder: `gm.data.from_csv` and `gm.data.from_values`. No name
starts with `read_`, `write_`, `load_`, `save_`, `parse_` or `dump_`.

## In-memory data

`gm.Dataset` (`gemini/run/dataset.py`) owns one pandas-backed, sorted, unique, timezone-aware UTC
table of raw values; units are metadata. `Dataset` and the engine contain no file readers, database
clients, network calls, or source handles. The user or backend reads files/services and passes the
resulting in-memory values to one of:

- `Dataset.from_frame(df, time_column=None, units=None, tz="UTC")`
- `Dataset.from_dict(data, time, units=None, tz="UTC")`
- `Dataset.from_records(rows, time_column, units=None, tz="UTC")`
- `Dataset.from_numpy(time, values, columns, units=None, tz="UTC")`
- `Dataset.from_profiles(profiles)`
- `Dataset(frame, units=None)` for a frame that already has a time index

The time axis may be any timestamp sequence: datetimes, ISO text or values with UTC offsets.
Naive timestamps are local times in `tz` and fail when ambiguous or nonexistent at a DST switch;
values with offsets keep their own offsets, which may change at DST switches. The index may have
any resolution (s, ms, us or ns; pandas 3 parses text as microseconds); spacing, gaps and sampling
are computed in nanoseconds. `units` maps column names to a unit string or a
`{"unit": ..., "quantity": ...}` mapping. `from_profiles` takes a mapping of column names to
profiles that share one index and records their SI units. Invalid input (no time column, repeated
or missing timestamps, repeated or empty column names, unit metadata for unknown columns, a wrong
array shape) raises `gm.errors.RunError`.

`read(start, end, columns=None)` and `window(start, end)` use inclusive bounds; `after(t)` is
strict. `names` lists the columns, `start`/`end` the first and last timestamps, and
`native_step` is the median spacing (`None` for fewer than two rows). `unit(column, default)`
returns the unit recorded for a column, or `default` without metadata: during a run a column's
recorded unit replaces the unit in the plant binding, and the binding unit applies otherwise.
`fingerprint()` hashes timestamps, values, dtypes and unit metadata; checkpoints store it for
information only and nothing compares it on resume. Text flags are retained. Missing bound
columns are reported together, as one `ValidationError` (code `missing_column`), before a run begins.

**Run input.** `simulate`, `replay` and `live` take one format: a `Dataset`, or a pandas DataFrame
with a timezone-aware `DatetimeIndex` and columns named by the binding `column`, in the units of
the bindings (a unit recorded in the `Dataset` metadata replaces the binding's, as above).
`gemini.run.dataset.as_dataset(data)` is the one wrapper: a `Dataset` passes through, a
DataFrame becomes a `Dataset` (any zone is converted to UTC), and a naive index, a non-time index
or another type raises `RunError`, because a local time without a zone is ambiguous. Rows with
NaN in a bound column are skipped for the twin that needs them and reported as `missing_value`
rows by `Results.errors()`; the run continues ([engine.md](engine.md#run-input)).

`Loader(dataset, ticks, columns=None, align="previous", max_gap=None, chunk=7 days,
durations=None)` is the internal sampler. It accepts any finite tick iterable and never imports
engine code. It yields `Sample(t, dt, row)`: the tick, the seconds to the next tick and a dict of
raw column values. `durations` gives those seconds per tick; by default they are the tick spacing
followed by the native cadence. `previous` alignment holds the latest row at or before the tick,
`exact` requires a row at the tick and `mean` averages numeric values over `[tick, next_tick)` and
keeps the final text flag. A hold older than `max_gap` (by default twice the native cadence, or
twice `DEFAULT_STEP` for fewer than two rows) and an empty mean bin give a row of NaN, which the
engine reports as missing measurements. The dataset is read one `chunk` of ticks at a time.
`Loader.arrays()` is the one alignment: `Aligned(times, durations, columns)` with one array per
column, for every `align` (gaps are NaN; a column is `float64`, or `object` when the dataset holds
text). Iterating yields the `Sample` of each tick built from those arrays, one chunk at a time.
`Aligned.numbers(column)` converts a column to floats (what `float()` refuses is NaN) and
`Aligned.present(column)` is the "missing" rule: a row holds a value when it is a finite number.
Tests assert that iteration equals the arrays, gaps, `max_gap` and chunk borders included.
Normal users do not construct loaders.

A frame may state units in `attrs["units"]`, as a `gm.schedule` plan does; they are the metadata of
its `Dataset`, so they replace a binding's unit, and a unit of a column the frame no longer has is
dropped.

`Profile.constant(value, unit=..., clock=...)` and `Profile.from_series(series, unit=...)`
convert in-memory raw values to SI. Profiles combined into a dataset must share a clock.

## Demand profiles

`gm.data` ships no profile: a demand is the caller's. The code is `gemini/case/_utils/demand.py`,
which `gm.data` exports, because a `gm.Case` holds a demand and `run` imports no `data`.
`from_csv(path, columns, unit, time_column=None)` reads a file, and `columns` maps its columns to the quantities of gemini, so a
file adapts to gemini and gemini takes no name or unit from it. `from_values(values, unit, start,
step, quantity)` takes numbers. A quantity is `heating_demand` or `cooling_demand`. Both return a
DataFrame in the run-input format, the form of a case's `demand.frame`: a UTC `DatetimeIndex` called `time`
at any constant step and of any length, one column per quantity in W, and `frame.attrs` with `units`
and `quantities`. Both validate through one check: a monotonic index with no gaps or repeats, a
constant step, no negative or missing value, a known quantity. `profile_schema()` is the JSON Schema
of the same frame as a document: `columns` (unit and quantity), `time` and `values`.
A profile column becomes a run input when a plant binding names it as
its `column`.

The committed CSVs under `inputs/doublet_heat/` are immutable source data. Two
of their naming choices predate the naming rule and stay: columns named `*.m_dot` hold volumetric
flow in m3/s (their bindings declare `"unit": "m3/s"`), and the unbound status columns
(`esp_status`, `hex_status`, `filterA_status`, `filterB_status`) and
`production_wellhead_pressure` keep their old names.

## The case

`gm.Case` is the strict, typed entry boundary of every run: fixed sections in a `case.json`, with
CSV files next to it. Every class is a frozen pydantic model that refuses unknown keys
(`additionalProperties: false` at every level of `gm.Case.schema()`); every value is stored in SI;
nothing has a default, so an absent value is `None` and the call that needs it raises
`missing_value` (`missing_assumption` below `assumptions`) naming its path. Only `time` is required.
`Case.from_json(path)` reads the file and the CSVs named in it; `case.to_json(path)` writes both
back, so that `Case.from_json(path) == case`; `Case.from_dict(data, folder)` and `case.to_dict()`
are the plain forms.

**The unit format.** A value with a unit is `{"value": 150, "unit": "m3/h"}` in the file and a
`gm.units.Quantity` in Python, with a unit of the `gm.units.Unit` enum ([units](conventions.md#units)).
Text such as `"150 m3/h"` raises `invalid_value`; a unit of another dimension raises `invalid_unit`
listing the units of the field. A dimensionless value (a share, a rate, a count, the GWP) is a
plain number. The case stores SI and `to_json` writes the SI unit (`degC` becomes kelvin, money is
`currency/...`; the currency is the label `finance.currency`, and nothing converts between
currencies). A number that a call needs but a user stated in a unit is read back with `.to(unit)`.

Sections of `case.json`, in order:

| Section | Holds |
| --- | --- |
| `time` | `start`, `end` (excluded) and `step`: the steps every profile lies on; `case.time.index` is the UTC `DatetimeIndex` |
| `environment` | `ground` (`surface_temperature`, `gradient`), `reservoir` (`reference_depth`, `thickness`, `permeability`, `pressure`, optional `temperature`), `fluid` (`density`, `viscosity`, `gas_liquid_ratio`, `gas` as mole fractions of `CH4`, `CO2`, `N2`, `H2S`), `air` (`temperature`, a number or a profile). `temperature_at(depth)` and `pressure_at(depth)` apply the two rules of `gemini/physics/ground.py`, and raise `missing_value` for what they need |
| `demand` | `file`, `time_column` (the first column when absent), and `heating`, `cooling`: each `{column, unit, supply_temperature, return_temperature}`. The CSV is read into `case.demand.frame`, in W on `time.index`, columns `heating_demand` and `cooling_demand` |
| `choices` | what a study may vary: `doublets` and `depth`, each `{min, max}` |
| `constraints` | a list of `{on, quantity, min, max, equals, over, when}`: a limit on a **role** and a **quantity** of it, from the closed table `gm.case.roles()` (`doublet`: `production_flow`, `brine_cooling`, `pump_efficiency`, `volume_imbalance`, ...; `heat_pump`, `boiler`, `chp`, `chiller`, `heat_exchanger`, `heating_supply`, `cooling_supply`). It applies to every unit of its role on its own. `over` is `each`, `sum`, `mean`, `max`, `min` or `duration`; `when` is `always` or `running`; these two are the only defaults of the case |
| `assumptions` | `finance` (`currency`, `discount_rate`, `lifetime`, `price_year`, `capex.<kind>`, `opex.fixed.<kind>` as `%/yr`, `opex.electricity`, `gas`, `chemical`, `waste_disposal`, `co2`, `revenue.heat`, `revenue.cold`, `allocation.heat_cost_share`) and `emissions` (`CO2.electricity`, `CH4.gwp`) |

**Uncertainty.** Any number under `environment` or `assumptions` may carry an `uncertainty` next to
its value, in the value's unit: `{"value": 105.75, "unit": "EUR/MWh", "uncertainty": {"kind":
"uniform", "min": 80, "max": 140}}`; a dimensionless value is `{"value": 0.05, "uncertainty": {...}}`.
`kind` is required: `uniform` and `triangular` (mode = value) need `min` and `max`; `normal` (mean =
value) needs `std` and may be cut by `min` and `max`. The value lies inside `[min, max]`, and `min`
and `max` respect the bounds of the field. An unknown or missing key raises with its path
(`assumptions.finance.opex.electricity.uncertainty.max`); `time`, `demand`, `choices` and
`constraints` cannot carry one, nor can a profile. The case stores each as a frozen
`gm.case.Uncertainty` in SI in `case.uncertainty`, by dotted path, and `to_dict` writes it back next
to the value. A run, `size` and `minimize` use only `value`; `gm.study.sample` and
`gm.study.sensitivity` read the declarations and nothing else.

The kinds of `capex` and `opex.fixed` are the 19 of `gm.case.Capex` (the list is in
[economics.md](economics.md#costs)); a plant needs a factor and a share for each kind it contains.
`inputs/examples/hackathon_2026/case.json` is the complete example, with the sources of the cited
values in [economics.md](economics.md#the-values-of-the-assumptions).

**CSV profiles.** The demand is one CSV (`demand.file`) with a time column and a column for each
service, on the steps of `time`: the same start, step and number of rows, else `invalid_value`
naming the first row that differs. Any other value that varies in time (the air temperature, an
opex price, a revenue, the CO2 intensity of electricity) is a number or a profile
`{"file": "air.csv", "column": "temperature", "unit": "degC"}`: the first column of the file holds
the timestamps, which must be the steps of `time`, and a missing value in the column raises
`missing_value`. In Python a profile is a `Quantity` with an array value. `to_json` writes
`demand.csv` in W under the services' column names and one file for each profile, named from the
file and the path (`case_environment_air_temperature.csv`) with the unit in SI, and names it in the
JSON. A price along the demand is integrated step by step.

## Where data lives

There is one data folder, and no data file inside `gemini/`: a plant is a class.

`inputs/` is at the repository root, next to `gemini/`, and is not installed. It holds everything
that code reads: `examples/` (sample cases), `plants/` (example values: a `size`, `params`,
`fluids`, `boundary`, `bindings`, `param_history` and `inputs`; the template plants have none),
`doublet_heat/` (measured data) and `legacy_project/`. A function that needs it raises `RunError`
with code `inputs_missing` when it is absent, as in an installed wheel, and the message names the
file. Nothing fails at import time, and `gm.plants.get` works without it.

`inputs/examples/<sample>/` holds one folder per sample case, a whole case in the shapes of gemini.
Each has:

- `case.json`: a `gm.Case` (`gm.Case.from_json`), see [the case](#the-case). It names the demand CSV;
- the demand CSV, read through `case.json` (`demand.file`);
- the plant dicts (`gm.Plant.from_json`): `plant.json` for `shallow_district/`, and one file for
  each candidate in `plants/` for `hackathon_2026/`; a design without the world;
- `README.md`: the source of the files and what the case asks.

`hackathon_2026/` also keeps its organiser files (the requirements PDF and the two daily demand
CSVs). A whole run is:

```python
import gemini as gm

case = gm.Case.from_json("inputs/examples/shallow_district/case.json")
plant = gm.Plant.from_json("inputs/examples/shallow_district/plant.json")
results = gm.simulate(plant, case)
```

**Only `examples/` and `tests/` read this folder** (tests through
`tests/fixtures/sample_cases.py`): nothing under `gemini/` names it or a sample, and
`tests/unit/test_code_quality.py` checks that. A sample is a test of the code, never the source of a
default, a name or a structure.

`docs/schemas/` is generated documentation, not data. `tests/fixtures/` holds goldens and
`tests/e2e/expected/` example outputs. `gemini/_utils/paths.py` is the one place that knows where the
folder is, and `tests/unit/test_code_quality.py` checks the layout.
