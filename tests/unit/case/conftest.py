"""A small full case, as a dictionary and as files, shared by the case tests."""

import numpy as np
import pandas as pd
import pytest

DAYS = 7


@pytest.fixture
def folder(tmp_path):
    """Return a folder holding the demand CSV of a week at one day."""
    days = pd.date_range("2027-01-01", periods=DAYS, freq="D")
    frame = pd.DataFrame(
        {
            "date": days.strftime("%Y-%m-%d"),
            "heat_MW": np.linspace(1, 4, DAYS),
            "cold_MW": np.linspace(0.5, 2, DAYS),
        }
    )
    frame.to_csv(tmp_path / "demand.csv", index=False)
    return tmp_path


def environment():
    """Return the environment section."""
    return {
        "ground": {
            "surface_temperature": {"value": 12, "unit": "degC"},
            "gradient": {"value": 30, "unit": "K/km"},
        },
        "reservoir": {
            "reference_depth": {"value": 2500, "unit": "m"},
            "thickness": {"value": 100, "unit": "m"},
            "permeability": {"value": 200, "unit": "mD"},
            "pressure": {"value": 250, "unit": "barg"},
        },
        "fluid": {
            "density": {"value": 1030, "unit": "kg/m3"},
            "viscosity": {"value": 0.4, "unit": "mPa.s"},
            "gas_liquid_ratio": {"value": 0.8, "unit": "Nm3/m3"},
            "gas": {"CH4": 0.8, "CO2": 0.2},
        },
        "air": {"temperature": {"value": 10, "unit": "degC"}},
    }


def demand():
    """Return the demand section."""
    return {
        "file": "demand.csv",
        "time_column": "date",
        "heating": {
            "column": "heat_MW",
            "unit": "MW",
            "supply_temperature": {"value": 100, "unit": "degC"},
            "return_temperature": {"value": 60, "unit": "degC"},
        },
        "cooling": {
            "column": "cold_MW",
            "unit": "MW",
            "supply_temperature": {"value": 20, "unit": "degC"},
            "return_temperature": {"value": 25, "unit": "degC"},
        },
    }


def constraints():
    """Return the constraints section."""
    flow = {"on": "doublet", "quantity": "production_flow", "when": "running"}
    return [
        flow
        | {
            "over": "each",
            "min": {"value": 50, "unit": "m3/h"},
            "max": {"value": 300, "unit": "m3/h"},
        },
        {"on": "doublet", "quantity": "pump_efficiency", "equals": 0.7},
        flow | {"over": "duration", "max": {"value": 5, "unit": "d"}},
    ]


def finance():
    """Return the finance assumptions."""
    return {
        "currency": "EUR",
        "discount_rate": 0.05,
        "lifetime": {"value": 25, "unit": "yr"},
        "price_year": 2015,
        "capex": {
            "drilling": {"value": 1239, "unit": "EUR/m"},
            "heat_pump": {"value": 0.67, "unit": "EUR/W"},
            "heat_exchanger": {"value": 0.5, "unit": "EUR/(W/K)"},
            "degasser": {"value": 1000000, "unit": "EUR"},
        },
        "opex": {
            "fixed": {"heat_pump": {"value": 2, "unit": "%/yr"}},
            "electricity": {"value": 100, "unit": "EUR/MWh"},
            "co2": {"value": 80, "unit": "EUR/t"},
        },
        "revenue": {"heat": {"value": 60, "unit": "EUR/MWh"}},
        "allocation": {"heat_cost_share": 0.8},
    }


@pytest.fixture
def data():
    """Return the dictionary of a full case, as ``case.json`` writes it."""
    return {
        "time": {"start": "2027-01-01", "end": "2027-01-08", "step": {"value": 1, "unit": "d"}},
        "environment": environment(),
        "demand": demand(),
        "choices": {
            "doublets": {"min": 1, "max": 3},
            "depth": {"min": {"value": 2000, "unit": "m"}, "max": {"value": 3500, "unit": "m"}},
        },
        "constraints": constraints(),
        "assumptions": {
            "finance": finance(),
            "emissions": {
                "CO2": {"electricity": {"value": 300, "unit": "g/kWh"}},
                "CH4": {"gwp": 29.8},
            },
        },
    }
