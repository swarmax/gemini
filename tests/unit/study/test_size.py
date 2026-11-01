"""``gm.study.size`` has its final name and signature and is not built yet."""

import pytest

import gemini as gm


def test_size_is_not_implemented_yet():
    """The call raises ``NotImplementedYet``."""
    with pytest.raises(gm.errors.NotImplementedYet):
        gm.study.size(None, None)
