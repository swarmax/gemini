# Legacy bridge

The package reads no old GEMINI file. `gm.Plant.from_legacy`, `gm.plants.convert_legacy`,
`gemini.data.legacy` and `gemini/plants/_utils/legacy/` are removed, and nothing in `gemini/`
interprets old names, tags, tables or node mappings. `paths.legacy_project` is removed too.

What the tests still need of the old format lives in `scripts/legacy/`, outside the package; tests
import it as `scripts.legacy`:

- `project.py`: `GeminiProject.from_folder(folder)` parses `diagram.json` and the `.param` files
  into typed models.
- `tables.py`: the old-name tables (`PORTS`, `NODE_PATHS`, `RISERS`, `TRACE_CONTROLS`, ...) and the
  property converters (`from_property`, `reservoir_params_from_gemini`,
  `productionwell_params_from_gemini`, `injectionwell_params_from_gemini`,
  `heatexchanger_params_from_gemini`, ...).
- `wiring.py`: `check_wiring(plant, project)` compares the stream identities of one step of a copy
  of the plant with the old diagram and returns an empty list when the wiring matches.

The old project folder is `inputs/legacy_project/` (`tests.fixtures.OLD_PROJECT`). It is read by the
golden reconstructions of the subsurface, wells and exchangers unit tests, by
`tests/unit/modules/test_monitoring_golden.py` and by the `check_wiring` audits of
`tests/integration/test_plant.py` and `tests/e2e/test_full_replay.py`. Nothing converts an old
project into a plant any more: write the plant in Python or as a plant dict
([plants.md](plants.md)).
