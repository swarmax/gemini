# Errors

`gemini/errors/` defines GEMINI's public exception and warning classes. Users reach them as
`gm.errors.<Name>`. It is a leaf package that imports nothing else from `gemini`
(`tests/unit/test_package_boundaries.py`).

## One rule for raising

Every public call raises on failure by default. A call that can report instead takes one argument
with one name everywhere, `on_error="raise" | "record"`, default `"raise"`. With `"record"` nothing
is raised and the problems go to the call's fixed place:

| Call | Under `on_error="record"` |
| --- | --- |
| `validate_params`, `p.validate`, `gm.plants.validate` | return the list of problems |
| `gm.call` | returns them under `errors`, with empty `outlets` and `outputs` |
| `gm.simulate`, `gm.replay`, `gm.live`, `gm.Engine` | record them in `results.errors()` and continue |
| `gm.evaluate.*` | a value the inputs cannot give is `{value: null, unit, reason}` |
| `gm.analysis.nodal` | the case holds its problem in `error`; the other cases still run |

`gm.call` has no "never raises" rule. The "never raises" behaviour agents need belongs to
geomind's tool layer, which catches `GeminiError` and calls `to_dict()`.

A raised error that comes from several problems (`gm.Plant.from_dict`, `validate`) carries all of
them in `error.problems`, a list of problem dicts: the same list `on_error="record"` returns, so a
caller sees every problem in one try. A single error has itself as the one item. A problem is
`{path, code, message, suggestions}`, built by `gemini.errors.base.problem`, which
`gemini.types.shapes` exports with the other return shapes; `code` is the stable key for machines.

**Checks are not errors.** The checks of `gm.evaluate` (`constraints`, `plant_balance`,
`energy_balance`, `mass_balance`, `bounds`, `run_all`) always return check dicts with `passed`; a
violated limit never raises. A real failure inside a check (wrong input) still raises.

## The classes

```text
GeminiError
  ValidationError    wrong input: values, dicts, bindings, units, unknown names
  DefinitionError    a module class written wrongly (developer side)
  PhysicsError       out of range, no convergence, missing chemistry, too little data
  RunError           dataset, clock, checkpoint, step
  Cancelled          a callback stopped a run; committed ticks stay readable
  NotImplementedYet  the name is final, its work lands in a later step
GeminiWarning        root of warnings
```

`GeminiError` takes `path=`, `code=`, `suggestions=` and `problems=` as keywords. `code` defaults to
the class attribute (`invalid_value`, `invalid_definition`, `out_of_range`, `step`, `cancelled`,
`not_implemented`) and must be one of `CODES`. What a former class meant is a code: catch the class,
read the code.

Built-in bases appear only where Python needs them, never two error meanings in one class:

- `ValidationError` is a `ValueError`.
- `gemini/errors/lookup.py` holds three private subclasses of `ValidationError` for Python's
  protocols, not public and never named by a caller: `UnknownKey` and `UnknownPort` (also `KeyError`
  and `AttributeError`, for mapping lookups, `Ports` and `Results`) and `UnknownMember` (also
  `AttributeError`, for `hasattr`, `getattr` with a default, `copy` and `pickle` on a module; its
  close-match suggestion is built only when the message is read).
- `TraceError` is internal to `gemini/compiler/graph/` (`gemini/compiler/graph/errors.py`). The graph runner catches it
  and runs that module as a plain call (a graph break); users never see it.

The other exceptions to raising these classes are the topic files of `gemini._utils`, which cannot
import them (`paths.py` alone can, and raises `inputs_missing`), pydantic validators, which must raise `ValueError` (pydantic reports it as its own
validation error), and `NotImplementedError` for an abstract method.
`test_package_code_raises_gemini_errors` and `test_package_code_raises_only_the_allowed_classes` in
`tests/unit/test_code_quality.py` enforce this.

`PhysicsError` is no `ValueError`. Code that once caught `ValueError` around a physics call names
`PhysicsError` too: `Declaration.validate`, `Module._validated_ports` and the Python `brentq`.

## Codes

`gm.errors.CODES` is the fixed tuple of `code` values; the backend puts them into `422` details, so a
code is never renamed without raising the minor number of `gm.__version__`.

