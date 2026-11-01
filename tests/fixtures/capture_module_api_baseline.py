"""Capture phase-0 state and results before the module API migration.

Historical generator of ``module_api_baseline/``, committed in 3102a12. It ran once as
``PYTHONPATH=. python tests/fixtures/capture_module_api_baseline.py`` on the untouched
``refactor`` implementation. The files are comparison inputs for the new API; running it now
would overwrite immutable goldens with new-API output, so never run it again.
"""

import json
from time import perf_counter

import pandas as pd

import gemini as gm
from gemini._utils import paths
from gemini.types import Profile
from tests.fixtures import FIXTURES
from tests.fixtures.frames import path_frame
from tests.fixtures.sample_cases import example_plant

OUTPUT = FIXTURES / "module_api_baseline"


def main():
    """Write plant state, full replay, quickstart simulation and timing metadata."""
    OUTPUT.mkdir(exist_ok=True)
    plant = example_plant("DoubletHeatPlant")
    data = gm.Dataset.from_frame(
        pd.read_csv(paths.doublet_heat("doublet_2024_15min.csv"), parse_dates=["time"]),
        time_column="time",
    )

    started = perf_counter()
    replay = gm.replay(plant, data)
    replay_seconds = perf_counter() - started
    path_frame(replay).to_csv(OUTPUT / "replay.csv.gz", compression="gzip")

    clock = gm.engine.Clock.days(2027, 1, 1, days=1)
    profiles = {
        "doublet.reservoir.m_dot": Profile.constant(150, unit="m3/h", clock=clock),
        "doublet.esp.frequency": Profile.constant(55, unit="Hz", clock=clock),
        "injection_pump.pressure_setpoint": Profile.constant(51.5, unit="bar", clock=clock),
    }
    simulation = gm.simulate(plant, plan=gm.Dataset.from_profiles(profiles), clock=clock)
    path_frame(simulation).to_csv(OUTPUT / "simulate.csv.gz", compression="gzip")

    (OUTPUT / "state_dict.json").write_text(
        json.dumps(plant.state_dict(), indent=2, sort_keys=True) + "\n"
    )
    (OUTPUT / "metadata.json").write_text(
        json.dumps(
            {
                "baseline_branch": "refactor",
                "pytest": "148 passed in 288.87s",
                "pytest_wall_seconds": 290.36,
                "replay_rows": len(replay),
                "replay_seconds": replay_seconds,
                "simulate_rows": len(simulation),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"Captured {len(replay)} replay rows in {replay_seconds:.3f} s")


if __name__ == "__main__":
    main()
