"""Development-profile test selection follows changed files and their importers."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[3] / "scripts/test_changed.py"
SPEC = importlib.util.spec_from_file_location("test_changed", SCRIPT)
test_changed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(test_changed)

FILES = {
    "gemini/__init__.py": "",
    "gemini/engine/__init__.py": "",
    "gemini/engine/base.py": "",
    "gemini/engine/user.py": "from .base import thing\n",
    "gemini/engine/other.py": "",
    "tests/__init__.py": "",
    "tests/conftest.py": "import gemini.engine.other\n",
    "tests/unit/conftest.py": "DATA = paths.shared('data.csv')\n",
    "tests/unit/engine/test_base.py": "",
    "tests/unit/engine/test_user.py": "",
    "tests/unit/engine/test_other.py": "",
    "tests/integration/test_flow.py": "from gemini.engine import user\n",
    "tests/e2e/test_examples.py": "",
    "examples/recipes/demo.py": "import gemini\n",
    "examples/README.md": "# Examples\n",
    "inputs/shared/data.csv": "time\n",
    "inputs/project/well.param": "{}\n",
    "inputs/plants/Plant.json": "{}\n",
    "tests/fixtures/__init__.py": "PROJECT = paths.project()\n",
    "tests/integration/test_project.py": "from tests.fixtures import PROJECT\n",
    "tests/integration/test_example.py": "example_plant('Plant')\n",
}


@pytest.fixture
def repository(tmp_path):
    """Write a small repository tree and return its root."""
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    return tmp_path


def select(repository, *changed):
    """Return the selected test paths for some changed files."""
    graph = test_changed.import_graph(repository)
    return test_changed.select_tests(list(changed), graph, repository)


def test_module_names_and_parent_packages():
    """Paths map to dotted names, and importing a module imports its packages."""
    assert test_changed.module_name("gemini/engine/user.py") == "gemini.engine.user"
    assert test_changed.module_name("gemini/engine/__init__.py") == "gemini.engine"
    assert test_changed.module_name("docs/index.rst") is None
    assert test_changed.with_parents("a.b.c") == {"a", "a.b", "a.b.c"}


def test_relative_and_from_imports_resolve():
    """Relative imports resolve against the importing package."""
    names = test_changed.imported_names("from .base import thing\n", "gemini.engine.user", False)
    assert {"gemini.engine.base", "gemini.engine.base.thing", "gemini"} <= names
    names = test_changed.imported_names("from . import base\n", "gemini.engine", True)
    assert "gemini.engine.base" in names


def test_changed_module_selects_mirror_and_transitive_importers(repository):
    """A base change reaches its mirror, the importing module's mirror and importing tests."""
    selected = select(repository, "gemini/engine/base.py")
    assert set(selected) == {
        "tests/unit/engine/test_base.py",
        "tests/unit/engine/test_user.py",
        "tests/integration/test_flow.py",
    }
    assert "gemini/engine/base.py" in selected["tests/integration/test_flow.py"]


def test_conftest_imports_are_not_followed(repository):
    """A module imported only by a conftest selects its own mirror, not the whole suite."""
    assert set(select(repository, "gemini/engine/other.py")) == {"tests/unit/engine/test_other.py"}


def test_package_init_change_selects_everything_importing_it(repository):
    """Every import of a subpackage also imports the root package."""
    selected = select(repository, "gemini/__init__.py")
    assert "tests/integration/test_flow.py" in selected
    assert "tests/unit/engine/test_user.py" in selected


def test_configuration_and_conftest_scopes(repository):
    """Root configuration selects all tests; a nested conftest selects its directory."""
    every_test = {path for path in FILES if test_changed.is_test_file(path)}
    assert set(select(repository, "pyproject.toml")) == every_test
    assert set(select(repository, "tests/unit/conftest.py")) == {
        path for path in every_test if path.startswith("tests/unit/")
    }


def test_test_files_examples_and_data_files(repository):
    """Changed tests run themselves, examples run the example test, data selects its readers."""
    assert set(select(repository, "tests/unit/engine/test_base.py")) == {
        "tests/unit/engine/test_base.py"
    }
    assert "tests/e2e/test_examples.py" in select(repository, "examples/recipes/demo.py")
    assert "tests/e2e/test_examples.py" in select(repository, "examples/README.md")
    assert set(select(repository, "inputs/shared/data.csv")) == {
        path for path in FILES if test_changed.is_test_file(path) and "tests/unit/" in path
    } | {"tests/e2e/test_examples.py"}
    assert set(select(repository, "inputs/project/well.param")) == {
        "tests/integration/test_project.py",
        "tests/e2e/test_examples.py",
    }
    assert set(select(repository, "inputs/plants/Plant.json")) == {
        "tests/integration/test_example.py",
        "tests/e2e/test_examples.py",
    }
    assert select(repository, "docs/index.rst") == {}


def test_code_quality_tests_always_run(repository):
    """The code-quality test is selected with its reason, also when nothing else is."""
    quality = test_changed.QUALITY_TEST
    (repository / quality).parent.mkdir(parents=True, exist_ok=True)
    (repository / quality).write_text("")
    assert select(repository, "docs/index.rst") == {quality: test_changed.QUALITY_REASON}
    assert select(repository) == {quality: test_changed.QUALITY_REASON}
    chosen = select(repository, "gemini/engine/other.py")
    assert chosen[quality] == test_changed.QUALITY_REASON
    assert "tests/unit/engine/test_other.py" in chosen
    assert select(repository, quality)[quality] == "changed test file"


def test_deleted_module_still_selects_its_importers(repository):
    """Importers of a deleted module are selected so their failures show up."""
    (repository / "gemini/engine/base.py").unlink()
    assert "tests/integration/test_flow.py" in select(repository, "gemini/engine/base.py")


def test_import_graph_cache_is_reused_and_refreshed(repository):
    """Unchanged files reuse the cache; edited files are parsed again."""
    cache = repository / ".tmp/imports.json"
    first = test_changed.import_graph(repository, cache)
    assert cache.exists()
    (repository / "gemini/engine/other.py").write_text("import gemini.engine.base\n")
    second = test_changed.import_graph(repository, cache)
    assert "gemini.engine.base" not in first["gemini/engine/other.py"]
    assert "gemini.engine.base" in second["gemini/engine/other.py"]


def test_pytest_command_uses_development_profile():
    """The selection runs in parallel on fast data and leaves slow tests to release."""
    command = test_changed.pytest_command(["tests/unit/engine/test_base.py"], ["-x"])
    assert command[1:] == [
        "-m",
        "pytest",
        "-n",
        "auto",
        "-m",
        "not slow",
        "--dataset=fast",
        "--profile=development",
        "-x",
        "tests/unit/engine/test_base.py",
    ]
