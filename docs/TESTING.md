# Testing

## Running

```sh
uv run pytest --cov=affected_tests   # tests with coverage report
```

## Policy

- Tests exercise the public API (`import affected_tests`) and the CLI entry point `main`.
- The specification's acceptance criteria define the behaviour the tests must check:
  - resolution of `import`, `from ... import` (absolute and relative) and package `__init__.py` re-exports;
  - imports inside functions, `try` blocks and `if TYPE_CHECKING:` count, while strings and comments do not;
  - a changed test file selects itself; a changed `tests/api/conftest.py` selects the tests under `tests/api`;
  - `pyproject.toml`, root `conftest.py` and unmapped `scripts/x.py` set `run_all`;
  - a syntax error or `RecursionError` during parsing becomes a warning and adds no edges;
  - a test containing `importlib.import_module` is always selected with reason `dynamic-import`;
  - a fixture module with top-level side effects is not executed by `build_graph`;
  - `GitDiffSource` rejects an option-like ref with `invalid_ref` before any subprocess call, and builds the exact git argument list for a valid ref;
  - the CLI prints nothing and returns 0 for a non-matching file, and `--format json` prints exactly the keys `run_all`, `tests`, `reasons`, `warnings`.
- Tests must be deterministic: no network, no dependence on wall-clock time or test order.

## Layout

Test files are placed under `tests/`. The specification names `tests/conftest.py` for shared fixtures. The file list is not recorded in this document; check the `tests/` directory for the files that exist.
