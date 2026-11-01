"""``gm.study.size`` on the shallow sample."""

import pandas as pd
import pytest

import gemini as gm
from gemini._utils.files import from_json
from tests.fixtures.errors import raises
from tests.fixtures.sample_cases import HACKATHON_2026 as HACKATHON
from tests.unit.study.conftest import SAMPLE, shallow_case, shallow_plant


def limited(flow_max):
    """Return the constraints of the sample with a maximum production flow of ``flow_max`` m3/h."""
    items = from_json(SAMPLE / "case.json")["constraints"]
    items[0]["max"] = {"value": flow_max, "unit": "m3/h"}
    for item in items:
        if item.get("over") == "duration":
            item["max"]["value"] = 20
    return items


def quick(folder, **sections):
    """Return the shallow sample case cut to one day, so that ``size`` simulates it fast."""
    return shallow_case(days=1, folder=folder, **sections)


class Sized:
    """A plant sized once for a module: its case, the design and the shares of its run."""

    def __init__(self, folder, plant=None, backup="peak", scale=1.0, **sections):
        self.case = quick(folder, **sections)
        self.case.demand.frame[["heating_demand", "cooling_demand"]] *= scale
        self.plant = plant or shallow_plant()
        self.before = self.plant.to_dict()
        self.design = gm.study.size(self.plant, self.case, backup=backup)
        self.notes = self.design.sizing
        self.by_path = {item["path"]: item for item in self.notes["sized"]}

    def shares(self):
        """Return ``gm.evaluate.capacities`` of the design on its case."""
        results = gm.simulate(self.design, self.case)
        return gm.evaluate.capacities(self.design, self.case, results)

    def capacity(self, path):
        """Return the capacity of the module at ``path``."""
        return self.design.get_submodule(path).capacity


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """The shallow sample sized with the whole-peak policy."""
    return Sized(tmp_path_factory.mktemp("base"))


@pytest.fixture(scope="module")
def none(tmp_path_factory):
    """The shallow sample sized with no backup policy."""
    return Sized(tmp_path_factory.mktemp("none"), backup="none")


@pytest.fixture(scope="module")
def tight(tmp_path_factory):
    """A flow limit of 40 m3/h: three doublets."""
    return Sized(tmp_path_factory.mktemp("tight"), constraints=limited(40))


@pytest.fixture(scope="module")
def short(tmp_path_factory):
    """A flow limit of 36 m3/h and twice the demand: three doublets do not cover the peak."""
    return Sized(tmp_path_factory.mktemp("short"), scale=2.0, constraints=limited(36))


@pytest.fixture(scope="module")
def half(tmp_path_factory):
    """The shallow sample with half its demand."""
    folder = tmp_path_factory.mktemp("half")
    return Sized(folder, scale=0.5)


@pytest.fixture(scope="module")
def hot(tmp_path_factory):
    """A reservoir hotter than the supply temperature."""
    ground = {
        "ground": {
            "surface_temperature": {"value": 60, "unit": "degC"},
            "gradient": {"value": 36, "unit": "K/km"},
        }
    }
    environment = from_json(SAMPLE / "case.json")["environment"] | ground
    return Sized(tmp_path_factory.mktemp("hot"), environment=environment)


@pytest.fixture(scope="module")
def column(tmp_path_factory):
    """A wellhead pressure above what the aquifer needs: the column injects alone."""
    plant = shallow_plant()
    plant.set_params("d0", {"nominal_wellhead_pressure": gm.units.Quantity(300, "bar")})
    return Sized(tmp_path_factory.mktemp("column"), plant=plant)


@pytest.fixture(scope="module")
def catalogue(tmp_path_factory):
    """A catalogue plant that states no design value: it cannot be simulated."""
    return Sized(tmp_path_factory.mktemp("catalogue"), plant=gm.plants.get("DoubletHeatPlant"))




