# Architecture

## Purpose

`trysac-affected-tests` (import name `affected_tests`) is a small Python library with no runtime dependencies. It selects the Python test files affected by changed files, using a static import graph built with `ast.parse`, and falls back to running the whole suite when it cannot be sure.

## Shape

```text
caller code / CLI (__main__.py)
        |
        +-- affected_tests/__init__.py   (public API, __all__)
               |
               +-- _core.py      build_graph, ImportGraph, affected_tests, AffectedResult
               +-- _git.py       GitDiffSource (runs git diff)
               +-- _errors.py    AffectedTestsError, clip
```

- **Public API**: the names listed in `__all__` of `src/affected_tests/__init__.py`: `AffectedResult`, `AffectedTestsError`, `GitDiffSource`, `ImportGraph`, `__version__`, `affected_tests`, `build_graph`. Other names are internal.
- **Graph building** (`build_graph`): discovers `.py` files under the source roots, parses each with `ast.parse`, maps each file to a dotted module name, and records import edges and dynamic-import calls. The result is an immutable `ImportGraph`.
- **Selection** (`affected_tests`): normalises the changed paths, maps them to modules, walks the reverse import graph with an iterative breadth-first search and a visited set, and intersects the result with the test files. Unmappable changes and the always-run-all patterns set `run_all`.
- **Git input** (`GitDiffSource`): validates the base ref, runs `git diff --name-only -z` with `shell=False`, a timeout and `cwd` set to the root, and re-bases paths onto the root.
- **Side effects**: `build_graph` reads files under `root` and walks the directory tree. `GitDiffSource.changed_files` starts a git subprocess. `affected_tests` is pure over the graph. The module logs through `logging.getLogger(__name__)` with a `NullHandler`.
- **Errors**: `AffectedTestsError` carries a stable `code` (`invalid_ref`, `git_failed`, `root_missing`). Invalid numeric limits and invalid source roots or globs raise `ValueError`.
- **CLI**: `python -m affected_tests` (`main(argv)` in `__main__.py`) maps errors to exit codes: 0 on success, 1 for `invalid_ref` and `git_failed`, 2 for usage errors, `root_missing` and I/O errors.

## Quality contract

Tests are under `tests/` and run with pytest. See [TESTING.md](TESTING.md).

## Decisions

The interpretation choices made during implementation:

1. `ImportGraph` has an extra public field `truncated`, set when `max_files` stops discovery. A relevant change then sets `run_all` with reason `graph-truncated`.
2. Under the catch-all `.` source root, a non-test `.py` file in a directory chain without `__init__.py` that has no importers (for example `scripts/x.py`) counts as unmapped and sets `run_all`. Files under `src` with no importers select nothing.
3. When `run_all` is true, `AffectedResult.tests` lists every known test file and `reasons` is `{"*": [...]}`.
4. Always-run-all patterns match the full relative path or the basename. Deeper `conftest.py` files select the tests under their directory instead.
5. Dynamic-import tests are added only when at least one changed `.py` or `conftest.py` file is present.
6. `--files` paths are relative to `--root`. `git diff` paths are relative to the repository top level, which is found by looking for `.git` upwards; the git command line is fixed.
7. Invalid numeric or root arguments raise `ValueError`, because the error codes cover only refs, git and the root directory.
