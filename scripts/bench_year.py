"""Time a daily year and an hourly month of the sample plants, eager and compiled.

Run ``PYTHONPATH=. python scripts/bench_year.py`` from the repository root. The cases are the
hackathon plant, the hackathon plant with treatment and the shallow district plant, each with the
``problem.json`` of its folder, plus the doublet heat plant, which has no loop or constraint, on a
constant plan. Each case runs a daily year and an hourly month, with ``compile=False`` and
``compile=True``.

A demand may be daily or hourly. The other cadence is derived with public functions only: the
demand frame is resampled to the step (the mean to a coarser step, the last value to a finer one),
repeated cyclically to the wanted number of rows, rebuilt with ``gm.data.from_values`` and joined
with ``pd.concat``, and a ``gm.Problem`` is built from it with the site, constraints and
assumptions of the original. The plan of the plain plant is a constant profile on a
``gm.engine.Clock``. A case that cannot run a cadence is recorded with its error, not fatal.

Per run it prints the median wall time of ``gm.simulate`` after one warm-up call, the time of the
first call, of a call on a copy of the plant and the cProfile counts: rows run row by row
(``_call_row``), the rows on arrays, loop closures (``loops.close``), tear advances (passes times
tears), constraint solves and ``Module._trial`` calls, then the top ten functions by cumulative
time of one extra profiled call. The counts come from the call counts of private functions, found
by name in the profile; the script itself calls public names. ``--baseline FILE`` compares the
times with a file this script wrote; the file of a run is ``.tmp/speed/bench-<label>.json`` below
the repository root, or below ``--out``. Timings are noisy when other work runs: the load average
is printed next to each run.
"""

import argparse
import copy
import cProfile
import json
import os
import pstats
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import gemini as gm
from gemini._utils import paths

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = paths.INPUTS / "examples"
DELTAS = {"1d": pd.Timedelta(days=1), "1h": pd.Timedelta(hours=1)}
CADENCES = {"daily-year": ("1d", 365), "hourly-month": ("1h", 744)}
MODES = {"eager": False, "compiled": True}
SAMPLES = (
    ("hackathon", "hackathon_2027", "plant.json", "problem.json"),
    (
        "hackathon-treatment",
        "hackathon_2027",
        "plant_with_treatment.json",
        "problem_with_treatment.json",
    ),
    ("shallow-district", "shallow_district", "plant.json", "problem.json"),
)
COUNTED = {
    "rows_by_row": ("engine/rows.py", "_call_row"),
    "loop_closures": ("plants/_utils/loops.py", "close"),
    "constraint_solves": ("plants/_utils/constraints.py", "solve"),
    "trial_calls": ("modules/module.py", "_trial"),
}
PLAIN = {
    "doublet.reservoir.production_rate": (150, "m3/h"),
    "doublet.esp.frequency": (60, "Hz"),
    "injection_pump.pressure_setpoint": (51.5, "bar"),
}


@dataclass
class Case:
    """One plant with what is needed to run it at a cadence."""

    name: str
    plant: object
    problem: object = None

    def inputs(self, cadence):
        """Return the keyword arguments of ``gm.simulate`` for ``cadence``."""
        step, count = CADENCES[cadence]
        if self.problem is None:
            return plain_inputs(step, count)
        return {"problem": rebuilt(self.problem, step, count)}


def plain_inputs(step, count):
    """Return a constant plan of ``count`` steps for the plant that has no loop."""
    days = count if step == "1d" else count // 24
    clock = gm.engine.Clock.days(2027, 1, 1, days=days, step=step)
    profiles = {
        path: gm.types.Profile.constant(value, unit=unit, clock=clock)
        for path, (value, unit) in PLAIN.items()
    }
    return {"plan": gm.Dataset.from_profiles(profiles), "clock": clock}


def rebuilt(problem, step, count):
    """Return ``problem`` with its demand at ``step``, repeated cyclically to ``count`` rows."""
    demand = problem.demand
    current = demand.index[1] - demand.index[0]
    resampler = demand.resample(DELTAS[step])
    frame = resampler.mean() if DELTAS[step] >= current else resampler.ffill()
    columns = [
        gm.data.from_values(
            np.resize(frame[name].to_numpy(), count), "W", frame.index[0], step, name
        )
        for name in frame
    ]
    return gm.Problem(
        pd.concat(columns, axis=1), problem.site, problem.constraints, problem.assumptions
    )


def cases(only=None):
    """Return the cases whose name contains ``only``, or all of them."""
    found = []
    for name, folder, plant_file, problem_file in SAMPLES:
        plant = gm.Plant.from_json(EXAMPLES / folder / plant_file)
        problem = gm.Problem.from_json(EXAMPLES / folder / problem_file)
        found.append(Case(name, plant, problem))
    found.append(Case("doublet-heat-plain", gm.plants.example("DoubletHeatPlant")))
    return [case for case in found if only is None or only in case.name]


