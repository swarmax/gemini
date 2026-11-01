"""Which ports a connection joins: the lookups and rules of ``Plant.connect``."""

from gemini._utils.strings import close_matches, did_you_mean, join_names, join_path
from gemini.errors import ValidationError
from gemini.modules.declarations import Declaration
from gemini.modules.module import Module
from gemini.plants._utils.plan import is_group, members, port_ends, split_end

SIDE_OF = {"source": "outlets", "target": "inlets"}


def _compatible(first, second):
    if first.carries_stream != second.carries_stream:
        return False
    return first.kind is None or second.kind is None or first.kind == second.kind


def _describe_end(candidate):
    path, port, declaration = candidate
    return f"{join_path(path, port)} [{declaration.kind or 'any'}]"


class PortResolver:
    """Methods of ``Plant`` that find, check and name ports (needs its ``_connections``)."""

    def _is_port_name(self, value):
        return isinstance(value, str) and "." not in value and self._find_submodule(value) is None

    def _name_port(self, side, name, end, explicit):
        field = "target" if side == "inlets" else "source"
        candidates = self._candidates(end, field, explicit)
        if len(candidates) != 1:
            raise self._ambiguous(list(map(_describe_end, candidates)), field)
        if name in self._listed[side] and self._shareable(candidates[0][2]):
            return self._join_port(side, name, candidates[0])
        if name in self._listed[side] or name in self._children:
            raise ValidationError(
                f"{name}: plant port name is already taken", path="", code="invalid_connection"
            )
        path, port, declaration = candidates[0]
        own = getattr(self, f"_{side}").get(name)
        if own is not None and not _compatible(own, declaration):
            raise ValidationError(
                f"stream mismatch: plant port {name} [{own.kind or 'any'}] to "
                f"{_describe_end(candidates[0])}",
                path=field,
                code="stream_mismatch",
            )
        self._listed[side][name] = (path, port)
        self._refresh()

    def _join_port(self, side, name, candidate):
        """Add ``candidate`` to the plant port ``name``, which several ends share."""
        path, port, _ = candidate
        kept = self._listed[side][name]
        self._listed[side][name] = [*port_ends(kept), (path, port)]
        self._refresh()

    @staticmethod
    def _shareable(declaration):
        """Return whether several ends may share a plant port: a power, or air at no flow."""
        return not declaration.carries_stream or declaration.kind == "air"

    def _candidates(self, value, field, explicit):
        side = SIDE_OF[field]
        path, port = self._locate(value, field, explicit)
        declared = getattr(self.get_submodule(path), side)()
        if port is not None:
            return [self._checked(path, port, declared, side, field)]
        free = [
            (path, name, item)
            for name, item in declared.items()
            if item.many or not self._in_use(path, name, side)
        ]
        if not free:
            code = "port_in_use" if declared else "unknown_port"
            raise ValidationError(f"{path}: no free {side[:-1]} to connect", path=field, code=code)
        return free

    def _checked(self, path, port, declared, side, field):
        if port not in declared:
            raise ValidationError(
                f"{join_path(path, port)}: not an {side[:-1]}; valid: {join_names(declared)}"
                f"{did_you_mean(port, declared)}",
                path=field,
                code="unknown_port",
                suggestions=close_matches(port, declared),
            )
        if not declared[port].many and self._in_use(path, port, side):
            raise ValidationError(
                f"{join_path(path, port)}: {side[:-1]} is already connected",
                path=field,
                code="port_in_use",
            )
        return path, port, declared[port]

    def _in_use(self, path, port, side):
        key = "source" if side == "outlets" else "target"
        used = {split_end(item[key]) for item in self._connections}
        named = {end for ends in self._listed[side].values() for end in port_ends(ends)}
        return (path, port) in used | named

    def _locate(self, value, field, explicit):
        path, port = self._from_handle(value, field)
        module = self._find_submodule(path)
        if module is None:
            paths = [item for item, _ in members(self)]
            raise ValidationError(
                f"{value!r}: no module {path!r}{did_you_mean(path, paths)}",
                path=field,
                suggestions=close_matches(path, paths),
                code="unknown_name",
            )
        self._check_reach(path, field)
        if port is None and explicit:
            free = [f"{path}.{name}" for name in getattr(module, SIDE_OF[field])()]
            raise ValidationError(
                f"{value!r}: name a port, one of {join_names(free)}",
                path=field,
                code="invalid_connection",
                suggestions=free,
            )
        return path, port

    def _from_handle(self, value, field):
        if isinstance(value, Declaration):
            return self._descendant_path(value.owner) or "", value.name
        if isinstance(value, Module):
            return self._descendant_path(value) or "", None
        if not isinstance(value, str):
            raise ValidationError(
                f"{value!r}: expected a module, a port or 'path.port'", path=field
            )
        if value and self._find_submodule(value) is not None:
            return value, None
        path, _, port = value.rpartition(".")
        return path, port or None

    def _check_reach(self, path, field):
        parts = path.split(".")
        module = self
        for index, part in enumerate(parts):
            if index and not is_group(module):
                prefix = ".".join(parts[:index])
                raise ValidationError(
                    f"{path}: reaches into {prefix!r}; use its own ports, one of "
                    f"{join_names(list(module.inlets()) + list(module.outlets()))}",
                    path=field,
                    code="invalid_connection",
                )
            module = module._children[part]
        if is_group(module):
            raise ValidationError(
                f"{path}: a group has no ports", path=field, code="invalid_connection"
            )

    def _choose(self, first, second):
        pairs = [(a, b) for a in first for b in second if _compatible(a[2], b[2])]
        if len(pairs) == 1:
            return pairs[0]
        if not pairs:
            raise ValidationError(
                f"stream mismatch: {', '.join(map(_describe_end, first))} to "
                f"{', '.join(map(_describe_end, second))}",
                path="target",
                code="stream_mismatch",
            )
        raise self._ambiguous([" -> ".join(map(_describe_end, pair)) for pair in pairs], "target")

    def _ambiguous(self, listed, field):
        return ValidationError(
            f"ambiguous port: {len(listed)} candidates: {'; '.join(listed)}",
            path=field,
            code="ambiguous_port",
            suggestions=listed,
        )

    def _port_map(self, side):
        """Return the plant's named ``inlets`` or ``outlets`` as ``{name: (path, port)}``."""
        return dict(self._listed[side])

    def _unconnected_ports(self):
        """Return ``(side, path, port)`` of every port with no connection and no plant name."""
        return [
            (side, path, port)
            for side in SIDE_OF.values()
            for path, module in members(self)
            for port, declaration in getattr(module, side)().items()
            if not declaration.many and not self._in_use(path, port, side)
        ] + [
            (side, "", name)
            for side, declared in (("inlets", self._inlets), ("outlets", self._outlets))
            for name in declared
            if name not in self._listed[side]
        ]