def test_the_shallow_sample_needs_one_doublet_and_covers_its_peak(tmp_path):
    """One doublet of 4.7 MW at the flow and cooling limits covers the 3.03 MW peak."""
    design = gm.study.size(shallow_plant(), quick(tmp_path), backup="peak")
    notes = {item["path"]: item for item in design.sizing["sized"]}
    assert design.to_dict()["size"] == {"doublets": 1}
    assert notes["size.doublets"]["value"].value == 1
    assert "covers the heating peak" in notes["size.doublets"]["reason"]
    assert 35 / 3600 <= notes["d0.nominal_flow"]["value"].value <= 180 / 3600


def test_the_shallow_sample_needs_one_doublet_and_covers_its_peak(base):
    """One doublet of 4.7 MW at the flow and cooling limits covers the 3.03 MW peak."""
    assert base.design.to_dict()["size"] == {"doublets": 1}
    assert base.by_path["size.doublets"]["value"].value == 1
    assert "covers the heating peak" in base.by_path["size.doublets"]["reason"]


def test_a_doublet_is_rated_for_the_flow_limit_of_the_case(base):
    """The largest flow the case lets it run: 180 m3/h on the sample."""
    assert base.by_path["d0.nominal_flow"]["value"].value == pytest.approx(180 / 3600)


def share_of(case, depth_m):
    """Return the part of the heating peak that the reservoir at ``depth_m`` cannot reach."""
    heating = case.demand.heating
    reservoir = case.environment.temperature_at(depth_m)
    return (heating.supply_temperature - reservoir) / (
        heating.supply_temperature - heating.return_temperature
    )


def test_the_capacities_follow_the_demand_peaks(base):
    """The boiler the heating peak, the heat pump its share of it, the chiller the cooling peak."""
    peaks = base.case.demand.frame.max()
    share = share_of(base.case, base.design.get_submodule("d0").depth)
    assert 0 < share < 1
    assert base.capacity("peak_boiler") == peaks["heating_demand"]
    assert base.capacity("heat_pump") == pytest.approx(share * peaks["heating_demand"])
    assert base.capacity("compression_chiller") == peaks["cooling_demand"]
    assert [item["path"] for item in base.notes["unchanged"]] == ["heat_exchanger"]


def test_a_tighter_flow_limit_asks_for_more_doublets(tight):
    """At 40 m3/h a doublet gives 1.04 MW: three cover the peak."""
    assert tight.design.to_dict()["size"] == {"doublets": 3}
    assert tight.design.get_submodule("d2").nominal_flow == pytest.approx(40 / 3600)


def test_a_peak_no_count_covers_takes_the_largest_and_says_so(short):
    """At 36 m3/h and twice the demand three doublets do not cover it."""
    assert short.design.to_dict()["size"] == {"doublets": 3}
    assert "does not cover" in short.by_path["size.doublets"]["reason"]


def test_the_plant_is_not_changed(base):
    """A new plant."""
    assert base.design is not base.plant and base.plant.to_dict() == base.before


def test_the_sized_plant_is_simulated_once_and_the_notes_hold_no_break(base):
    """The shallow sample's design meets its constraints."""
    assert base.notes["simulation"] == "simulated" and base.notes["broken"] == []


def test_a_class_without_the_structural_size_keeps_its_doublets(catalogue):
    """The count is not chosen; the flows are still sized."""
    assert catalogue.by_path["size.doublets"]["value"].value == 1
    assert "doublet.nominal_flow" in catalogue.by_path


@pytest.mark.parametrize(
    ("sections", "path"),
    [
        ({"constraints": limited(180)[1:]}, "constraints"),
        ({"demand": None}, "demand"),
    ],
)
def test_what_the_case_lacks_is_named(sections, path):
    """``missing_value`` with the path."""
    data = from_json(SAMPLE / "case.json") | sections
    data = {key: value for key, value in data.items() if value is not None}
    data["choices"] = {"doublets": {"min": 1, "max": 3}}
    case = gm.Case.from_dict(data, SAMPLE)
    with raises(gm.errors.ValidationError, "missing_value") as refused:
        gm.study.size(shallow_plant(), case, backup="peak")
    assert refused.value.path == path


