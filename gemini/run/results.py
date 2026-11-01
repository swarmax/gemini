"""Per-module series, energy integration, JSON views and lossless result persistence."""

import io
from pathlib import Path

import numpy as np
import pandas as pd

from gemini import units as physics_units
from gemini._utils.jsonable import to_plain
from gemini._utils.strings import close_matches, did_you_mean, join_names, join_path, split_path
from gemini._utils.time import to_utc
from gemini.engine import archive
from gemini.engine.chunks import (
    PathColumns,
    ResultChunk,
    assemble,
    first_present,
    merge,
)
from gemini.errors import ValidationError
from gemini.errors.lookup import UnknownKey
from gemini.types.flows import FIELD_QUANTITIES
from gemini.types.shapes import OutputUnits, problem, series, value

ENERGY_FIELDS = ("power_in", "fuel", "loss_out")
"""Leaf outputs integrated over time into energy totals."""

SERIES_UNITS = {
    "head": ("Pa", "pressure_difference"),
    "pressure_drop": ("Pa", "pressure_difference"),
    "discharge_pressure": ("Pa", "pressure"),
    "power": ("W", "power"),
    "duty": ("W", "power"),
    "thermal_power": ("W", "power"),
}
"""Stored SI unit and quantity of the result fields that ``ModuleSeries.get`` can convert.

``Results.units`` maps every column to its unit and ``Results.declared`` holds them by path;
``ModuleSeries.get`` keeps converting only these six, because it needs the quantity of a
difference, which is not stored.
"""


class Summary(pd.DataFrame):
    """Detailed summary table with a compact printed energy/alarm view."""

    def __repr__(self):
        """Display the principal metrics without pandas hiding energy or alarm columns."""
        if self.empty:
            return "No completed observations"
        columns = [
            "energy_J",
            "energy_MWh",
            "peak_W",
            "operating_hours",
            "alarms",
            "alarm_rate",
            "skipped",
            "errors",
        ]
        return self[columns].to_string(float_format=lambda value: f"{value:.6g}")

    __str__ = __repr__


class ModuleSeries:
    """Attribute access to a module's output series."""

    def __init__(self, frame, path=""):
        """Retain the module's field-indexed frame and its path for error messages."""
        self._frame = frame
        self._path = path

    def __getattr__(self, field):
        """Return one pandas Series or an informative unknown-field error."""
        if field not in self._frame:
            raise UnknownKey(
                f"{self._path}: result field = {field!r}; expected one of "
                f"{join_names(self._frame)}{did_you_mean(field, self._frame)}"
            )
        return self._frame[field]

    def get(self, field, unit=None):
        """Return a series, optionally converted from its stored SI unit.

        Results store no per-field unit metadata, so conversion is limited to the fields in
        ``SERIES_UNITS`` (head, pressure drops, powers and duties); other fields raise.
        """
        series = getattr(self, field)
        if unit is None:
            return series
        if field not in SERIES_UNITS:
            raise ValidationError(
                f"{self._path}: result field = {field!r}; expected one of "
                f"{join_names(SERIES_UNITS)} for unit conversion",
                code="invalid_unit",
            )
        source, quantity = SERIES_UNITS[field]
        return series.map(lambda value: physics_units.convert(value, source, unit, quantity))


def _add_skips(skip_counts, skips):
    """Add one step's ``{path: {reason: count}}`` skips into running totals."""
    for path, reasons in skips.items():
        target = skip_counts.setdefault(path, {})
        for reason, count in reasons.items():
            target[reason] = target.get(reason, 0) + count


class _ColumnUnits(dict):
    """The unit of each column of a frame; pandas copies ``attrs`` at every step, this it shares."""

    def __deepcopy__(self, memo):
        """Return this mapping: its copies would all be equal."""
        return self


