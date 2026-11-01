"""Cases for the tests of what reads a finished run."""

import tempfile
from datetime import timedelta
from pathlib import Path

import pandas as pd

import gemini as gm
from gemini.units import Quantity
from tests.fixtures.result_tables import START


def make_case(count=24, step=3600.0, finance=None, emissions=None, supply=None, **sections):
    """Return a case of ``count`` steps of ``step`` seconds, as ``make_results`` makes a run.

    ``finance`` and ``emissions`` are the arguments of ``gm.case.Finance`` and
    ``gm.case.Emissions``; ``supply`` is ``{"heating": Quantity, "cooling": Quantity}``, the supply
    temperatures of services whose demand is 1 W; ``sections`` are the other arguments of
    ``gm.Case``, such as ``constraints``.
    """
    sections.setdefault("environment", make_environment())
    if supply is not None:
        sections["demand"] = _demand(count, step, supply)
    parts = {}
    if finance is not None:
        parts["finance"] = gm.case.Finance(**finance)
    if emissions is not None:
        parts["emissions"] = gm.case.Emissions(**emissions)
    if parts:
        sections["assumptions"] = gm.case.Assumptions(**parts)
    time = gm.case.Time(
        start=START, end=START + timedelta(seconds=step * count), step=Quantity(step, "s")
    )
    return gm.Case(time=time, **sections)


def costed_finance(opex=None, revenue=None, **parts):
    """Return the ``finance`` of a case for the plants of ``costed_plants``.

    The heat consumer is a degasser of 1000 with a fixed opex of 1 %/yr (10 a year) and the cooling
    consumer a flare of 2000 at 3 %/yr (60 a year). ``opex`` and ``revenue`` are the prices, as
    keyword arguments of ``gm.case.Opex`` and ``gm.case.Revenue``; ``parts`` are the other
    arguments of ``gm.case.Finance``.
    """
    shares = {"degasser": Quantity(1, "%/yr"), "flare": Quantity(3, "%/yr")}
    finance = {
        "capex": gm.case.Capex(
            degasser=Quantity(1000.0, "currency"), flare=Quantity(2000.0, "currency")
        ),
        "opex": gm.case.Opex(fixed=shares, **(opex or {})),
    }
    if revenue:
        finance["revenue"] = gm.case.Revenue(**revenue)
    return finance | parts


def _demand(count, step, supply):
    """Return a demand of 1 W for each service of ``supply``, read from a temporary file."""
    index = pd.date_range(START, periods=count, freq=timedelta(seconds=step))
    frame = pd.DataFrame({"time": index.strftime("%Y-%m-%dT%H:%M:%S")})
    for service in supply:
        frame[f"{service}_W"] = 1.0
    with tempfile.TemporaryDirectory() as folder:
        frame.to_csv(Path(folder) / "demand.csv", index=False)
        services = {
            service: gm.case.Service(column=f"{service}_W", unit="W", supply_temperature=value)
            for service, value in supply.items()
        }
        return gm.case.Demand(file=str(Path(folder) / "demand.csv"), time_column="time", **services)


def make_environment():
    """Return the environment of a case with a doublet: ground, reservoir, brine and air."""
    return gm.case.Environment(
        ground=gm.case.Ground(
            surface_temperature=Quantity(12, "degC"), gradient=Quantity(30, "K/km")
        ),
        reservoir=gm.case.Reservoir(
            reference_depth=Quantity(2500, "m"),
            thickness=Quantity(100, "m"),
            permeability=Quantity(200, "mD"),
            pressure=Quantity(250, "barg"),
        ),
        fluid=gm.case.Fluid(
            density=Quantity(1030, "kg/m3"),
            viscosity=Quantity(0.4, "mPa.s"),
            gas_liquid_ratio=Quantity(0.8, "Nm3/m3"),
            gas={"CH4": 0.8, "CO2": 0.2},
        ),
        air=gm.case.Air(temperature=Quantity(10, "degC")),
    )
