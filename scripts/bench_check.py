"""Check that a fresh run of every benchmark case gives the numbers of a saved baseline.

Run ``PYTHONPATH=. python scripts/bench_check.py --save`` once on code known to be right: it runs
every case of ``scripts/bench_year.py`` (daily year and hourly month, eager and compiled) and
stores every result column of ``results.to_frame()``, ``results.errors()`` and
``results.skip_counts`` in ``.tmp/speed/baseline.npz`` below ``--out`` (the repository root by
default). Without ``--save`` it runs the cases again, or reads a file written by ``--save
--baseline OTHER`` given as ``--fresh``, and compares each run with the baseline.

A column is the same when every value is within a relative 1e-9 of the baseline: zeros, NaN and
infinities must match exactly, and booleans, strings and objects are compared exactly. The failed
steps, the error codes and messages and the skip counts must be equal. The output is PASS or each
differing column with its worst row and size, and the exit code is 1 on any difference. It also
compares the eager run with the compiled run of the baseline and reports any difference without
changing the exit code.
"""

import argparse
import json
import sys
from pathlib import Path

import bench_year
import numpy as np
import pandas as pd

RTOL = 1e-9
SEPARATOR = "||"


def key_of(case, cadence, mode):
    """Return the name of a run in the baseline."""
    return f"{case}/{cadence}/{mode}"


def column_array(series):
    """Return the values of a column: floats stay floats, anything else becomes objects."""
    if pd.api.types.is_float_dtype(series) and not isinstance(series.dtype, pd.StringDtype):
        return series.to_numpy(dtype=float)
    return series.to_numpy(dtype=object)


def capture(case, cadence, mode):
    """Run one case and return what the baseline keeps of it."""
    try:
        results = bench_year.simulate(case.plant, case.inputs(cadence), mode)
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}
    frame = results.to_frame()
    return {
        "index": frame.index.astype(str).to_numpy(dtype=object),
        "names": np.array(list(frame.columns), dtype=object),
        "errors": json.dumps(results.errors(), default=str, sort_keys=True),
        "skips": json.dumps(dict(results.skip_counts), default=str, sort_keys=True),
        "columns": {name: column_array(frame[name]) for name in frame.columns},
    }


def capture_all(only):
    """Run every selected case and return ``{run key: capture}``."""
    runs = {}
    for case, cadence, mode in bench_year.run_names(only):
        key = key_of(case.name, cadence, mode)
        runs[key] = capture(case, cadence, mode)
        print(f"ran {key}", flush=True)
    return runs


def flatten(runs):
    """Return the arrays of ``runs`` under flat names, for ``np.savez``."""
    flat = {}
    for key, run in runs.items():
        for field in ("error", "errors", "skips"):
            if field in run:
                flat[f"{key}{SEPARATOR}{field}"] = np.array(run[field])
        if "index" in run:
            flat[f"{key}{SEPARATOR}index"] = run["index"]
            flat[f"{key}{SEPARATOR}names"] = run["names"]
        for position, values in enumerate(run.get("columns", {}).values()):
            flat[f"{key}{SEPARATOR}col{position}"] = values
    return flat


def restore(path):
    """Return ``{run key: capture}`` from a file written by ``flatten``."""
    runs = {}
    with np.load(path, allow_pickle=True) as stored:
        for name in stored.files:
            key, field = name.split(SEPARATOR)
            runs.setdefault(key, {})[field] = stored[name]
    for run in runs.values():
        for field in ("error", "errors", "skips"):
            if field in run:
                run[field] = str(run[field])
        names = run.get("names", [])
        run["columns"] = {name: run.pop(f"col{i}") for i, name in enumerate(names)}
    return runs


def same_object(first, second):
    """Return whether two scalar values are equal, two NaN or two missing values being equal."""
    missing = [
        value is None or (isinstance(value, float) and value != value) for value in (first, second)
    ]
    if any(missing):
        return all(missing)
    try:
        return bool(first == second)
    except ValueError:
        return repr(first) == repr(second)


def exact_differences(old, new):
    """Return the row positions where two non-float columns differ."""
    return [row for row in range(len(old)) if not same_object(old[row], new[row])]


