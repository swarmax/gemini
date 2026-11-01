"""The vectorised Brent and Newton repeat the scalar algorithms row by row."""

import numpy as np
import pytest
from scipy import optimize

from gemini.errors import PhysicsError
from gemini.ops.kernels.python import PythonBackend
from gemini.ops.kernels.solvers import brent_roots, newton_roots
from tests.fixtures.equivalence import RTOL

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

XTOL = 1e-9
RTOL_BRENT = 8.881784197001252e-16


def _wave(x, scale, offset):
    return np.sin(scale * x) + 0.3 * x - offset


def _sine_slope(x, scale, offset):
    return np.cos(scale * x) * scale + 0.3


def _scalar(function, low, high, args):
    try:
        return optimize.brentq(function, low, high, args=args, xtol=XTOL, rtol=RTOL_BRENT)
    except ValueError:
        return np.nan


def test_a_physics_error_in_a_trial_is_raised_on_the_python_backend():
    """A failed check in the residual raises, as it does on arrays; only no root gives NaN."""

    def refuses(value):
        raise PhysicsError("a trial outside the model's domain")

    with pytest.raises(PhysicsError):
        PythonBackend().brentq(-1.0, 1.0, function=refuses, xtol=XTOL, rtol=RTOL_BRENT, maxiter=10)


def test_brent_roots_follow_scipy_brentq_on_every_row():
    """Over a dense grid the vectorised iteration lands on the scipy result of each row."""
    scale, offset = np.meshgrid(np.linspace(0.5, 6.0, 60), np.linspace(-2.0, 2.0, 60))
    scale, offset = scale.ravel(), offset.ravel()
    low, high = np.full(scale.shape, -3.0), np.full(scale.shape, 4.0)
    roots = brent_roots(_wave, low, high, (scale, offset), XTOL, RTOL_BRENT, 100)
    expected = np.array(
        [_scalar(_wave, -3.0, 4.0, (a, b)) for a, b in zip(scale.tolist(), offset.tolist())]
    )
    np.testing.assert_allclose(roots, expected, rtol=RTOL, atol=0, equal_nan=True)
    assert np.isnan(roots).tolist() == np.isnan(expected).tolist()


def test_brent_roots_broadcast_and_return_a_scalar_for_scalars():
    """Scalar operands give a scalar and mixed shapes broadcast."""
    assert np.ndim(brent_roots(_wave, 0.0, 4.0, (1.0, 1.0), XTOL, RTOL_BRENT, 100)) == 0
    roots = brent_roots(_wave, 0.0, 4.0, (np.array([1.0, 2.0, 3.0]), 1.0), XTOL, RTOL_BRENT, 100)
    assert roots.shape == (3,)


def test_brent_roots_of_nothing_is_empty():
    """An empty batch has no rows to iterate."""
    assert brent_roots(_wave, np.zeros(0), np.ones(0), (1.0, 1.0), XTOL, RTOL_BRENT, 100).size == 0


def test_newton_roots_stop_per_row_like_the_scalar_loop():
    """Rows that converge early keep their iterate while the others continue."""
    scale = np.array([0.1, 1.0, 2.0, 5.0])
    start = np.full(4, 2.0)
    roots = newton_roots(_wave, _sine_slope, start, (scale, 0.5), 1e-6, 100)
    for index, value in enumerate(roots):
        single = newton_roots(_wave, _sine_slope, start[index], (scale[index], 0.5), 1e-6, 100)
        assert value == pytest.approx(single, rel=RTOL)
