"""Calibration application, public replay objective and scalar/vector fits."""

import copy

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from gemini.engine.columns import read
from gemini.engine.loader import Aligned
from gemini.engine.step import BindingPlan
from gemini.errors import PhysicsError, ValidationError
from gemini.types import Binding, Stream
from tests.fixtures.errors import raises


def _kwargs(plant, path, row):
    """Return the call keywords of the twin at ``path`` for one row, as the engine builds them."""
    data = gm.Dataset.from_frame(pd.DataFrame([row], index=[pd.Timestamp("2024-01-01", tz="UTC")]))
    (twin,) = BindingPlan(plant, data, "replay", only=[path]).twins
    columns = {column: np.array([value], dtype=object) for column, value in row.items()}
    block = read(twin, Aligned([data.start], np.array([900.0]), columns), 0, 1)
    kwargs = {name: values[0] for name, values in block.inputs.items()}
    for port, fluid in block.fluids.items():
        fields = {name: block.fields[port, name][0] for name in ("m_dot", "T", "p")}
        kwargs[port] = Stream._si(**fields, fluid=fluid)
    return kwargs


def test_hx_apply_and_save(tmp_path, fresh_plant, reference_dataset):
    """Optional application preserves histories and fitted parameters survive replay/save."""
    plant, dataset = fresh_plant, reference_dataset
    dataset = dataset.window(end="2024-06-07T02:45Z")
    before = plant.state_dict()
    fit = gm.analysis.calibrate(
        plant,
        dataset,
        params=[plant.get("heat_exchanger.thermal_conductance")],
        apply=False,
    )
    assert fit.success and fit.rms_after < fit.rms_before / 100
    assert plant.state_dict() == before and not fit.applied
    count = len(plant.heat_exchanger._param_history)
    fitted = gm.analysis.calibrate(
        plant, dataset, params=[plant.get("heat_exchanger.thermal_conductance")]
    )
    gm.replay(plant, dataset)
    assert plant.heat_exchanger.thermal_conductance == fitted.fitted["thermal_conductance"]
    assert len(plant.heat_exchanger._param_history) == count
    plant.to_json(tmp_path / "plant.json")
    loaded = gm.Plant.from_json(tmp_path / "plant.json")
    assert loaded.state_dict() == plant.state_dict()
    assert loaded.heat_exchanger._param_history == plant.heat_exchanger._param_history
    assert loaded.bindings == plant.bindings
    with pytest.raises(ValueError, match="calibratable"):
        gm.analysis.calibrate(
            plant,
            dataset,
            params=[
                plant.get("heat_exchanger.thermal_conductance"),
                plant.get("heat_exchanger.arrangement"),
            ],
        )


def test_esp_head_coefficients(fresh_plant, fast_dataset):
    """Recover a synthetic curve across a broad flow sweep without changing the original."""
    plant, source = fresh_plant, fast_dataset
    first = source.read(source.start, source.start).iloc[0]
    pump = plant.doublet.esp
    original = pump.head_coefficients.copy()
    rows = []
    for flow in np.linspace(90, 160, 16):
        row = first.to_dict()
        row["doublet.esp.suction.m_dot"] = flow / 3600
        kwargs = _kwargs(plant, "doublet.esp", row)
        predicted = pump(**kwargs).outputs
        row["doublet.esp.head"] = predicted.head * 0.8
        row["doublet.esp.discharge_pressure"] = (
            row["doublet.esp.suction.p"] + row["doublet.esp.head"]
        )
        rows.append(row)
    data = gm.Dataset.from_frame(
        pd.DataFrame(rows, index=pd.date_range(source.start, periods=16, freq="15min"))
    )
    fit = gm.analysis.calibrate(
        plant, data, params=[plant.get("doublet.esp.head_coefficients")], apply=False
    )
    assert fit.success and fit.rms_after < 1e-8
    assert pump.head_coefficients == original
    assert fit.observations == 16
    print(fit)


def _head_rows(plant, source, flows, column_scale=1.0):
    """Return synthetic ESP rows whose measured head is 80 % of the model head."""
    first = source.read(source.start, source.start).iloc[0]
    pump = plant.doublet.esp
    bindings = plant.bindings["doublet.esp"]
    column = bindings.inlets["fluid_in"]["m_dot"].column
    rows = []
    for flow in flows:
        row = first.to_dict()
        row[column] = flow * column_scale
        kwargs = _kwargs(plant, "doublet.esp", row)
        row["doublet.esp.head"] = pump(**kwargs).outputs.head * 0.8
        row["doublet.esp.discharge_pressure"] = (
            row["doublet.esp.suction.p"] + row["doublet.esp.head"]
        )
        rows.append(row)
    index = pd.date_range(source.start, periods=len(rows), freq="15min")
    return gm.Dataset.from_frame(pd.DataFrame(rows, index=index))


def test_hx_guess_ignores_rows_without_measured_duty(fresh_plant, reference_dataset):
    """A missing duty observation is left out of the UA guess as it is of the residual."""
    frame = reference_dataset.window(end="2024-06-07T02:45Z").to_frame()
    frame.loc[frame.index[3], "heat_exchanger.duty"] = np.nan
    data = gm.Dataset(frame, reference_dataset.columns)
    ua = fresh_plant.get("heat_exchanger.thermal_conductance")
    fit = gm.analysis.calibrate(fresh_plant, data, params=[ua], apply=False)
    assert fit.success and fit.observations == len(frame) - 1


def test_esp_head_guess_converts_any_mass_flow_unit(fresh_plant, fast_dataset):
    """Mass flows bound in t/h start from the same head-curve guess as flows in kg/s."""
    fits = {}
    for unit, column_scale in (("kg/s", 1.0), ("t/h", 3.6)):
        plant = copy.deepcopy(fresh_plant)
        suction = plant.bindings["doublet.esp"].inlets["fluid_in"]
        suction["m_dot"] = Binding(column=suction["m_dot"].column, unit=unit)
        data = _head_rows(plant, fast_dataset, np.linspace(25, 45, 16), column_scale)
        head = plant.get("doublet.esp.head_coefficients")
        fits[unit] = gm.analysis.calibrate(plant, data, params=[head], apply=False)
    assert fits["t/h"].success and fits["t/h"].rms_after < 1e-8
    assert fits["t/h"].evaluations == fits["kg/s"].evaluations


def test_esp_head_guess_names_too_few_flows(fresh_plant, fast_dataset):
    """Steady flow cannot seed the six-coefficient head guess; the error says so."""
    data = _head_rows(fresh_plant, fast_dataset, [0.03] * 8)
    head = fresh_plant.get("doublet.esp.head_coefficients")
    with raises(PhysicsError, "too_little_data", match="doublet.esp.head_coefficients.*distinct"):
        gm.analysis.calibrate(fresh_plant, data, params=[head], apply=False)


def test_window_before_the_first_snapshot_is_rejected(fresh_plant, reference_dataset):
    """A window starting before every dated design snapshot names the first date."""
    history = fresh_plant.heat_exchanger._param_history
    fresh_plant.heat_exchanger._param_history = [
        history[0].model_copy(update={"valid_from": pd.Timestamp("2024-06-07T01:00Z")})
    ]
    ua = fresh_plant.get("heat_exchanger.thermal_conductance")
    with raises(ValidationError, "invalid_design", match="2024-06-07 01:00"):
        gm.analysis.calibrate(fresh_plant, reference_dataset.window(end="2024-06-07T02:45Z"), [ua])
