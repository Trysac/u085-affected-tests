"""Static import graph construction and affected-test selection."""

from __future__ import annotations

import ast
import logging
import os
import posixpath
import re
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ._errors import AffectedTestsError, clip

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

MAX_WARNINGS = 1000
MAX_CHANGED_FILES = 10_000
MAX_PATH_LENGTH = 4096
MAX_PATTERN_LENGTH = 200
DEFAULT_SOURCE_ROOTS: tuple[str, ...] = ("src", ".")
DEFAULT_TEST_GLOBS: tuple[str, ...] = ("tests/**/test_*.py", "tests/**/*_test.py")
DEFAULT_ALWAYS_RUN_ALL: tuple[str, ...] = (
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "conftest.py",
    "requirements*.txt",
    "tox.ini",
    "noxfile.py",
)
_SKIPPED_DIRS = frozenset({"__pycache__", "node_modules", "site-packages", "venv"})
_DYNAMIC_NAMES = frozenset({"__import__", "import_module"})
_BACKSLASH = chr(92)
_NUL = chr(0)


class _Warnings:
    """Collects warnings, keeping at most ``MAX_WARNINGS`` of them."""

    def __init__(self) -> None:
        self._items: list[str] = []
        self._extra = 0

    def add(self, message: str) -> None:
        if len(self._items) < MAX_WARNINGS:
            self._items.append(message)
        else:
            self._extra += 1

    def finish(self) -> tuple[str, ...]:
        if self._extra:
            return (*self._items, f"and {self._extra} more")
        return tuple(self._items)


