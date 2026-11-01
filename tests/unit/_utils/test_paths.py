"""The data folders are found here; ``inputs/`` raises a clear error when it is absent."""

import pytest

import gemini as gm
from gemini._utils import paths


def test_the_package_finds_its_folders():
    """``inputs/`` is next to the package."""
    assert paths.INPUTS.parent == paths.PACKAGE.parent


@pytest.mark.parametrize(
    ("call", "name"),
    [
        (lambda: paths.plant_values("Doublet"), "plants/Doublet.json"),
        (lambda: paths.doublet_heat("data.csv"), "doublet_heat/data.csv"),
    ],
)
def test_each_folder_of_the_inputs_lies_below_them(tmp_path, monkeypatch, call, name):
    """Each function gives its file, and without the folder an error that names the file."""
    monkeypatch.setattr(paths, "INPUTS", tmp_path)
    assert call() == tmp_path / name
    monkeypatch.setattr(paths, "INPUTS", tmp_path / "absent")
    with pytest.raises(gm.errors.RunError, match="source checkout") as caught:
        call()
    assert caught.value.code == "inputs_missing"
    assert caught.value.path == name
    assert name in str(caught.value)
