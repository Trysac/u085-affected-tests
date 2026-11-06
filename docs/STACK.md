# Stack

## Used

| Tool | Why |
|---|---|
| Python >= 3.10 | Minimum version declared for the package; the code uses `from __future__ import annotations` and `str.removeprefix`. |
| Python standard library only | `ast`, `os`, `posixpath`, `re`, `subprocess`, `pathlib`, `collections`, `dataclasses`, `functools`, `logging`, `argparse`, `json`. No third-party imports exist in `src/affected_tests`. |
| `typing.Literal` | Types the `code` of `AffectedTestsError`. |

## Discarded

| Tool | Why not |
|---|---|
| pytest-testmon | Needs a coverage database from a previous run; this tool is stateless. See the README. |
| Importing project modules to discover imports | Would execute project code. Module discovery uses `ast.parse` only. |
| A shell for git | Git is started with an argument list and `shell=False`, so the base ref cannot inject shell syntax. |
