"""Conversion between old GEMINI files and the new plant, Dataset and Results objects."""

from copy import deepcopy

import pandas as pd

from gemini import units
from gemini._utils.strings import join_path
from gemini._utils.time import to_utc
from gemini.errors import ValidationError
from gemini.modules._utils.wiring import trace_wiring
from gemini.plants._utils.legacy import tables
from gemini.plants._utils.legacy.design import from_legacy_design, node_kinds, node_paths
from gemini.plants._utils.legacy.reader import converted_bindings, si_unit
from gemini.run.dataset import Dataset


def _from_si(value, unit):
    """Convert an SI value back to the old tag unit."""
    return units.convert(value, si_unit(unit), unit)


def to_dataset(project, frame):
    """Rename old tag columns, convert numeric values to SI and return an in-memory Dataset.

    Status columns are kept as text and ``tables.EXTRA_COLUMNS`` are kept converted to SI.
    """
    _, sources = converted_bindings(from_legacy_design(project))
    frame = frame.copy()
    time_column = next(
        (name for name in frame.columns if pd.api.types.is_datetime64_any_dtype(frame[name])),
        frame.columns[0],
    )
    index = pd.to_datetime(frame.pop(time_column), utc=True)
    missing = sorted({source.column for source in sources.values()} - set(frame.columns))
    if missing:
        raise ValidationError(
            f"old CSV: bound tag columns {missing} are missing", code="invalid_format"
        )
    converted, metadata = {}, {}
    for name, source in sources.items():
        converted[name] = _si_column(frame[source.column], source.unit)
        metadata[name] = si_unit(source.unit)
    for name in frame.filter(like="status").columns:
        converted[name] = frame[name]
    for old, (name, unit) in tables.EXTRA_COLUMNS.items():
        if old in frame:
            converted[name] = _si_column(frame[old], unit)
            metadata[name] = si_unit(unit)
    columns = {name: values.to_numpy() for name, values in converted.items()}
    return Dataset.from_frame(pd.DataFrame(columns, index=index), units=metadata)


def _si_column(column, unit):
    """Return a pandas column of old-unit numbers converted to SI."""
    return pd.Series(units.array_to_si(column, unit), index=column.index)


def _export_dates(owner, legacy_param):
    """Return the dates to export: the owner's history, or the old dates when they agree."""
    dates = [snapshot.valid_from for snapshot in owner._param_history] or legacy_param.timestamps
    old = legacy_param.timestamps
    if len(dates) == len(old) and all(map(_same_time, dates, old)):
        return list(old)
    return list(dates)


def _same_time(left, right):
    if left is None or right is None:
        return left is right
    return to_utc(left) == to_utc(right)


def from_plant(plant, template):
    """Convert current parameters and dated histories into an old-project copy.

    Properties without a faithful inverse (notably trajectory tables) retain the template's
    raw value. New-format-only fields remain in the plant JSON and are not invented in GEMINI.
    """
    paths = node_paths(template)
    converted = template.model_copy(deep=True)
    for node_id, properties in converted.params.items():
        path = paths[node_id]
        owner = plant.get_submodule(path)
        for name, legacy_param in properties.items():
            source = plant.get_submodule(tables.PROPERTY_OWNERS.get((path, name), path))
            dates = _export_dates(owner, legacy_param)
            values = []
            for index, at in enumerate(dates):
                original = legacy_param.values[min(index, len(legacy_param.values) - 1)]
                values.append(_legacy_property(name, source._params_at(at), original))
            legacy_param.values, legacy_param.timestamps = values, dates
    return converted


def _coefficient_value(values, original):
    """Return new coefficients in the old spelling, or the original if they are unchanged."""
    values = list(values)
    if tables.from_coefficients(original) == values:
        return original
    if isinstance(original, str):
        return ";".join(format(value, ".17g") for value in values)
    return values


def _inverse(name, params):
    """Return ``(new parameter, conversion from SI)`` of an old property, or ``None``."""
    if name == "heat_transfer_coeff":
        key = "thermal_conductance"
        return (key if key in params else "heat_transfer_coefficient"), None
    if name in tables.PROPERTY_INVERSE:
        return tables.PROPERTY_INVERSE[name]
    for suffix, key, conversion in tables.SUFFIX_INVERSE:
        if name.endswith(suffix):
            return key, conversion
    return None


def _legacy_property(name, params, original):
    """Return one old-format property while preserving unchanged raw representations."""
    if name in tables.COEFFICIENT_PROPERTIES:
        return _coefficient_value(params[tables.COEFFICIENT_PROPERTIES[name]], original)
    if name == "esp_correction_factor":
        slope, offset = params["correction_factors"]
        return _coefficient_value([slope, units.pa_to_bar(offset)], original)
    inverse = _inverse(name, params)
    if inverse is None:
        return original
    key, conversion = inverse
    value = params[key] if conversion is None else conversion(params[key])
    return original if value == original else value


def results_to_frame(results, project):
    """Convert predicted bound outputs to their old tag columns and units."""
    design = from_legacy_design(project)
    frame = results.to_frame()
    output = pd.DataFrame({"Timestamp": frame.index.tz_convert("UTC").tz_localize(None)})
    for path, bound in design.bindings.items():
        for field, binding in bound.measured.items():
            name = join_path(path, field)
            if name in frame:
                output[binding.column] = (
                    frame[name].map(lambda value: _from_si(value, binding.unit)).to_numpy()
                )
    return output


def _traced_edges(plant):
    """Return the stream connections of one step of a copy of ``plant`` with assumed inputs."""
    if not plant._root_inputs():
        raise ValidationError(
            f"{plant.path}: inputs has no plant inlet stream; expected a plant filled by "
            "legacy.to_plant",
            code="invalid_format",
        )
    trial = deepcopy(plant)
    trial._set_inputs(tables.TRACE_CONTROLS)
    return trace_wiring(trial, trial._root_inputs())


def _endpoint(kinds, paths, node_id, port):
    """Return ``(path, port)`` of a diagram link end, or ``None`` if the bridge cannot map it."""
    ports = tables.PORTS.get(kinds.get(node_id), {})
    if node_id not in paths or port not in ports:
        return None
    return paths[node_id], ports[port]


def _expected_edges(project):
    """Return the plant connections the old diagram describes and its unmapped link ends."""
    kinds, paths = node_kinds(project), node_paths(project)
    pumps = {pump: riser for pump, riser in tables.RISERS.values()}
    expected, errors = set(), []
    for link in project.links:
        source = _endpoint(kinds, paths, link.source, link.source_port)
        target = _endpoint(kinds, paths, link.target, link.target_port)
        if source is None or target is None:
            errors.append(
                f"Unmapped legacy diagram endpoint: {link.source}.{link.source_port} -> "
                f"{link.target}.{link.target_port}"
            )
            continue
        if source[0] in pumps and source[1] == "fluid_out":
            expected.add((*source, pumps[source[0]], "bottom_in"))
            source = (pumps[source[0]], "wellhead_out")
        expected.add((*source, *target))
    return expected, errors


def check_wiring(plant, project):
    """Return an empty list when observed plant stream identities match the old diagram.

    One step runs on a copy of the plant with its assumed root inputs and
    ``tables.TRACE_CONTROLS``, so the caller's plant is not changed. Failures to run the step
    propagate.
    """
    traced = _traced_edges(plant)
    expected, errors = _expected_edges(project)
    errors.extend(f"Missing connection: {edge}" for edge in sorted(expected - traced))
    errors.extend(f"Unexpected connection: {edge}" for edge in sorted(traced - expected))
    return errors
