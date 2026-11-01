"""Compare the refactored API with the immutable phase-0 result fixtures.

Replay values must agree within one binary64 ULP (``REPLAY_RTOL``), the most a CSV round trip
of the fixture can change them. The committed simulation fixture differs from the results this
code produces by a few ULP in the ESP flow, and pressures that are differences of ~1e7 Pa terms
differ by up to two ULP of 1e7 Pa (3.7e-9 Pa). ``SIMULATE_RTOL`` admits exactly that round-off
and nothing physically visible.

NOTE(refactor): pandas 3 parses decimal text correctly rounded, as pandas 2 did only with
``float_precision="round_trip"``. Its default parser read 44,022 cells of the July CSV (and the
fixture CSVs) differently, by up to 2.3e-15 relative, and cancellation in differences of large
terms amplifies that to 1.7e-13 relative (1.0e-8 W) in injector heat loss and 8.0e-14
(7.7e-7 W/K) in apparent HX UA. pandas 2.3.3 with ``round_trip`` reproduces exactly these
deviations, and its replay is bit-identical to pandas 3's on the same parsed values, so GEMINI's
arithmetic is unchanged. ``PARSER_RTOL`` admits that parsing difference under pandas 3 only;
pandas 2 keeps ``REPLAY_RTOL``.
"""

import ast
import json

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from tests.fixtures import FIXTURES
from tests.fixtures.doublet_day import doublet_day
from tests.fixtures.frames import on_ports, path_frame
from tests.fixtures.old_names import FLUID_NAMES, RENAMED_NAMES, fluid_names

pytestmark = pytest.mark.e2e
BASELINE = FIXTURES / "module_api_baseline"
FAST_BASELINE = FIXTURES / "module_api_fast"
PATH_RENAMES = {"filter_hot": "filters.hot", "filter_return": "filters.cold"}
FIELD_RENAMES = {
    "energy_port_electricity": "electricity",
    "energy_port_fuel": "fuel",
    "energy_port_heat_loss": "heat_loss",
}
REPLAY_RTOL = 2e-15
PARSER_RTOL = 2e-13
SIMULATE_RTOL = 1e-13
TYPE_RENAMES = {
    "doublet_heat": "doublet_heat_plant",
    "heatexchanger": "heat_exchanger",
    "injectionpump": "injection_pump",
    "injectionwell": "injection_well",
    "productionwell": "production_well",
}
NEW_PARAMS = {
    "degasser": {"separation_efficiency": 0.0},
    "doublet": {
        name: None
        for name in (
            "depth",
            "gradient",
            "surface_temperature",
            "permeability",
            "thickness",
            "well_diameter",
            "nominal_flow",
            "pump_efficiency",
            "nominal_wellhead_pressure",
        )
    }
    | {"drainage_radius": 1000.0},
    "injection_pump": {"nominal_flow": None, "nominal_head": None},
}
"""Parameters added after phase 0, as ``None`` (unset), plus the two explicit values."""


def _baseline_frame(directory, name):
    """Read one captured result frame and apply the documented path and field renames."""
    return on_ports(
        pd.read_csv(directory / name, header=[0, 1], index_col=0, parse_dates=True)
        .rename(columns=PATH_RENAMES, level=0)
        .rename(columns=FIELD_RENAMES, level=1)
        .rename(columns=RENAMED_NAMES, level=1)
    )


def _parse_list(cell):
    """Parse a list written to CSV as its Python representation; keep other cells."""
    if isinstance(cell, str) and cell.startswith("["):
        return ast.literal_eval(cell)
    return cell


def _float_rows(series):
    """Return a column of equal-length float lists as a matrix, or ``None`` otherwise."""
    rows = [_parse_list(cell) for cell in series]
    if not all(isinstance(row, list) and row for row in rows):
        return None
    if len({len(row) for row in rows}) != 1:
        return None
    if not all(isinstance(value, float) for row in rows for value in row):
        return None
    return np.array(rows)


def _assert_close(left, right, rtol):
    """Compare floats within ``rtol`` and an absolute floor of 1e-12 SI units."""
    np.testing.assert_allclose(left, right, rtol=rtol, atol=1e-12, equal_nan=True)


def _assert_values_identical(actual, expected, rtol=REPLAY_RTOL):
    """Compare frames: floats and float-list cells within ``rtol``, everything else exactly."""
    actual = actual.reindex(columns=expected.columns)
    assert actual.index.equals(expected.index)
    assert actual.columns.equals(expected.columns)
    for column in expected:
        left, right = actual[column], expected[column]
        if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
            _assert_close(left.to_numpy(), right.to_numpy(), rtol)
            continue
        left_rows, right_rows = _float_rows(left), _float_rows(right)
        if left_rows is not None and right_rows is not None:
            _assert_close(left_rows, right_rows, rtol)
            continue
        pd.testing.assert_series_equal(
            left.astype(object).fillna("<missing>").map(str),
            right.astype(object).fillna("<missing>").map(str),
            check_names=False,
            check_dtype=False,
        )


SECTION_FIELDS = {
    "length": "length",
    "inclination": "inclination",
    "diameter": "inner_diameter",
    "roughness": "roughness",
}
"""Each list of a well's pipe path, with the field of the old section it comes from."""


def test_state_and_full_results_match_phase_zero(dataset_name, selected_dataset, fresh_plant):
    """State, replay and simulation remain numerically identical after documented renames."""
    plant = fresh_plant
    old_state = json.loads((BASELINE / "state_dict.json").read_text())
    new_state = plant.state_dict()
    for old_path, old in old_state.items():
        new = new_state[PATH_RENAMES.get(old_path, old_path)]
        assert TYPE_RENAMES.get(old["type"], old["type"]) == new["type"]
        old_params = {RENAMED_NAMES.get(key, key): value for key, value in old["params"].items()}
        old_params.pop("coefficient_precision", None)
        old_params = {key: value for key, value in old_params.items() if key not in FLUID_NAMES}
        if "path" in old_params:
            sections = old_params.pop("path")["sections"]
            old_params |= {
                f"section_{name}": [section[field] for section in sections]
                for name, field in SECTION_FIELDS.items()
            }
        assert old_params | NEW_PARAMS.get(old_path, {}) == new["params"]
        assert fluid_names(old["fluid"]) == new["fluid"]

    replay = path_frame(gm.replay(plant, selected_dataset))
    baseline = BASELINE if dataset_name == "slow" else FAST_BASELINE
    rtol = PARSER_RTOL if int(pd.__version__.split(".")[0]) >= 3 else REPLAY_RTOL
    _assert_values_identical(replay, _baseline_frame(baseline, "replay.csv.gz"), rtol)

    clock, plan = doublet_day()
    simulation = path_frame(gm.simulate(plant, plan=plan, clock=clock))
    _assert_values_identical(
        simulation, _baseline_frame(BASELINE, "simulate.csv.gz"), SIMULATE_RTOL
    )