def run_names(only=None):
    """Return ``(case, cadence, mode)`` for every run selected by ``only``."""
    return [(case, cadence, mode) for case in cases(only) for cadence in CADENCES for mode in MODES]


def simulate(plant, arguments, mode):
    """Run ``gm.simulate`` once in ``mode`` and return the results."""
    return gm.simulate(plant, compile=MODES[mode], **arguments)


def timed(plant, arguments, mode):
    """Return the wall time [s] of one ``gm.simulate`` call."""
    start = time.perf_counter()
    simulate(plant, arguments, mode)
    return time.perf_counter() - start


def counts(profiler):
    """Return the counted calls of the profile and its top ten functions by cumulative time."""
    stats = pstats.Stats(profiler)
    found = {name: 0 for name in COUNTED}
    advances = {}
    for (path, line, function), (_, calls, _, _, _) in stats.stats.items():
        for name, (suffix, wanted) in COUNTED.items():
            found[name] += calls if path.endswith(suffix) and function == wanted else 0
        if path.endswith("plants/_utils/loops.py") and function == "advance":
            advances[line] = calls
    found["tear_advances"] = advances[max(advances)] if advances else 0
    ranked = sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)
    found["top"] = [
        [f"{Path(path).name}:{line}:{function}", values[1], round(values[3], 3)]
        for (path, line, function), values in ranked[:10]
    ]
    return found


def measure(case, cadence, mode, repeats):
    """Return the record of one run: times, counts, loads; a failing run records its error."""
    arguments = case.inputs(cadence)
    record = {"case": case.name, "cadence": cadence, "mode": mode}
    try:
        plant = copy.deepcopy(case.plant)
        record["first_s"] = timed(plant, arguments, mode)
        record["median_s"] = statistics.median(
            timed(plant, arguments, mode) for _ in range(repeats)
        )
        record["copy_s"] = timed(copy.deepcopy(plant), arguments, mode)
        profiler = cProfile.Profile()
        profiler.enable()
        results = simulate(plant, arguments, mode)
        profiler.disable()
    except Exception as error:
        return record | {"error": f"{type(error).__name__}: {error}"[:300]}
    record["rows"] = len(results.to_frame())
    record["failed_rows"] = len(results.errors())
    record["skips"] = dict(results.skip_counts)
    record.update(counts(profiler))
    record["load"] = os.getloadavg()[0]
    return record


def show(record):
    """Print one record."""
    title = f"{record['case']:<20} {record['cadence']:<13} {record['mode']:<9}"
    if "error" in record:
        print(f"{title} cannot run: {record['error']}")
        return
    rows = record["rows"]
    print(
        f"{title} median {record['median_s']:7.3f} s  first {record['first_s']:7.3f} s  "
        f"copy {record['copy_s']:7.3f} s  load {record['load']:.1f}"
    )
    print(
        f"    rows {rows}: by row {record['rows_by_row']}, on arrays {rows - record['rows_by_row']}"
        f"; closures {record['loop_closures']}, tear advances {record['tear_advances']}, "
        f"solves {record['constraint_solves']}, trials {record['trial_calls']}; "
        f"failed {record['failed_rows']}, skips {record['skips']}"
    )
    for name, calls, cumulative in record["top"]:
        print(f"      {cumulative:8.3f} s {calls:9d}  {name}")


def compare(records, path):
    """Print the ratio of each median to the one in the file ``path``."""
    before = {
        (r["case"], r["cadence"], r["mode"]): r.get("median_s")
        for r in json.loads(Path(path).read_text())
    }
    for record in records:
        old = before.get((record["case"], record["cadence"], record["mode"]))
        new = record.get("median_s")
        if old and new:
            name = f"{record['case']} {record['cadence']} {record['mode']}"
            print(f"{name}: {new / old:.3f} x {old:.3f} s")


def options():
    """Return the parsed command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="run", help="name of the output file")
    parser.add_argument("--repeats", type=int, default=5, help="timed calls per run")
    parser.add_argument("--only", help="run the cases whose name contains this text")
    parser.add_argument("--baseline", help="a bench file to compare the medians with")
    parser.add_argument("--out", type=Path, default=ROOT, help="repository root of the output")
    return parser.parse_args()


def main():
    """Run the selected benchmark runs, print them and write the file."""
    args = options()
    records = []
    for case, cadence, mode in run_names(args.only):
        records.append(measure(case, cadence, mode, args.repeats))
        show(records[-1])
    target = args.out / ".tmp" / "speed" / f"bench-{args.label}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(records, indent=1))
    if args.baseline:
        compare(records, args.baseline)


if __name__ == "__main__":
    main()
