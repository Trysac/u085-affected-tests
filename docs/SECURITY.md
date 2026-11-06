# Security notes

## Threat model

`trysac-affected-tests` reads Python source files under a project root and runs `git diff` for a caller-supplied base ref. Its inputs (project files, changed paths, base ref) may come from untrusted sources such as a pull request.

### Defended

- **Code execution from project files**: project code is parsed with `ast.parse` only. It is never imported, compiled or executed. A fixture module with top-level side effects leaves no trace after `build_graph`.
- **Option injection through the base ref**: `GitDiffSource` rejects any base that does not match `^[A-Za-z0-9_][A-Za-z0-9._/~^-]{0,199}$` or that contains `..`. The ref therefore cannot start with `-`.
- **Shell injection**: git is started with an argument list and `shell=False`.
- **Hung git process**: git runs with a timeout (default 30 seconds).
- **Path escape**: changed paths are normalised to POSIX form; absolute paths and paths that resolve outside the root are dropped with a warning. Paths containing NUL characters, longer than 4096 characters, or equal to `.`/`..` are rejected.
- **Symbolic links**: symbolic links to Python files are skipped during discovery with a warning. Directories are not followed by the directory walk.
- **Oversized files**: files above `max_file_bytes` (default 1 MiB) are not parsed.
- **Parser failures**: `SyntaxError`, `RecursionError`, `MemoryError`, `ValueError` and `OverflowError` raised while parsing one file are caught and reported as warnings; the file adds no edges. Unreadable files are skipped with a warning.
- **Unbounded inputs**: discovery stops at `max_files` (default 50,000); changed paths above 10,000 select every test; warnings are capped at 1000; git output is capped by a character limit, and git stderr in errors is cut to 200 characters.

### Not defended

- **Resource use inside one file**: a file below the size limit can still take time or memory to parse. Only `RecursionError` and `MemoryError` raised during parsing are caught.
- **Git itself**: the tool does not sandbox git. It runs `git -c core.fsmonitor=false diff` in the caller's repository and trusts the repository's git configuration otherwise.
- **Symbolic links inside the tree**: a symbolic link is skipped only for files; the tool does not check whether a directory it reads is reached through a link outside the root.
- **Uncommitted changes**: they are not seen by `GitDiffSource`, so a caller relying on it for a safety decision must supply the file list explicitly.
- **Selection completeness**: dynamic imports other than `importlib.import_module` and `__import__` (for example `exec`, string-built module names outside those calls) are not detected. Imports of names outside the project are ignored.

## Publishing

The package is published under the name `trysac-affected-tests`. This repository does not contain release automation code, so no publishing claim is made here.

To report a vulnerability, see [SECURITY.md](../SECURITY.md).
