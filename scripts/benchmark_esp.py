"""Benchmark the ESP, the doublet_heat replay, live ticks and a simulation over the July dataset.

Run ``PYTHONPATH=. python scripts/benchmark_esp.py`` from the repository root. On the committed
2,976-row July 2024 dataset it evaluates the ESP of the shared doublet plant by a direct call per
row and as one graph on the NumPy backend, with and without common-subexpression elimination,
then runs the whole plant on each backend: the month replay, live one tick at a time, and a
one-day simulation. It checks that the results agree and prints the best of ``--repeat`` CPU
times. It is a benchmark, not a test.
"""

import argparse
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

import gemini as gm
from gemini import runtime
from gemini._utils import paths
from gemini.compiler.graph import GraphCache, run
from gemini.types.flows import Stream
from tests.fixtures.parity import BACKENDS, RTOL

DATASET = paths.doublet_heat("doublet_2024_15min_month.csv")
COLUMNS = ["suction.m_dot", "suction.T", "suction.p", "frequency"]


def load():
    """Return the plant's ESP and its SI inputs: mass flow, T, p and frequency per row."""
    esp = gm.plants.example("DoubletHeatPlant").doublet.esp
    frame = pd.read_csv(DATASET, parse_dates=["time"])
    rows = frame[[f"doublet.esp.{column}" for column in COLUMNS]].dropna().to_numpy()
    rows[:, 0] *= esp.fluid.properties(None, None).density
    return esp, rows


def direct_calls(esp, rows):
    """Call the ESP once per row and return the results."""
    return [
        esp(
            fluid_in=gm.Stream(m_dot=m_dot, T=temperature, p=pressure, fluid=esp.fluid),
            frequency=frequency,
        )
        for m_dot, temperature, pressure, frequency in rows
    ]


def traced(esp, rows, cache):
    """Evaluate the ESP on all rows in one traced NumPy call."""
    suction = Stream(m_dot=rows[:, 0], T=rows[:, 1], p=rows[:, 2], fluid=esp.fluid)
    return run(esp, {"fluid_in": suction}, {"frequency": rows[:, 3]}, cache=cache)


def best_time(function, repeat):
    """Return the shortest CPU time [s] of ``repeat`` calls and the last result."""
    times, result = [], None
    for _ in range(repeat):
        start = time.process_time()
        result = function()
        times.append(time.process_time() - start)
    return min(times), result


def check_agreement(results, graph_run):
    """Return the largest relative difference over every output; fail above ``RTOL``."""
    worst = 0.0
    for name in results[0].outputs:
        expected = np.array([result.outputs[name] for result in results], dtype=float)
        actual = np.asarray(graph_run.outputs[name], dtype=float)
        scale = np.maximum(np.abs(expected), np.finfo(float).tiny)
        worst = max(worst, float(np.max(np.abs(actual - expected) / scale)))
    if worst > RTOL:
        raise SystemExit(f"traced results differ by {worst:.3g} > {RTOL}")
    return worst


def benchmark_esp(repeat):
    """Print the ESP tick by tick and traced, with and without common-subexpression elimination."""
    esp, rows = load()
    trace_time, _ = best_time(lambda: GraphCache().graph(esp, {"fluid_in": esp.fluid}), 1)
    merged, unmerged = GraphCache(), GraphCache(optimize=False)
    traced(esp, rows, merged)
    traced(esp, rows, unmerged)
    tick_time, results = best_time(lambda: direct_calls(esp, rows), repeat)
    plain_time, plain_run = best_time(lambda: traced(esp, rows, unmerged), repeat)
    graph_time, graph_run = best_time(lambda: traced(esp, rows, merged), repeat)
    worst = max(check_agreement(results, plain_run), check_agreement(results, graph_run))
    print(f"rows: {len(rows)}; nodes: {len(plain_run.graph.nodes)} -> {len(graph_run.graph.nodes)}")
    print(f"ESP tick by tick (untraced): {tick_time * 1e3:9.2f} ms")
    print(f"ESP trace (once, cached):    {trace_time * 1e3:9.2f} ms")
    print(f"ESP traced, no CSE:          {plain_time * 1e3:9.2f} ms")
    print(f"ESP traced, CSE:             {graph_time * 1e3:9.2f} ms")
    print(f"ESP speedup: {tick_time / graph_time:.0f}x; largest difference {worst:.3g}")


def replay(dataset):
    """Replay a freshly loaded plant over ``dataset`` and return the engine."""
    engine = gm.Engine(gm.plants.example("DoubletHeatPlant"))
    engine.replay(dataset)
    return engine


def simulate(dataset):
    """Simulate a freshly loaded plant over ``dataset`` and return the engine."""
    engine = gm.Engine(gm.plants.example("DoubletHeatPlant"))
    engine.simulate(dataset, gm.engine.Clock.from_data(dataset))
    return engine


def live(frame):
    """Evaluate ``frame`` one new row at a time through ``Engine.live``; return the engine."""
    engine = gm.Engine(gm.plants.example("DoubletHeatPlant"))
    views = [
        gm.Dataset.from_frame(frame.iloc[: row + 1], time_column="time")
        for row in range(len(frame))
    ]
    with tempfile.TemporaryDirectory() as folder:
        for view in views:
            engine.live(view, Path(folder) / "live.json")
    return engine


def benchmark_plant(repeat):
    """Print the replay, live and simulate on each backend; their frames must be equal."""
    frame = pd.read_csv(DATASET, parse_dates=["time"])
    month = gm.Dataset.from_frame(frame, time_column="time")
    day = gm.Dataset.from_frame(frame.iloc[:96], time_column="time")
    cases = (
        ("replay month", lambda: replay(month), len(month)),
        ("simulate day", lambda: simulate(day), len(day)),
        ("live, per tick", lambda: live(frame.iloc[:48]), 48),
    )
    for name, function, rows in cases:
        run_case(name, function, rows, repeat)


def run_case(name, function, rows, repeat):
    """Print one case on every backend, checking that the result frames are equal."""
    expected = None
    for backend in BACKENDS:
        with runtime.settings(backend=backend):
            seconds, engine = best_time(function, repeat)
        results = engine.results.to_frame()
        if expected is not None:
            pd.testing.assert_frame_equal(results, expected, check_exact=False, rtol=RTOL)
        expected = results
        print(f"{name}, {backend}: {seconds:9.3f} s, {seconds / rows * 1e3:9.3f} ms per tick")


def main():
    """Run both benchmarks."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeat", type=int, default=5, help="timed repetitions per path")
    repeat = parser.parse_args().repeat
    benchmark_esp(repeat)
    benchmark_plant(repeat)


if __name__ == "__main__":
    main()
