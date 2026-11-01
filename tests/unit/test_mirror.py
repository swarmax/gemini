"""Enforce one mirrored unit-test module with real tests for every source file.

Every ``gemini/<path>/<name>.py`` except ``__init__.py`` (including ``gemini/_utils/`` and
``gemini/errors/``) needs ``tests/unit/<path>/test_<name>.py`` defining at least one test
function.
"""

import ast

from tests.fixtures import ROOT

SOURCE = ROOT / "gemini"
UNIT_TESTS = ROOT / "tests/unit"


def _mirror(source):
    """Return the unit-test path that mirrors one source file."""
    relative = source.relative_to(SOURCE)
    return UNIT_TESTS / relative.parent / f"test_{relative.name}"


def _defines_test(path):
    """Whether a test module defines a test function at module level or in a class."""
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
        for node in ast.walk(ast.parse(path.read_text()))
    )


def _mirrors():
    """Yield every source file except package markers with its expected mirror path."""
    for source in sorted(SOURCE.rglob("*.py")):
        if source.name != "__init__.py":
            yield source, _mirror(source)


def test_source_files_have_mirrored_unit_tests():
    """Every source file has a mirrored unit-test module."""
    missing = [
        str(source.relative_to(SOURCE)) for source, mirror in _mirrors() if not mirror.exists()
    ]
    assert missing == []


def test_mirrored_unit_tests_define_tests():
    """Every mirror defines at least one test function."""
    empty = [
        str(mirror.relative_to(UNIT_TESTS))
        for _, mirror in _mirrors()
        if mirror.exists() and not _defines_test(mirror)
    ]
    assert empty == []
