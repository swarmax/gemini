"""``gm.study.sensitivity`` has its final name and signature and is not built yet."""

import pytest

import gemini as gm


def test_sensitivity_is_not_implemented_yet():
    """The call raises ``NotImplementedYet``."""
    with pytest.raises(gm.errors.NotImplementedYet):
        gm.study.sensitivity(None, None, [], [])