class Results:
    """Collect finite timestep outputs, energy totals, health, errors and explicit skips.

    Results are columnar. ``commit(chunk)`` is the one way in: a ``ResultChunk`` of any length,
    one tick included. Chunks concatenate lazily in ``to_frame``. ``units`` maps each column,
    ``"<path>.<field>"``, to its SI unit, as ``to_frame`` names the columns. ``declared`` maps
    ``{path: {field: unit}}`` to the SI unit of each output field, as the plant declares it
    (a field without an entry is dimensionless, ``"-"``), ``quantities`` likewise to its quantity
    (``None`` when it has none, and then ``units=`` leaves it alone), and ``end_state`` is the plain
    JSON state a following replay starts from (``replay(..., state=results.end_state)``). Every
    view takes ``units``, a map from quantity to unit (``OutputUnits``): nothing stored changes.
    """

    def __init__(self, declared=None):
        """Start an independent result table."""
        self._chunks, self._order = [], {}
        self._times, self._dt = [], []
        self.skip_counts, self._failures = {}, []
        self._energy = set()
        self._skips = []
        self._frame = None
        self._series = None
        self.declared = dict(declared or {})
        self.quantities = {}
        self.end_state = None

    @property
    def units(self):
        """The SI unit of every column, ``{"<path>.<field>": unit}``, as ``to_frame`` names them."""
        return {join_path(path, field): self.unit(path, field) for path, field in self._order}

    @property
    def failures(self):
        """The rows where a module raised, oldest first; skipped rows are not among them."""
        return self._failures

    def commit(self, chunk):
        """Commit a chunk of ticks: its columns, durations, skips and errors."""
        self._register(chunk)
        self._record(chunk.times, chunk.durations, chunk.skips, chunk.errors)

    def _record(self, times, durations, skips, errors):
        """Keep the times, durations, skips and errors of committed ticks."""
        self._times.extend(times)
        self._dt.extend(durations)
        self._skips.extend(skips if skips is not None else [{}] * len(times))
        for skipped in skips or ():
            _add_skips(self.skip_counts, skipped)
        for row, error in errors:
            self._failures.append(dict(error, time=times[row].isoformat()))
        self._frame = None
        self._series = None

    def _register(self, chunk):
        """Store a chunk: its new columns, in the order a row-by-row build meets them."""
        for key in chunk.column_order():
            self._order.setdefault(key, None)
        for path, table in chunk.tables.items():
            if table.present.any():
                self._energy.update((path, name) for name in ENERGY_FIELDS if name in table.columns)
        self._chunks.append(chunk)

    def __len__(self):
        """Count completed ticks, including skipped or failed rows."""
        return len(self._times)

    def __getitem__(self, path):
        """Return the series of a module, or one Series: an output or a port field by its path.

        ``results["sub.consumer"].unmet_demand``, ``results["sub.consumer.unmet_demand"]`` and
        ``results["sub.heat_exchanger.hot_out.T"]`` all read by path.
        """
        frame = self._cached_frame()
        paths = list(frame.columns.get_level_values(0).unique())
        if path in paths:
            return ModuleSeries(frame[path].copy(), path)
        owner, name = split_path(path)
        if owner in paths and name in frame[owner]:
            return frame[owner][name].copy()
        module, port = split_path(owner)
        column = f"{port}.{FIELD_QUANTITIES.get(name)}"
        if module in paths and column in frame[module]:
            return frame[module][column].copy()
        raise _unknown_path(path, paths)

    @property
    def durations(self):
        """Return the duration [s] of every committed tick, as a float array."""
        return np.asarray(self._dt, dtype=float)

    def _cached_frame(self):
        """Return the shared table, built once after each append; callers must not change it."""
        if self._frame is None:
            self._chunks = [merge(self._chunks)] if self._chunks else []
            chunk = self._chunks[0] if self._chunks else ResultChunk([], [], {})
            self._frame = assemble(chunk, list(self._order), self._times)
        return self._frame

    def to_frame(self, units=None, table="series"):
        """Return a table of the results, the one route to a DataFrame.

        ``"series"`` is a copy with one column per field, named ``path.field`` (a root field by
        name), in SI or in ``units``, with the unit of each column in ``frame.attrs["units"]``.
        ``"energy"`` is the table of ``energy_report`` with a row per module and energy output,
        which ``repr`` prints; its columns state their units and it takes no ``units``.
        """
        if table not in ("series", "energy") or (table == "energy" and units):
            raise ValidationError(
                f"Results.to_frame: table = {table!r}, units = {units!r}; expected 'series', or "
                "'energy' without units",
                path="table",
            )
        return self._energy_table() if table == "energy" else self._series_table(units)

    def _series_table(self, units):
        """Return the table of the series, with the unit of each column in ``attrs``.

        Without ``units`` it is built once and each caller gets a copy: every reader of a finished
        run starts here, several times for one metric.
        """
        if units or self._series is None:
            table = self._built_series(units)
            if units:
                return table
            self._series = table
        return self._series.copy()

    def _built_series(self, units):
        """Return a new table of the series in ``units``."""
        frame = self._cached_frame().copy()
        keys = list(frame.columns)
        if not units:
            frame.columns = [join_path(*key) for key in keys]
            frame.attrs["units"] = _ColumnUnits(
                {join_path(path, field): self.unit(path, field) for path, field in keys}
            )
            return frame
        output = OutputUnits(units)
        stated = {}
        for key in keys:
            column, stated[join_path(*key)] = self._column(frame[key], *key, output)
            frame[key] = column
        frame.columns = list(stated)
        frame.attrs["units"] = _ColumnUnits(stated)
        return frame

    def _column(self, column, path, field, output):
        """Return one column and its unit in the unit ``output`` asks for its quantity."""
        unit, quantity = self.unit(path, field), self.quantity(path, field)
        target = output.target(quantity)
        if target is None:
            return column, unit
        if pd.api.types.is_numeric_dtype(column) and not pd.api.types.is_bool_dtype(column):
            numbers = physics_units.array_convert(column, unit, target, quantity)
            return pd.Series(numbers, index=column.index, name=column.name), target
        return column.map(lambda cell: output.number(cell, unit, quantity)[0]), target

    def unit(self, path, field):
        """Return the SI unit of a field; a field the plant gives no unit is ``"-"``."""
        return self.declared.get(path, {}).get(field, "-")

    def quantity(self, path, field):
        """Return the quantity of a field, or ``None`` for one the plant gives none."""
        return self.quantities.get(path, {}).get(field)

    def names(self):
        """Return ``{path: [field, ...]}`` of everything ``get`` can read, in column order."""
        names = {}
        for path, field in self._order:
            names.setdefault(path, []).append(field)
        return names

    def get(self, path, field, start=None, end=None, units=None):
        """Return the series ``{time, value, unit}`` of one field, ``start`` to ``end`` inclusive.

        ``time`` is ISO 8601 UTC text, ``value`` has ``None`` for a missing value and ``unit``
        is the unit used, SI unless ``units`` asks otherwise. An unknown path or field raises
        ``ValidationError``.
        """
        output = OutputUnits(units)
        column = _window(getattr(self[path], field), start, end)
        converted, unit = self._column(column, path, field, output)
        return series(column.index, converted, unit)

    def summary(self, path=None, start=None, end=None, units=None):
        """Return ``{path: {field: {min, max, mean}}}`` of the numeric fields, each a value.

        ``path`` selects one module and ``start`` and ``end`` (inclusive) a window; a value is
        ``None`` with a ``reason`` where a field has no finite value. ``units`` converts them.
        """
        output = OutputUnits(units)
        frame = _window(self._cached_frame(), start, end)
        paths = list(dict.fromkeys(frame.columns.get_level_values(0)))
        if path is not None:
            if path not in paths:
                raise _unknown_path(path, paths)
            paths = [path]
        return {name: self._field_summary(name, frame[name], output) for name in paths}

    def _field_summary(self, path, fields, output):
        """Return the minimum, maximum and mean of each numeric field of one path."""
        return {
            field: output.statistics(
                fields[field].min(),
                fields[field].max(),
                fields[field].mean(),
                self.unit(path, field),
                self.quantity(path, field),
            )
            for field in fields
            if pd.api.types.is_numeric_dtype(fields[field])
            and not pd.api.types.is_bool_dtype(fields[field])
        }

    def errors(self):
        """Return the rows that did not give a result, oldest first, as problems.

        Each row is ``{path, code, message, suggestions, time}``. A tick where a module raised
        has its error code from ``gm.errors.ROW_CODES`` and the exception's message; a tick
        skipped for a missing bound value has the code ``missing_value`` and the missing column
        as message. The run continues after every such row.
        """
        failed = {}
        for row in self._failures:
            failed.setdefault(row["time"], []).append(row)
        rows = []
        for time, skipped in zip(self._times, self._skips):
            stamp = time.isoformat()
            rows.extend(failed.get(stamp, ()))
            rows.extend(_skip_rows(stamp, skipped))
        return to_plain(rows)

    def to_dict(self, units=None):
        """Return everything as plain JSON: ``{time, duration, series, errors, ...}``.

        ``duration`` is a value and ``series`` is ``{path: {field: {value, unit}}}``, with one item
        per entry of ``time``, in SI or in ``units``.
        """
        output = OutputUnits(units)
        frame = self._cached_frame()
        columns = {}
        for path, field in frame.columns:
            column, unit = self._column(frame[(path, field)], path, field, output)
            columns.setdefault(path, {})[field] = {"value": column, "unit": unit}
        return to_plain(
            {
                "time": frame.index,
                "duration": output.value(self._dt, "s", "duration"),
                "series": columns,
                "errors": self.errors(),
                "skip_counts": self.skip_counts,
                "end_state": self.end_state,
            }
        )

    def energy_report(self, units=None):
        """Report energy, peaks, evaluated hours, alarms and skip reasons per module and output.

        Returns ``{path: {output: entry}}``, ``output`` being the energy output, or ``""`` for a
        path without one. An entry has the values ``energy``, ``peak``, ``hours``,
        ``operating_hours``, ``alarms``, ``alarm_rate``, ``skipped`` and ``errors``, ``peaks`` with
        the largest value of each numeric field, and ``reasons`` with the count of each skip reason.
        ``to_frame(table="energy")`` is the same report as a table. ``units`` converts them.
        """
        output = OutputUnits(units)
        report = {}
        for row in self._energy_rows():
            report.setdefault(row["module"], {})[row["port"]] = self._report_entry(row, output)
        return report

    def _report_entry(self, row, output):
        """Return one row of the energy table with every number as a value."""
        path = row["module"]
        return {
            "energy": output.value(row["energy_J"], "J", "energy"),
            "peak": output.value(row["peak_W"], "W", "power"),
            "hours": output.value(row["hours"], "h", "duration"),
            "operating_hours": output.value(row["operating_hours"], "h", "duration"),
            "alarms": value(row["alarms"], "-"),
            "alarm_rate": value(row["alarm_rate"], "-"),
            "skipped": value(row["skipped"], "-"),
            "errors": value(row["errors"], "-"),
            "peaks": {
                field: output.value(peak, self.unit(path, field), self.quantity(path, field))
                for field, peak in row["peaks"].items()
            },
            "reasons": row["reasons"],
        }

    def _energy_table(self):
        """Return the energy report as a table, one row per module and energy output."""
        rows = self._energy_rows()
        return Summary(pd.DataFrame(rows).set_index(["module", "port"])) if rows else Summary()

    def _energy_rows(self):
        """Return the rows of the energy report in path order."""
        frame = self._cached_frame().copy()
        recorded = set(frame.columns.get_level_values(0))
        failed = {error["path"] for error in self._failures}
        paths = sorted(recorded | self.skip_counts.keys() | failed)
        dt = pd.Series(self._dt, index=frame.index, dtype=float)
        rows = []
        for path in paths:
            fields = frame[path] if path in recorded else pd.DataFrame(index=frame.index)
            rows.extend(self._summary_rows(path, fields, dt))
        return rows

    def _module_info(self, path, fields, dt):
        """Return evaluated and operating hours, peaks, alarms, errors and skips of one path."""
        active = fields.notna().any(axis=1)
        alarms = fields.get("health_alarm", pd.Series(False, index=fields.index)).eq(True)
        return dict(
            module=path,
            hours=float(dt[active].sum() / physics_units.SECONDS_PER_HOUR),
            operating_hours=float(
                dt[fields.get("operating", active).eq(True)].sum() / physics_units.SECONDS_PER_HOUR
            ),
            errors=sum(error["path"] == path for error in self._failures),
            peaks={
                field: float(fields[field].max())
                for field in fields
                if not field.startswith("health_")
                and (path, field) not in self._energy
                and field != "operating"
                and pd.api.types.is_numeric_dtype(fields[field])
            },
            alarms=int(alarms.sum()),
            alarm_rate=float(alarms[active].mean()) if active.any() else 0,
            skipped=sum(self.skip_counts.get(path, {}).values()),
            reasons=dict(self.skip_counts.get(path, {})),
        )

    def _summary_rows(self, path, fields, dt):
        """Return one row per energy output of a path, or one row with its peak power."""
        info = self._module_info(path, fields, dt)
        ports = sorted(field for owner, field in self._energy if owner == path)
        if not ports:
            power_fields = [name for name in ("duty", "power", "thermal_power") if name in fields]
            peak = float(fields[power_fields].max().max()) if power_fields else np.nan
            return [info | dict(port="", energy_J=0.0, energy_MWh=0.0, peak_W=peak)]
        rows = []
        for field in ports:
            power = fields[field]
            energy = float((power * dt).sum())
            rows.append(
                info
                | dict(
                    port=field,
                    energy_J=energy,
                    energy_MWh=energy / 3.6e9,
                    peak_W=float(power.max()),
                )
            )
        return rows

    def __repr__(self):
        """Print the compact energy report."""
        return str(self._energy_table())

    def _archive(self):
        """Return the table and the metadata that ``save`` and ``to_bytes`` write."""
        metadata = dict(
            dt=self._dt,
            skip_counts=self.skip_counts,
            failures=self._failures,
            skips=self._skips,
            energy=sorted(self._energy),
            units=self.declared,
            quantities=self.quantities,
            end_state=self.end_state,
        )
        return self._cached_frame(), metadata

    def to_npz(self, path):
        """Write every cell exactly as one ``.npz`` file and return its path.

        A path without the ``.npz`` suffix gets it. Numeric columns are stored as arrays and
        other columns as JSON text, so loading needs no pickle and gives the same bits.
        """
        path = Path(path)
        if path.suffix != ".npz":
            path = Path(str(path) + ".npz")
        path.parent.mkdir(parents=True, exist_ok=True)
        archive.to_file(path, *self._archive())
        return path

    def to_bytes(self):
        """Return the ``.npz`` archive of ``to_npz`` as bytes, for storage without a file."""
        return archive.to_bytes(*self._archive())

    @classmethod
    def from_npz(cls, path):
        """Return the results written by ``to_npz``, with identical cells, units and end state."""
        path = Path(path)
        if not path.exists() and Path(str(path) + ".npz").exists():
            path = Path(str(path) + ".npz")
        return cls._restored(*archive.from_file(path))

    @classmethod
    def from_bytes(cls, data):
        """Restore results from the bytes of ``to_bytes``."""
        return cls._restored(*archive.from_file(io.BytesIO(data)))

    @classmethod
    def _restored(cls, times, columns, metadata):
        """Build results from the parts of an archive without re-running equipment."""
        result = cls()
        present = np.ones(len(times), dtype=bool)
        tables = {}
        for path, field, values in columns:
            tables.setdefault(path, PathColumns(present, {})).columns[field] = values
        result._times = list(times)
        result._dt = metadata["dt"]
        result._chunks = [ResultChunk(list(result._times), list(result._dt), tables)]
        result._order = dict.fromkeys((path, field) for path, field, _ in columns)
        result.skip_counts = metadata["skip_counts"]
        result._failures = metadata["failures"]
        result._skips = metadata["skips"]
        result._energy = {tuple(key) for key in metadata["energy"]}
        result.declared = metadata["units"]
        result.quantities = metadata["quantities"]
        result.end_state = metadata["end_state"]
        return result

    def slice(self, start):
        """Return the new rows of a live call, with matching durations and diagnostics."""
        result = Results(self.declared)
        result.quantities = self.quantities
        result.end_state = self.end_state
        if self._chunks:
            self._chunks = [merge(self._chunks)]
            chunk = self._chunks[0].rows(start, len(self._chunks[0]))
            result._chunks = [chunk]
            result._order = _sliced_order(self._order, chunk)
        result._times, result._dt = self._times[start:], self._dt[start:]
        result._energy = self._energy.copy()
        result._skips = self._skips[start:]
        for skipped in result._skips:
            _add_skips(result.skip_counts, skipped)
        times = {t.isoformat() for t in result._times}
        result._failures = [error for error in self._failures if error["time"] in times]
        return result


