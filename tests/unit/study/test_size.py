"""``gm.study.size`` on the shallow sample."""

import pytest

import gemini as gm
from gemini._utils.files import from_json
from tests.fixtures.errors import raises
from tests.unit.study.conftest import SAMPLE, shallow_case, shallow_plant


def limited(flow_max):
    """Return the constraints of the sample with a maximum production flow of ``flow_max`` m3/h."""
    items = from_json(SAMPLE / "case.json")["constraints"]
    items[0]["max"] = {"value": flow_max, "unit": "m3/h"}
    return items


def test_the_shallow_sample_needs_one_doublet_and_covers_its_peak():
    """One doublet of 4.7 MW at the flow and cooling limits covers the 3.03 MW peak."""
    design = gm.study.size(shallow_plant(), shallow_case())
    notes = {item["path"]: item for item in design.sizing["sized"]}
    assert design.to_dict()["size"] == {"doublets": 1}
    assert notes["size.doublets"]["value"].value == 1
    assert "covers the heating peak" in notes["size.doublets"]["reason"]
    assert 35 / 3600 <= notes["d0.nominal_flow"]["value"].value <= 180 / 3600


def test_the_capacities_follow_the_demand_peaks():
    """The boiler and the heat pump the heating peak, the chiller the cooling peak."""
    case = shallow_case()
    design = gm.study.size(shallow_plant(), case)
    peaks = case.demand.frame.max()
    assert design.get_submodule("peak_boiler").capacity == peaks["heating_demand"]
    assert design.get_submodule("heat_pump").capacity == peaks["heating_demand"]
    assert design.get_submodule("compression_chiller").capacity == peaks["cooling_demand"]
    assert [item["path"] for item in design.sizing["unchanged"]] == ["heat_exchanger"]


def test_a_tighter_flow_limit_asks_for_more_doublets():
    """At 40 m3/h a doublet gives 1.04 MW: three cover the peak."""
    design = gm.study.size(shallow_plant(), shallow_case(constraints=limited(40)))
    assert design.to_dict()["size"] == {"doublets": 3}
    assert design.get_submodule("d2").nominal_flow == pytest.approx(
        3.034e6 / (3 * 1012 * 4217.4 * 22), rel=1e-3
    )


def test_a_peak_no_count_covers_takes_the_largest_and_says_so():
    """At 36 m3/h three doublets do not cover it."""
    design = gm.study.size(shallow_plant(), shallow_case(constraints=limited(36)))
    note = next(item for item in design.sizing["sized"] if item["path"] == "size.doublets")
    assert design.to_dict()["size"] == {"doublets": 3} and "does not cover" in note["reason"]


def test_the_plant_is_not_changed():
    """A new plant."""
    plant = shallow_plant()
    before = plant.to_dict()
    assert gm.study.size(plant, shallow_case()) is not plant and plant.to_dict() == before


def test_a_class_without_the_structural_size_keeps_its_doublets():
    """The count is not chosen; the flows are still sized."""
    design = gm.study.size(gm.plants.get("DoubletHeatPlant"), shallow_case())
    note = next(item for item in design.sizing["sized"] if item["path"] == "size.doublets")
    assert note["value"].value == 1 and "doublet.nominal_flow" in [
        i["path"] for i in design.sizing["sized"]
    ]


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
        gm.study.size(shallow_plant(), case)
    assert refused.value.path == path


def test_the_sized_plant_delivers_the_heating_of_a_short_run(tmp_path):
    """One doublet carries the peak of the first two days, which a real run then delivers."""
    case = shallow_case(days=2, folder=tmp_path)
    design = gm.study.size(shallow_plant(), case)
    assert design.to_dict()["size"] == {"doublets": 1}
    results = gm.simulate(design, case)
    assert gm.evaluate.totals(design, case, results)["heating_coverage"].si == pytest.approx(1.0)