def test_a_lower_peak_gives_smaller_units(base, half):
    """Halving the demand halves the boiler, the heat pump and the chiller."""
    for name in ("peak_boiler", "heat_pump", "compression_chiller"):
        assert half.capacity(name) < base.capacity(name)
    assert half.design.get_submodule("d0").nominal_flow <= base.design.get_submodule(
        "d0"
    ).nominal_flow


def test_a_heat_pump_gets_its_share_not_the_peak(base):
    """Less than the peak, shared by the units of the role, and below the boiler."""
    assert base.capacity("heat_pump") < base.capacity("peak_boiler")


def test_a_reservoir_hotter_than_the_supply_leaves_the_heat_pump_unsized(hot):
    """No heat pump is needed: it stays as stored and a note says why."""
    stored = hot.plant.get_submodule("heat_pump").capacity
    assert hot.capacity("heat_pump") == stored
    notes = {item["path"]: item for item in hot.notes["unchanged"]}
    assert "hotter" in notes["heat_pump"]["reason"]


def test_a_searched_capacity_replaces_the_sized_one(runs, base):
    """The search varies ``heat_pump.capacity`` of the sized plant within its bounds."""
    variables = [
        {
            "path": "heat_pump",
            "parameter": "capacity",
            "lower": gm.units.Quantity(0.1, "MW"),
            "upper": gm.units.Quantity(0.5, "MW"),
        }
    ]
    result = gm.study.minimize(base.design, base.case, "lcts", variables, evaluations=5)
    found = result["best"]["plant"].get_submodule("heat_pump").capacity
    assert 0.1e6 <= found <= 0.5e6
    assert found != base.capacity("heat_pump")


def pump_notes(sized):
    """Return the sized value of each note of the injection pump, in SI."""
    return {
        path: item["value"].value
        for path, item in sized.by_path.items()
        if path.startswith("injection_pump.")
    }


def test_the_injection_pump_is_rated_for_the_flow_of_the_doublets_it_serves(tight):
    """Three doublets share one pump: its flow is theirs together."""
    flows = [tight.design.get_submodule(f"d{i}").nominal_flow for i in range(3)]
    assert pump_notes(tight)["injection_pump.nominal_flow"] == pytest.approx(sum(flows))
    assert tight.design.get_submodule("injection_pump").nominal_flow == pytest.approx(sum(flows))


def test_the_injection_pump_is_rated_for_the_pressure_the_aquifer_needs_above_the_suction(base):
    """One doublet of 180 m3/h at 8 bar of suction needs more than the column gives."""
    assert 0 < pump_notes(base)["injection_pump.nominal_head"] < 100e5


def test_a_column_that_injects_alone_asks_no_head(column):
    """A suction above the pressure the aquifer needs: the head is floored at zero."""
    assert pump_notes(column)["injection_pump.nominal_head"] == 0.0


def test_a_pump_whose_doublet_lacks_a_design_value_is_left_unsized_with_a_note(catalogue):
    """The stored catalogue plant states no depth: the pump is listed as unchanged."""
    unchanged = {item["path"]: item["reason"] for item in catalogue.notes["unchanged"]}
    assert "doublet.depth is missing" in unchanged["injection_pump"]
    assert catalogue.design.get_submodule("injection_pump").nominal_flow is None
    assert catalogue.notes["simulation"].startswith("not simulated")
    assert catalogue.notes["broken"] == []


def test_a_missing_backup_policy_is_named():
    """The policy is a design decision: no default, ``missing_value`` naming ``backup``."""
    with raises(gm.errors.ValidationError, "missing_value") as refused:
        gm.study.size(shallow_plant(), shallow_case())
    assert refused.value.path == "backup"