| Code | Class | Meaning |
| --- | --- | --- |
| `error` | any | A GEMINI error with no more specific code |
| `invalid_value` | `ValidationError` | A value has the wrong type or shape |
| `out_of_bounds` | `ValidationError` | A value is outside its declared bounds |
| `missing_value` | `ValidationError` | A required value is absent |
| `missing_assumption` | `ValidationError` | A cost, a price or an emission factor is needed and the case does not give it; the path names it in the case (`assumptions.finance.capex.<kind>`) |
| `no_value` | `ValidationError` | The inputs cannot give this value, such as a plant without equipment that has a cost |
| `conflicting_value` | `ValidationError` | Two sources give one value: a `Constraint` of the case gives two bounds that exclude each other (`equals` with a `min` or `max`); the path names it |
| `duplicate_name` | `ValidationError` | A second class takes the registry name of another class |
| `invalid_unit` | `ValidationError` | A unit is unknown or does not fit the quantity |
| `unknown_name` | `ValidationError` | A module type, path, parameter, category, correlation or field does not exist |
| `unknown_port` | `ValidationError` | A port does not exist on that module |
| `invalid_call` | `ValidationError` | A module was called with wrong arguments |
| `invalid_format` | `ValidationError` | A document has the wrong structure |
| `old_format` | `ValidationError` | A plant dict is older than the current format, a checkpoint was written before 0.2.0, or a results file before 0.1.0 |
| `invalid_connection` | `ValidationError` | A connection breaks a wiring rule |
| `stream_mismatch` | `ValidationError` | The two ends of a connection have different kinds |
| `ambiguous_port` | `ValidationError` | Automatic port matching found no port or more than one |
| `port_in_use` | `ValidationError` | An inlet already has a source, or an outlet already has a target |
| `unconnected_port` | `ValidationError` | A port of a module has no connection and no plant name |
| `root_plant_port` | `ValidationError` | A plant that is not a registered building block has a plant port; `validate` reports it |
| `invalid_binding` | `ValidationError` | A binding does not fit the plant or the data |
| `missing_column` | `ValidationError` | A bound column is not in the run input |
| `invalid_design` | `ValidationError` | Equipment design data is missing or inconsistent at call time, or a calibration request does not fit the plant |
| `invalid_definition` | `DefinitionError` | Declarations, children, hooks, formulas, outputs or outlets of a class written wrongly |
| `out_of_range` | `PhysicsError` | An input is outside the domain of a correlation |
| `no_convergence` | `PhysicsError` | An iterative solve did not converge |
| `loop_not_converged` | `PhysicsError` | A loop of a plant did not converge; the path names its tear stream. In a run its row code is `no_convergence` |
| `missing_chemistry` | `PhysicsError` | A correlation needs fluid chemistry that was not given |
| `too_little_data` | `PhysicsError` | A fit or estimate has too few valid observations |
| `invalid_data` | `RunError` | A dataset or profile cannot be built or read |
| `inputs_missing` | `RunError` | A file of `inputs/` is needed and the folder is absent: it takes a source checkout, because `inputs/` is not installed |
| `clock` | `RunError` | An invalid clock, or a timestamp that is not a tick |
| `checkpoint` | `RunError` | A checkpoint cannot be written, read or resumed |
| `step` | `RunError` | A replayed twin failed under `on_error="raise"`; the cause is chained |
| `cancelled` | `Cancelled` | A callback stopped the run |
| `not_implemented` | `NotImplementedYet` | The name is final, its work lands later |

`gm.errors.ROW_CODES` maps every row code of `Results.errors()` to its meaning:

| Row code | Meaning |
| --- | --- |
| `missing_value` | A bound column has no finite value at this tick; the row was skipped |
| `invalid_inlet` | An inlet stream breaks the stream limits; the row failed |
| `out_of_bounds` | A control, boundary or output is outside its bounds; the row failed |
| `out_of_range` | An input is outside the domain of a correlation; the row failed |
| `no_convergence` | An iterative solve did not converge; the row failed |
| `module_error` | A module raised any other error; the row failed |

## Message style

Write `<module path>: <field> = <value> <unit>; expected <what>[; did you mean 'x'?]`, for example
`units.convert: unit = 'K'; expected a unit of 'Pa' to convert from 'bar'`. Use
`gemini._utils.strings.did_you_mean` for the suggestion and `join_names` for lists of valid names.

## Adding a code

There is no new class for a new situation: add a code to `CODES` in `gemini/errors/base.py`, with a
row in the table above, raise the class it belongs to with `code=`, and test it. An `ops.check` takes
the same `code=` beside the class. Then update this document.
