"""Generate the July 2024 fast dataset and its unchanged-code replay golden.

Run from the repository root as ``PYTHONPATH=. python tests/fixtures/generate_fast_fixtures.py``;
it overwrites both committed files in place, so run it only for a reviewed numerical change. The
dataset slice is reproduced byte for byte. The replay golden was written in another numeric
environment: regenerating it here, even at its capture commit 56d90be, changes 401 rows by a few
ULP, which the e2e comparison tolerates. Under pandas 3 its correctly rounded CSV parser changes
the replay by up to 1.7e-13 relative, which ``PARSER_RTOL`` tolerates. A changed golden is
evidence of a numerical change, never a routine update (see ``.claude/docs/testing.md``).
"""

import pandas as pd

import gemini as gm
from gemini._utils import paths
from tests.fixtures import FIXTURES
from tests.fixtures.frames import path_frame
from tests.fixtures.sample_cases import example_plant

SOURCE = paths.doublet_heat("doublet_2024_15min.csv")
FAST = paths.doublet_heat("doublet_2024_15min_month.csv")
GOLDEN = FIXTURES / "module_api_fast/replay.csv.gz"


def generate_dataset():
    """Copy July rows byte-for-byte from the immutable full dataset."""
    lines = SOURCE.read_text().splitlines(keepends=True)
    selected = [lines[0], *(line for line in lines[1:] if line.startswith("2024-07-"))]
    FAST.write_text("".join(selected))


def generate_golden():
    """Replay the generated month and save its exact result frame."""
    frame = pd.read_csv(FAST, parse_dates=["time"])
    data = gm.Dataset.from_frame(frame, time_column="time")
    plant = example_plant("DoubletHeatPlant")
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    path_frame(gm.replay(plant, data)).to_csv(GOLDEN, compression={"method": "gzip", "mtime": 0})


if __name__ == "__main__":
    generate_dataset()
    generate_golden()