PORT_QUANTITIES = {
    "mass_flow": ("kg/s", "mass_flow"),
    "volume_flow": ("m3/s", "volume_flow"),
    "temperature": ("K", "temperature"),
    "pressure": ("Pa", "pressure"),
    "enthalpy_flow": ("W", "power"),
    "gas_flow": ("kg/s", "mass_flow"),
    "co2_flow": ("kg/s", "mass_flow"),
    "chemical_flow": ("W", "power"),
}
"""Unit and quantity of each field of a fluid port, named ``<port>.<quantity>`` in the results."""


def port_fields(module):
    """Return ``{field: (unit, quantity)}`` of the ports of ``module``."""
    fields = {}
    for name, port in (module.inlets() | module.outlets()).items():
        if not port.carries_stream:
            fields[name] = ("W", "power")
            continue
        fields |= {f"{name}.{key}": item for key, item in PORT_QUANTITIES.items()}
    return fields


def declared_units(plant):
    """Return ``{path: {field: unit}}``: the SI unit of each output and port field of a plant."""
    return {
        path: {
            **{
                name: declaration.unit or "-"
                for name, declaration in module.outputs(recurse=False).items()
            },
            **{name: item[0] for name, item in port_fields(module).items()},
        }
        for path, module in plant.named_modules()
    }


