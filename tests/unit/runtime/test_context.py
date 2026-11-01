"""Context-local runtime settings."""

from concurrent.futures import ThreadPoolExecutor

import gemini as gm
from gemini.errors import ValidationError
from tests.fixtures.errors import raises


def test_settings_restore_and_context_isolation():
    """Temporary settings restore and separate copied thread contexts."""
    assert gm.runtime.get_precision() == "float64"
    with gm.runtime.settings(precision="float32", display_units="field"):
        assert gm.runtime.get_precision() == "float32"
        assert gm.runtime.get_display_units() == "field"
    assert gm.runtime.get_precision() == "float64"
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda _: gm.runtime.get_precision(), range(2)))
    assert values == ["float64", "float64"]


def test_state_round_trip():
    """Serializable runtime state restores all settings through ``settings``."""
    before = gm.runtime.state()
    with gm.runtime.settings(display_units="field"):
        with gm.runtime.settings(**before):
            assert gm.runtime.state() == before
    assert gm.runtime.state() == before


def test_unknown_settings_are_rejected():
    """A misspelled setting raises with a suggestion instead of doing nothing."""
    with raises(ValidationError, "unknown_name", match="did you mean 'precision'"):
        with gm.runtime.settings(precison="float32"):
            pass
    with raises(ValidationError, "unknown_name", match="float16"):
        with gm.runtime.settings(precision="float16"):
            pass
    assert gm.runtime.get_precision() == "float64"


def test_settings_decorator_and_default_fluid():
    """A decorated function sees the setting on every call; fluids are validated."""

    @gm.runtime.settings(display_units="field", default_fluid=gm.WATER)
    def current():
        return gm.runtime.get_display_units(), gm.runtime.get_default_fluid()

    assert current() == ("field", gm.WATER)
    assert gm.runtime.get_display_units() == "si"
    assert gm.runtime.get_default_fluid() == gm.BRINE