def test_an_unknown_backup_policy_is_refused():
    """Only ``none`` and ``peak`` exist."""
    with raises(gm.errors.ValidationError, "invalid_value") as refused:
        gm.study.size(shallow_plant(), shallow_case(), backup="half")
    assert refused.value.path == "backup"


def test_no_backup_gives_a_smaller_boiler_than_the_peak(base, none):
    """``none`` covers only what the doublets cannot reach; ``peak`` the whole peak."""
    assert 0 < none.capacity("peak_boiler") < base.capacity("peak_boiler")
    assert none.capacity("heat_pump") == base.capacity("heat_pump")


def test_every_rated_pump_covers_the_duty_of_its_run(tight):
    """The doublets are rated at the flow limit: no share is above one."""
    shares = tight.shares()
    for path in ("d0", "d1", "d2"):
        assert shares[path]["share"].value <= 1 + 1e-9


def test_a_broken_constraint_is_listed_with_its_role_quantity_value_limit_and_step(short):
    """The notes hold what the design breaks, in the shape of ``gm.evaluate.constraints``."""
    for item in short.notes["broken"]:
        assert {"role", "quantity", "value", "limit", "worst_step", "unit_path"} <= set(item)


def cooling_peak_case(folder, days=1, winter=True):
    """Return the competition-sample case cut to the ``days`` from its cooling peak.

    With ``winter`` the heating demand is the year's peak every day.
    """
    data = from_json(HACKATHON / "case.json")
    frame = pd.read_csv(HACKATHON / data["demand"]["file"])
    at = int(frame["cooling_demand_MWcool"].idxmax())
    winter_peak = frame["heating_demand_MWth"].max()
    frame = frame.iloc[at : at + days]
    if winter:
        frame = frame.assign(heating_demand_MWth=winter_peak)
    frame.to_csv(folder / data["demand"]["file"], index=False)
    data["time"]["start"] = str(frame["date"].iloc[0])
    data["time"]["end"] = str(pd.Timestamp(frame["date"].iloc[-1]) + pd.Timedelta(days=1))[:10]
    for item in data["constraints"]:
        if item.get("over") == "duration":
            item["max"]["value"] = days
    return gm.Case.from_dict(data, folder)


@pytest.fixture(scope="module")
def series(tmp_path_factory):
    """The sample plant with three chillers in series, sized on the days of its cooling peak."""
    case = cooling_peak_case(tmp_path_factory.mktemp("series"))
    plant = gm.Plant.from_json(HACKATHON / "plants/HeatingFullCoolingPlant.json")
    return gm.study.size(plant, case, backup="peak")


def test_chillers_in_series_deliver_the_cooling_supply_at_the_peak(series):
    """A sorption unit delivers less than its rating when its characteristic map says so; the
    chiller that closes the series is rated for the whole peak and makes up the difference."""
    assert [item for item in series.sizing["broken"] if item["quantity"] == "temperature"] == []
    assert series.get_submodule("compression_chiller").capacity == pytest.approx(10e6)


@pytest.fixture(scope="module", params=["none", "peak"])
def driven(request, tmp_path_factory):
    """The sample plant on the cooling-peak day with its own, small heating demand."""
    case = cooling_peak_case(tmp_path_factory.mktemp("driven"), winter=False)
    plant = gm.Plant.from_json(HACKATHON / "plants/HeatingFullCoolingPlant.json")
    return request.param, case, gm.study.size(plant, case, backup=request.param)


def test_the_boiler_is_rated_for_the_heating_and_the_drive_heat_of_the_sorption_chillers(driven):
    """The sorption units draw their generator heat from the boiler: it adds to the heating.

    ``none`` assumes an ideal exchanger, so it may break the supply, which the notes then list."""
    backup, case, design = driven
    heating = case.demand.frame["heating_demand"].max()
    assert design.sizing["simulation"] == "simulated"
    if backup == "peak":
        assert design.get_submodule("peak_boiler").capacity > heating
        assert [i for i in design.sizing["broken"] if i["role"] == "heating_supply"] == []
