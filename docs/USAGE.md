# Usage of affected-tests

`affected_tests` selects the Python test files that a change can affect, using a static import
graph built with `ast`. It never imports or executes project code and needs no previous run or
coverage database.

## Library

```python
from pathlib import Path
from affected_tests import GitDiffSource, affected_tests, build_graph

graph = build_graph(Path("."))
changed = GitDiffSource(Path("."), "main").changed_files()
result = affected_tests(graph, changed)
print(result.run_all, result.tests, result.reasons)
```

## Command line

```
python -m affected_tests [--root .] (--base REF | --files PATH ...) [--format lines|json]
```

- `lines` prints one test path per line; when everything must run it prints the single line
  `tests`. Warnings go to stderr.
- `json` prints an object with the keys `run_all`, `tests`, `reasons` and `warnings`.
- `--files` paths are relative to `--root`; backslashes are accepted.
- Exit codes: 0 success, 1 invalid ref or git failure, 2 usage error, missing root or I/O error.

## Resolution rules

- Every `import` and `from ... import` node counts, including inside functions, `try` blocks and
  `if TYPE_CHECKING:`. Strings and comments never do.
- Importing a package depends on its `__init__.py`, so re-exports are followed.
- `from x import y` depends on the submodule `x.y` when it exists, otherwise on `x`.
- Names outside the project are ignored.
- A changed test selects itself; a nested `conftest.py` selects the tests below its directory.
- Run everything when a root `conftest.py`, `pyproject.toml`, `setup.cfg`, `setup.py`,
  `requirements*.txt`, `tox.ini` or `noxfile.py` changes, or when a changed `.py` file cannot be
  mapped to the project (outside the source roots, or a script-like file nobody imports).
- Test files calling `importlib.import_module` or `__import__` are selected whenever a Python
  file changed.
- Deleted files are resolved by module name.

## Limits

At most 50 000 files, 1 MiB per file, 10 000 changed paths and 1000 warnings are processed by
default. A truncated graph forces a run-all result. `git diff` paths are relative to the top level
of the repository and only committed changes since the merge base are seen.
