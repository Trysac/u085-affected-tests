# affected-tests

[![PyPI version](https://img.shields.io/pypi/v/trysac-affected-tests)](https://pypi.org/project/trysac-affected-tests/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-affected-tests)](LICENSE)
[![CI](https://github.com/Trysac/u085-affected-tests/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u085-affected-tests/actions/workflows/ci.yml)

Select the Python test files affected by changed files using a static ast import graph, with conservative run-all triggers.

## Problem

Large Python test suites slow every pull request even when a change touches one module. pytest-testmon needs a coverage database from a previous run. `affected_tests` builds a static import graph with `ast.parse` (project code is never imported or executed) and returns the test files a change can affect. When it cannot be sure, it reports that the whole suite must run. It keeps no state between runs and has no runtime dependencies.

## Install

```sh
pip install trysac-affected-tests
# or
uv add trysac-affected-tests
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from pathlib import Path
from affected_tests import affected_tests, build_graph

graph = build_graph(Path("."))
result = affected_tests(graph, ["src/pkg/a.py"])
if result.run_all:
    print("run the whole suite")
else:
    print("\n".join(result.tests))
```

CLI:

```sh
affected-tests --base main                      # committed changes since the merge base
affected-tests --files src/pkg/a.py tests/x.py  # explicit paths, relative to --root
affected-tests --base main --format json        # keys: run_all, tests, reasons, warnings
```

The `lines` format prints one test path per line, or the single line `tests` when everything must run. Warnings go to stderr in `lines` format and into the `warnings` key in `json` format.

## Public API

Import everything from `affected_tests`: `build_graph`, `ImportGraph`, `affected_tests`, `AffectedResult`, `GitDiffSource`, `AffectedTestsError`, `__version__`.

- `build_graph(root, *, source_roots=("src", "."), test_globs=("tests/**/test_*.py", "tests/**/*_test.py"), max_files=50_000, max_file_bytes=1_048_576) -> ImportGraph`. Raises `AffectedTestsError` with code `root_missing` when `root` is not a directory, and `ValueError` for non-positive limits or an invalid source root or glob.
- `ImportGraph`: attributes `root`, `test_files`, `warnings`, `truncated`; methods `module_for(path)`, `imports_of(module)`, `importers_of(module, *, transitive=True)`.
- `affected_tests(graph, changed, *, always_run_all=("pyproject.toml", "setup.cfg", "setup.py", "conftest.py", "requirements*.txt", "tox.ini", "noxfile.py")) -> AffectedResult`. `AffectedResult` has `tests` (sorted POSIX paths), `run_all`, `reasons` (test path to triggering changed paths, or `dynamic-import`; `{"*": [...]}` when `run_all`) and `warnings`.
- `GitDiffSource(root, base, *, timeout=30.0).changed_files() -> list[str]`. Lists committed changes between the merge base of `base` and `HEAD`. Raises `AffectedTestsError` with code `invalid_ref`, `root_missing` or `git_failed`.
- `AffectedTestsError` has a `code` attribute: `invalid_ref`, `git_failed` or `root_missing`.

A changed `.py` file that cannot be mapped to the project, a root `conftest.py`, or a file matching `always_run_all` sets `run_all`. Changed paths that resolve outside the root are dropped with a warning.

## Limits

- Only `import` and `from ... import` statements are read. Dynamic imports are handled only by a conservative rule: a test file containing `importlib.import_module` or `__import__` is always selected.
- Imports of names outside the project are ignored.
- Files larger than `max_file_bytes` (default 1 MiB) are skipped with a warning. Discovery stops at `max_files` (default 50,000) and sets `truncated`.
- Symbolic links are not followed during discovery and are reported as warnings.
- At most 1000 warnings are kept, followed by one `and N more` entry.
- At most 10,000 changed paths are processed; more selects every test with reason `too-many-changed-files`.
- Path arguments are limited to 4096 characters; glob patterns to 200 characters.
- `GitDiffSource` sees only committed changes; uncommitted work is not included. Its base ref must match `^[A-Za-z0-9_][A-Za-z0-9._/~^-]{0,199}$` and must not contain `..`.
- Git runs with a 30-second default timeout and without a shell.
- Deeper `conftest.py` files select only the tests under their directory.

## Why not pytest-testmon

pytest-testmon records coverage during a run and stores it in a database, so it needs a previous run to select tests. `affected-tests` is stateless: it reads the source code statically, needs no previous run and has no dependencies. It is less precise than coverage-based selection, because it works from import relationships and not from executed lines.

## Security

See [docs/SECURITY.md](docs/SECURITY.md) for the threat model and its limits.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [LLM index](llms.txt)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
