"""Every op is registered with a name, a known kind and an operand count."""

from gemini import ops
from gemini.errors import ValidationError
from gemini.ops import registry
from tests.fixtures.errors import raises


def test_registered_ops_describe_name_kind_and_arity():
    """The ESP ops, ``where``, ``check`` and the ``scan`` definition are registered."""
    assert ops.control is not None
    defined = registry.registered()
    assert defined["add"] == registry.OpDef("add", "elementwise", 2)
    assert defined["where"].arity == 3 and defined["getitem"].kind == "index"
    assert defined["check"].kind == "check" and defined["scan"].kind == "scan"
    assert "break" in registry.KINDS
    assert {definition.kind for definition in defined.values()} <= set(registry.KINDS)


def test_unknown_ops_and_kinds_raise():
    """An unknown op name suggests a close one; an unknown kind is refused."""
    with raises(ValidationError, "unknown_name", match="did you mean 'where'"):
        registry.get("wher")
    with raises(ValidationError, "unknown_name", match="kind = 'spin'"):
        registry.register("spin_op", "spin", 1)
