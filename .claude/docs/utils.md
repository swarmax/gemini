# Utilities

`gemini/_utils/` holds general-purpose helpers that know nothing about geothermal physics, modules
or the engine. Its topic files are a leaf package: they import only the standard library and
installed dependencies, never another part of `gemini` (`tests/unit/test_package_boundaries.py`
enforces this). They therefore cannot raise `gm.errors` classes; their helpers raise built-in exceptions such
as `TypeError` and `ValueError`, and callers that need a GEMINI error convert them. `paths.py` is the
exception, and `registry.py` another: they import `gemini.errors`, the other leaf, to raise
`inputs_missing` and `duplicate_name`. Import helpers
from their topic module, for example `from gemini._utils.strings import did_you_mean`;
`gemini/_utils/__init__.py` exports nothing.

- `strings.py`: `snake_case`, `first_paragraph`, `join_path`, `split_path`, `join_names`,
  `close_matches`, `did_you_mean`.
- `jsonable.py`: `to_plain`, the one conversion of returned data to plain JSON (NumPy to Python,
  NaN and infinity to `None`); every public function that returns data uses it.
- `time.py`: `to_utc`, `to_utc_index`, `to_timedelta`, `median_step`, `interval_seconds`,
  `DEFAULT_STEP`.
- `hooks.py`: `RemovableHandle` (ordered hook dicts, safe double `remove()`), `has_signature`.
- `mappings.py`: `AttributeMapping` (base of `Ports` and `Values`), `get_nested`, `set_nested`.
- `context.py`: `ContextSetting`, a context variable change usable as `with` and as a decorator.
- `files.py`: `from_json`, `to_json` and the lossless JSON-cell tables (`encode_cell`,
  `encode_cells`, `decode_cells`, `to_cells`, `from_cells`) used by the rows a checkpoint keeps.
- `registry.py`: the one registry of module and plant classes (`register`, `names`, `get`,
  `categories`, `CATEGORIES`), filled by `Module.__init_subclass__`
  ([modules.md](modules.md#registry-categories-and-streams)).
- `paths.py`: where the data folder is, and the only code that knows ([data.md](data.md#where-data-lives)):
  `plant_values(name)`,
  and `doublet_heat(name)` below `inputs/`, which raise `inputs_missing` when it
  is absent.
- `version.py`: `package_version`, read from `pyproject.toml` or the package metadata, and
  `is_older`, the rule that refuses files written before `OLDEST_READABLE`.
- `collect_env.py`: `python -m gemini._utils.collect_env` prints the versions a bug report needs.

The demand frame is not here: it is `gemini/case/_utils/demand.py`. The place of every folder in the dependency order is
in [conventions.md](conventions.md#dependencies).

## Adding a helper

Add a helper only when at least two places need it, or when it removes a duplicate. Put it in the
file of its topic (no `misc.py` or `helpers.py`), give it a docstring, replace every duplicate in
the same commit and add a test to the mirrored `tests/unit/_utils/test_<file>.py`. A new topic file
needs its own mirror, which `tests/unit/test_mirror.py` requires. Physics, units and quantities
belong in `physics` and `types`; code that needs modules or the engine stays in those
packages.