@lru_cache(maxsize=128)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Compile a POSIX glob where ``**/`` spans zero or more directories."""
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise ValueError("glob pattern too long")
    text = pattern.replace(_BACKSLASH, "/")
    out: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif text.startswith("**", index):
            out.append(".*")
            index += 2
        elif text[index] == "*":
            out.append("[^/]*")
            index += 1
        elif text[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(text[index]))
            index += 1
    return re.compile("".join(out))


def _normalize(raw: object, root: str) -> str | None:
    """Return ``raw`` as a POSIX path relative to ``root`` or ``None`` if unusable."""
    if not isinstance(raw, str) or not raw or _NUL in raw or len(raw) > MAX_PATH_LENGTH:
        return None
    text = raw.replace(_BACKSLASH, "/")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        absolute = posixpath.normpath(text)
        prefix = root.rstrip("/") + "/"
        if not absolute.startswith(prefix):
            return None
        text = absolute.removeprefix(prefix)
    normalized = posixpath.normpath(text)
    if normalized in {".", ".."} or normalized.startswith(("../", "/")):
        return None
    return normalized


def _normalize_root(value: str) -> str:
    cleaned = posixpath.normpath(value.replace(_BACKSLASH, "/")) if value else "."
    if cleaned == ".":
        return ""
    if cleaned.startswith("/") or cleaned == ".." or cleaned.startswith("../"):
        raise ValueError(f"invalid source root: {clip(value)}")
    return cleaned


def _dotted(rel: str) -> str | None:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def _module_info(
    path: str, roots: tuple[str, ...], pkg_dirs: frozenset[str]
) -> tuple[str | None, bool]:
    """Map ``path`` to ``(dotted module, script_like)`` under the first containing root.

    ``script_like`` marks files mapped through the catch-all ``.`` root whose directories are
    not regular packages (no ``__init__.py``), for example ``scripts/x.py``.
    """
    for root in roots:
        prefix = f"{root}/" if root else ""
        if not path.startswith(prefix):
            continue
        rel = path.removeprefix(prefix)
        name = _dotted(rel)
        script_like = False
        if name is not None and not root and "/" in rel:
            chain: list[str] = []
            for directory in rel.split("/")[:-1]:
                chain.append(directory)
                if "/".join(chain) not in pkg_dirs:
                    script_like = True
                    break
        return name, script_like
    return None, False


def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name in _SKIPPED_DIRS


def _discover(root: str, max_files: int, warnings: _Warnings) -> tuple[list[str], bool]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not _skip_dir(name))
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        prefix = "" if rel_dir == "." else rel_dir + "/"
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            rel = prefix + name
            if os.path.islink(os.path.join(dirpath, name)):
                warnings.add(f"{clip(rel)}: symbolic link skipped")
                continue
            if len(found) >= max_files:
                warnings.add(f"file limit of {max_files} reached; the graph is incomplete")
                return sorted(found), True
            found.append(rel)
    return sorted(found), False


def _parse_file(path: str, rel: str, limit: int, warn: _Warnings) -> ast.Module | None:
    label = clip(rel)
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError:
        warn.add(f"{label}: unreadable file skipped")
        return None
    if len(data) > limit:
        warn.add(f"{label}: larger than {limit} bytes, skipped")
        return None
    try:
        return ast.parse(data, filename=rel)
    except SyntaxError as exc:
        warn.add(f"{label}: syntax error at line {exc.lineno}")
    except RecursionError:
        warn.add(f"{label}: nesting too deep to parse")
    except MemoryError:
        warn.add(f"{label}: out of memory while parsing")
    except (ValueError, OverflowError):
        warn.add(f"{label}: invalid source text")
    return None


def _resolve_base(node: ast.ImportFrom, package: str | None) -> str | None:
    if node.level == 0:
        return node.module or ""
    if package is None:
        return None
    parts = package.split(".") if package else []
    strip = node.level - 1
    if strip > len(parts):
        return None
    keep = len(parts) - strip
    parts = parts[:keep]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _is_dynamic_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in _DYNAMIC_NAMES
    return isinstance(func, ast.Name) and func.id in _DYNAMIC_NAMES


def _extract(tree: ast.AST, module: str | None, is_init: bool) -> tuple[frozenset[str], bool]:
    """Collect absolute dotted import names and whether a dynamic import call exists."""
    if module is None:
        package: str | None = None
    else:
        package = module if is_init else module.rpartition(".")[0]
    names: set[str] = set()
    dynamic = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_base(node, package)
            if base is None:
                continue
            if base:
                names.add(base)
            for alias in node.names:
                if alias.name != "*":
                    names.add(f"{base}.{alias.name}" if base else alias.name)
        elif isinstance(node, ast.Call) and _is_dynamic_call(node):
            dynamic = True
    return frozenset(names), dynamic


@dataclass(frozen=True)
class AffectedResult:
    """Outcome of :func:`affected_tests`.

    ``tests`` is the sorted list of POSIX test paths to run (every known test when ``run_all``
    is true). ``reasons`` maps each selected test to the changed paths (or the marker
    ``dynamic-import``) that selected it; with ``run_all`` it is ``{"*": [triggers]}``.
    """

    tests: list[str]
    run_all: bool
    reasons: dict[str, list[str]]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ImportGraph:
    """Static import graph of a project; build it with :func:`build_graph`.

    Attributes:
        root: Resolved project root.
        test_files: POSIX paths of the files matching the test globs.
        warnings: Problems met while building (capped, last entry may be ``and N more``).
        truncated: True when ``max_files`` stopped the scan, so the graph is incomplete.
    """

    root: Path
    test_files: frozenset[str]
    warnings: tuple[str, ...]
    truncated: bool
    _files: dict[str, str | None] = field(repr=False, compare=False)
    _mod2path: dict[str, str] = field(repr=False, compare=False)
    _rev: dict[str, frozenset[str]] = field(repr=False, compare=False)
    _edges: dict[str, frozenset[str]] = field(repr=False, compare=False)
    _raw_by_name: dict[str, frozenset[str]] = field(repr=False, compare=False)
    _dynamic: frozenset[str] = field(repr=False, compare=False)
    _pkg_dirs: frozenset[str] = field(repr=False, compare=False)
    _roots: tuple[str, ...] = field(repr=False, compare=False)
    _test_globs: tuple[str, ...] = field(repr=False, compare=False)

    def module_for(self, path: str) -> str | None:
        """Return the dotted module for a project path, or ``None`` when it has none."""
        normalized = _normalize(path, self.root.as_posix())
        if normalized is None or not normalized.endswith(".py"):
            return None
        if normalized in self._files:
            return self._files[normalized]
        return _module_info(normalized, self._roots, self._pkg_dirs)[0]

    def imports_of(self, module: str) -> frozenset[str]:
        """Return the project modules imported directly by ``module``."""
        path = self._mod2path.get(module)
        if path is None:
            return frozenset()
        names = (self._files.get(target) for target in self._edges.get(path, ()))
        return frozenset(name for name in names if name is not None)

    def importers_of(self, module: str, *, transitive: bool = True) -> frozenset[str]:
        """Return the modules that import ``module`` (directly, or transitively by default)."""
        path = self._mod2path.get(module)
        if path is None:
            return frozenset()
        direct = set(self._rev.get(path, ()))
        reached = self._closure({path}) - {path} if transitive else direct
        names = (self._files.get(item) for item in reached)
        return frozenset(name for name in names if name is not None)

    def _closure(self, seeds: Iterable[str]) -> set[str]:
        visited = set(seeds)
        queue = deque(visited)
        while queue:
            current = queue.popleft()
            for importer in self._rev.get(current, ()):
                if importer not in visited:
                    visited.add(importer)
                    queue.append(importer)
        return visited

    def _seeds_by_name(self, module: str) -> set[str]:
        seeds = set(self._raw_by_name.get(module, ()))
        prefix = module + "."
        for name, paths in self._raw_by_name.items():
            if name.startswith(prefix):
                seeds.update(paths)
        return seeds

    def _matches_test_glob(self, path: str) -> bool:
        return any(_glob_regex(pattern).fullmatch(path) for pattern in self._test_globs)


def build_graph(
    root: Path | str,
    *,
    source_roots: Sequence[str] = DEFAULT_SOURCE_ROOTS,
    test_globs: Sequence[str] = DEFAULT_TEST_GLOBS,
    max_files: int = 50_000,
    max_file_bytes: int = 1_048_576,
) -> ImportGraph:
    """Parse the Python files under ``root`` and build a static import graph.

    Files are only parsed with ``ast.parse``; nothing is imported or executed. Hidden
    directories, ``__pycache__``, ``node_modules``, ``venv`` and ``site-packages`` are skipped.

    Raises:
        AffectedTestsError: ``root_missing`` when ``root`` is not a directory.
        ValueError: for non-positive limits or an invalid source root or glob.
    """
    if max_files < 1 or max_file_bytes < 1:
        raise ValueError("max_files and max_file_bytes must be positive")
    base = Path(root)
    if not base.is_dir():
        raise AffectedTestsError("root_missing", "root is not an existing directory")
    root_path = base.resolve()
    roots_in = [source_roots] if isinstance(source_roots, str) else list(source_roots)
    globs = (test_globs,) if isinstance(test_globs, str) else tuple(test_globs)
    roots = tuple(dict.fromkeys(_normalize_root(item) for item in roots_in))
    test_res = [_glob_regex(item) for item in globs]
    warnings = _Warnings()
    root_str = str(root_path)
    paths, truncated = _discover(root_str, max_files, warnings)
    pkg_dirs = frozenset(
        posixpath.dirname(item) for item in paths if posixpath.basename(item) == "__init__.py"
    )

    files: dict[str, str | None] = {}
    script_like: dict[str, bool] = {}
    tests: set[str] = set()
    for path in paths:
        name, script = _module_info(path, roots, pkg_dirs)
        if any(pattern.fullmatch(path) for pattern in test_res):
            tests.add(path)
            if name is None:
                name = _module_info(path, ("",), pkg_dirs)[0]
        files[path] = name
        script_like[path] = script

    mod2path: dict[str, str] = {}
    for path in sorted(paths, key=lambda item: (script_like[item], item)):
        name = files[path]
        if name is None:
            continue
        if name in mod2path:
            warnings.add(f"{clip(path)}: duplicate module {clip(name)}, not an import target")
            continue
        mod2path[name] = path

    raw_by_path: dict[str, frozenset[str]] = {}
    dynamic: set[str] = set()
    for path in paths:
        full = os.path.join(root_str, *path.split("/"))
        tree = _parse_file(full, path, max_file_bytes, warnings)
        if tree is None:
            continue
        is_init = posixpath.basename(path) == "__init__.py"
        names, is_dynamic = _extract(tree, files[path], is_init)
        raw_by_path[path] = names
        if is_dynamic and path in tests:
            dynamic.add(path)

    edges: dict[str, frozenset[str]] = {}
    rev_sets: dict[str, set[str]] = {}
    raw_sets: dict[str, set[str]] = {}
    for path, names in raw_by_path.items():
        targets: set[str] = set()
        for name in names:
            raw_sets.setdefault(name, set()).add(path)
            parts = name.split(".")
            for count in range(1, len(parts) + 1):
                target = mod2path.get(".".join(parts[:count]))
                if target is not None and target != path:
                    targets.add(target)
        edges[path] = frozenset(targets)
        for target in targets:
            rev_sets.setdefault(target, set()).add(path)

    logger.debug("graph built: %d files, %d tests", len(paths), len(tests))
    return ImportGraph(
        root=root_path,
        test_files=frozenset(tests),
        warnings=warnings.finish(),
        truncated=truncated,
        _files=files,
        _mod2path=mod2path,
        _rev={key: frozenset(value) for key, value in rev_sets.items()},
        _edges=edges,
        _raw_by_name={key: frozenset(value) for key, value in raw_sets.items()},
        _dynamic=frozenset(dynamic),
        _pkg_dirs=pkg_dirs,
        _roots=roots,
        _test_globs=globs,
    )


def _matches_any(path: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    base = posixpath.basename(path)
    return any(item.fullmatch(path) or item.fullmatch(base) for item in patterns)


def _select_for_python(
    graph: ImportGraph,
    path: str,
    selected: dict[str, set[str]],
    run_reasons: set[str],
) -> None:
    is_test = path in graph.test_files
    known = path in graph._files
    info_module, script_like = _module_info(path, graph._roots, graph._pkg_dirs)
    if known:
        module = graph._files[path]
        seeds = {path}
        has_importers = bool(graph._rev.get(path))
    else:
        module = info_module
        seeds = graph._seeds_by_name(module) if module else set()
        has_importers = bool(seeds)
    if is_test:
        selected.setdefault(path, set()).add(path)
    elif not known and graph._matches_test_glob(path):
        return
    elif module is None or (script_like and not has_importers):
        run_reasons.add(path)
        return
    for target in graph._closure(seeds):
        if target in graph.test_files:
            selected.setdefault(target, set()).add(path)


def affected_tests(
    graph: ImportGraph,
    changed: Iterable[str],
    *,
    always_run_all: Sequence[str] = DEFAULT_ALWAYS_RUN_ALL,
) -> AffectedResult:
    """Return the test files that the ``changed`` paths can affect.

    Paths are taken relative to the graph root (backslashes and absolute paths inside the
    root are accepted); paths outside the root are dropped with a warning. Deleted files
    are resolved by module name. A changed ``.py`` file that cannot be mapped to the
    project, a root ``conftest.py`` or a match of ``always_run_all`` selects everything.
    """
    warnings = _Warnings()
    changed_items: Iterable[str] = [changed] if isinstance(changed, str) else changed
    patterns = [always_run_all] if isinstance(always_run_all, str) else always_run_all
    run_res = [_glob_regex(item) for item in patterns]
    root = graph.root.as_posix()
    normalized: set[str] = set()
    run_reasons: set[str] = set()
    count = 0
    for raw in changed_items:
        count += 1
        if count > MAX_CHANGED_FILES:
            run_reasons.add("too-many-changed-files")
            break
        path = _normalize(raw, root)
        if path is None:
            warnings.add(f"ignored invalid or outside-root path: {clip(repr(raw))}")
            continue
        normalized.add(path)

    selected: dict[str, set[str]] = {}
    relevant = False
    for path in sorted(normalized):
        if posixpath.basename(path) == "conftest.py":
            relevant = True
            directory = posixpath.dirname(path)
            if not directory:
                run_reasons.add(path)
                continue
            for test in graph.test_files:
                if test.startswith(directory + "/"):
                    selected.setdefault(test, set()).add(path)
            continue
        if _matches_any(path, run_res):
            run_reasons.add(path)
            continue
        if not path.endswith(".py"):
            continue
        relevant = True
        _select_for_python(graph, path, selected, run_reasons)

    if graph.truncated and relevant:
        run_reasons.add("graph-truncated")
    all_warnings = (*graph.warnings, *warnings.finish())
    if run_reasons:
        return AffectedResult(
            tests=sorted(graph.test_files),
            run_all=True,
            reasons={"*": sorted(run_reasons)},
            warnings=all_warnings,
        )
    if relevant:
        for test in graph._dynamic:
            selected.setdefault(test, set()).add("dynamic-import")
    reasons = {test: sorted(selected[test]) for test in sorted(selected)}
    logger.debug("selected %d tests", len(reasons))
    return AffectedResult(
        tests=list(reasons),
        run_all=False,
        reasons=reasons,
        warnings=all_warnings,
    )