def declared_quantities(plant):
    """Return ``{path: {field: quantity}}``: the quantity of each output and port field."""
    return {
        path: {
            **{
                name: declaration.quantity
                for name, declaration in module.outputs(recurse=False).items()
            },
            **{name: item[1] for name, item in port_fields(module).items()},
        }
        for path, module in plant.named_modules()
    }


def _unknown_path(path, paths):
    """Return the error for a results path that does not exist."""
    return UnknownKey(
        f"Results: module path = {path!r}; expected one of "
        f"{join_names(paths)}{did_you_mean(path, paths)}",
        path=path,
        suggestions=close_matches(path, paths),
    )


def _window(table, start, end):
    """Return the rows of a time-indexed table from ``start`` to ``end``, both inclusive."""
    if start is None and end is None:
        return table
    lower = to_utc(start) if start is not None else None
    upper = to_utc(end) if end is not None else None
    return table.loc[lower:upper]


def _skip_rows(stamp, skipped):
    """Return the rows of the reasons a tick skipped each path."""
    return [
        problem(path, "missing_value", reason, time=stamp)
        for path, reasons in skipped.items()
        for reason in reasons
    ]


def _sliced_order(order, chunk):
    """Return the columns of a slice: those of paths present in it, by first tick present."""
    first = {path: first_present(table) for path, table in chunk.tables.items()}
    kept = [key for key in order if first.get(key[0]) is not None]
    return dict.fromkeys(sorted(kept, key=lambda key: first[key[0]]))
