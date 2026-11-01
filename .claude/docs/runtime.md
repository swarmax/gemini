# Runtime settings

`gm.runtime` (`gemini/runtime/context.py`) contains process defaults that should not be design parameters:

- `set_default_fluid` / `get_default_fluid`
- `set_precision("float64" | "float32")` / `get_precision`
- `set_display_units("si" | "field")` / `get_display_units`
- `get_processes()`
- `state()`
- `settings(**changes)`

Use `with gm.runtime.settings(precision="float32", display_units="field"):` or the same call as a
decorator for temporary changes; it is built on `gemini._utils.context.ContextSetting`, nests, and
restores the previous settings on exit. Settings are context-local: they live in one
`contextvars.ContextVar`, so a change applies to the current context only. asyncio tasks start
from a copy of their creator's settings, while new threads start from the defaults; code that
hands work to threads passes `state()` along or runs it in `contextvars.copy_context()`.

`state()` returns a JSON-safe copy of the settings; `settings(**state())` applies a complete one.
`processes` is the number of worker processes the trials of a study run in (a whole number of at
least 1, 1 meaning a serial run). `gm.study.sample`, `sensitivity` and `minimize` run their
independent trials in that many processes (`minimize`: one search per doublet count) and return
the numbers and the order of a serial run. A worker applies the settings of its parent with one
process, so it starts no pool of its own; a script that sets `processes` above 1 needs the usual
`if __name__ == "__main__":` guard, because workers start from a `forkserver`.
Unknown setting names and values outside the choices raise `gm.errors.ValidationError`; an invalid fluid raises a validation error.

Precision selects the ESP's legacy float32 arithmetic, used for golden parity. Display units
affect module representations only. A default fluid is copied into newly built modules and
streams; explicit fluids always win. Checkpoints store the settings captured when a run starts.
`gm.resume` and `gm.live`, like `Engine.resume` and `Engine.live`, re-apply the saved precision and
display units for their run; the default fluid is not re-applied because the plant already carries
its fluids.
