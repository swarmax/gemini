# Contributing

GEMINI supports Python 3.11, 3.12, 3.13 and 3.14. Install the package with its development
dependency groups with `poetry install` or with `uv pip install -e . --group dev`. Read
[AGENTS.md](AGENTS.md) and the documents it links before changing equipment or physics; the implementation rules are in
[.claude/docs/conventions.md](.claude/docs/conventions.md).

## Bug reports

Describe what you ran, what you expected and what happened, and include the output of:

```bash
python -m gemini._utils.collect_env
```

It prints the Python, platform, GEMINI and dependency versions and the git commit.

## Development process

Coding agents follow the branching rule in [AGENTS.md](AGENTS.md#branching). Human contributors
work as follows:

- create a feature branch from `main`;
- make the change, including tests and documentation, and commit with a clear message;
- push the branch and open a pull request into `main`;
- discuss with the reviewer what changes are needed; the reviewer merges once every discussion is
  resolved;
- record user-visible changes under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md).

CI runs the development test profile on pushes to feature branches and on pull requests into other
branches, and the release profile on pushes to `main`, on release tags, on pull requests into
`main` and in merge queues; a manual run of the Test workflow runs the release profile on any
branch. Every run covers Python 3.11 to 3.14 with the newest dependencies, plus the declared lower
bounds (`uv pip install --resolution lowest-direct`) on 3.11 and 3.14; free-threaded 3.14t and
the 3.15 beta run as non-blocking jobs. Lint runs on every push, pull request and merge queue.

## Code quality guidelines

Quality guidelines serve to improve quality. They should not be busy work nor work against
developers. They should be of value.

### Code review

- Every pull request must be reviewed by at least one other developer and all comments must be
  resolved.
- No linting issues may remain before merging.
- Code reviews are not about distrust. They are about sharing knowledge about the code base,
  sharing knowledge about writing code and increasing quality by collaboration.

### Units and defaults

- A value with a unit is a `gm.units.Quantity` or `{"value", "unit"}`; never accept or write unit
  text such as `"150 m3/h"`.
- Nothing a user must decide has a default: a field is required or absent, and a call that needs it
  raises `missing_value` naming its path. Both rules are in
  [AGENTS.md](AGENTS.md#start-here) and [conventions.md](.claude/docs/conventions.md#units), and
  `tests/unit/test_code_quality.py` checks what it can.

### Documentation

- Every function has a docstring that summarises what it does and explains its arguments and
  return value where they are not obvious. Code has no explanatory comments; see the comment rule
  in [conventions.md](.claude/docs/conventions.md#comments).

### Linting

- Linting maintains a shared quality of the code base across repositories. Run `make lint`
  (flake8 with docstring and complexity checks, black and isort).
- Rules of the linter may only be ignored when approved by the software leads. Prefer to silence
  one line with `# noqa: <code>` over ignoring a rule everywhere.

### Testing

Run `make test` (the development profile: the tests of what changed and of everything that
imports it) while developing and before every commit. Always test what changed and everything
that imports it; never run the full suite locally. `make test-release` is the release profile
(every tier on the full-year dataset) that CI runs before merging into `main`. The profiles, tier
markers, one-second test budget, shared fixtures, datasets and golden workflow are defined in
[.claude/docs/testing.md](.claude/docs/testing.md).

- Every function should be covered by a unit test in the mirrored file under `tests/unit/`. Some
  functions allow more easily for unit tests and some are not worth unit testing; this is up to
  the team's discretion.
- A unit test should test some significant amount of code. If the test function is similar or
  equal to the logic being tested, the amount of code being tested is too small. If the test
  function tests whole modules or multiple layers of code, the amount of code being tested is too
  big. The amount of code being tested is referred to as the 'unit-under-test'.
- Use mocks to isolate the unit-under-test where applicable.
- A bug fix starts with a test that fails without the fix.
