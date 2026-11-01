"""The one check every module makes of a flow that runs against its marked direction."""

from gemini import ops
from gemini.errors import PhysicsError


def require_forward(path, name, value, unit="kg/s"):
    """Raise ``PhysicsError`` naming ``path`` and ``name`` where the flow ``value`` is negative."""
    ops.check(
        value >= 0,
        PhysicsError,
        "{path}: {name} = {value} {unit}; expected >= 0 (reverse flow is not modelled)",
        path=path,
        name=name,
        value=value,
        unit=unit,
    )