def float_worst(old, new):
    """Return ``(row, size)`` of the worst difference of two float columns, or ``None``."""
    nan = np.isnan(old) | np.isnan(new)
    if (np.isnan(old) != np.isnan(new)).any():
        return int(np.argmax(np.isnan(old) != np.isnan(new))), float("inf")
    with np.errstate(invalid="ignore"):
        gap = np.where(nan | (old == new), 0.0, np.abs(old - new))
        scale = np.maximum(np.abs(old), np.abs(new))
        size = np.where(
            gap == 0, 0.0, np.where(scale > 0, gap / np.where(scale > 0, scale, 1), np.inf)
        )
    size = np.where(np.isnan(size), np.inf, size)
    row = int(np.argmax(size))
    return (row, float(size[row])) if size[row] > RTOL else None


def column_difference(name, old, new, index):
    """Return the sentence for a differing column, or ``None`` when it is the same."""
    if old.dtype == float and new.dtype == float:
        worst = float_worst(old, new)
        if worst is None:
            return None
        row, size = worst
        return f"{name}: worst row {index[row]} {old[row]!r} -> {new[row]!r} (relative {size:.3g})"
    rows = exact_differences(old, new)
    if not rows:
        return None
    first = rows[0]
    return f"{name}: {len(rows)} rows differ, first {index[first]} {old[first]!r} -> {new[first]!r}"


def differences(old, new):
    """Return the sentences that say how capture ``new`` differs from ``old``."""
    if "error" in old or "error" in new:
        same = old.get("error") == new.get("error")
        return [] if same else [f"error: {old.get('error')!r} -> {new.get('error')!r}"]
    found = [
        f"{field}: {old[field]} -> {new[field]}"
        for field in ("errors", "skips")
        if old[field] != new[field]
    ]
    if list(old["index"]) != list(new["index"]):
        return found + ["index differs"]
    names = list(old["columns"])
    found += [f"column {name} is missing" for name in names if name not in new["columns"]]
    found += [f"column {name} is new" for name in new["columns"] if name not in old["columns"]]
    for name in (name for name in names if name in new["columns"]):
        sentence = column_difference(name, old["columns"][name], new["columns"][name], old["index"])
        found += [sentence] if sentence else []
    return found


def report(title, found):
    """Print PASS or the differences of one comparison; return whether it passed."""
    print(f"{title}: {'PASS' if not found else f'{len(found)} differences'}")
    for sentence in found[:40]:
        print(f"    {sentence}")
    return not found


def check_baseline(baseline, fresh):
    """Compare every run of ``fresh`` with ``baseline``; return whether all passed."""
    passed = True
    for key in sorted(set(baseline) | set(fresh)):
        if key not in baseline or key not in fresh:
            passed = (
                report(
                    key,
                    ["run is missing from the " + ("fresh run" if key in baseline else "baseline")],
                )
                and passed
            )
            continue
        passed = report(key, differences(baseline[key], fresh[key])) and passed
    return passed


def check_modes(baseline):
    """Report the differences between the eager and compiled runs of the baseline."""
    print("eager against compiled, in the baseline (reported, not an error):")
    for key in sorted(baseline):
        if key.endswith("/eager") and key[:-5] + "compiled" in baseline:
            report(f"  {key[:-6]}", differences(baseline[key], baseline[key[:-5] + "compiled"]))


def options():
    """Return the parsed command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--save", action="store_true", help="write the baseline, do not compare")
    parser.add_argument("--baseline", type=Path, help="the baseline file")
    parser.add_argument("--fresh", type=Path, help="a saved file to compare, instead of a run")
    parser.add_argument("--only", help="the cases whose name contains this text")
    parser.add_argument("--out", type=Path, default=bench_year.ROOT, help="repository root")
    args = parser.parse_args()
    args.baseline = args.baseline or args.out / ".tmp" / "speed" / "baseline.npz"
    return args


def main():
    """Save the baseline, or compare a fresh run with it; exit 1 on a difference."""
    args = options()
    if args.save:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        np.savez(args.baseline, **flatten(capture_all(args.only)))
        print(f"saved {args.baseline}")
        return
    baseline = restore(args.baseline)
    fresh = restore(args.fresh) if args.fresh else capture_all(args.only)
    if args.only:
        baseline = {key: run for key, run in baseline.items() if args.only in key}
    passed = check_baseline(baseline, fresh)
    check_modes(baseline)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
