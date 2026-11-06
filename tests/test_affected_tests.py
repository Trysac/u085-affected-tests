"""Behaviour tests for the public API of affected_tests."""

from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from affected_tests import (
    AffectedTestsError,
    GitDiffSource,
    _core,
    _git,
    affected_tests,
    build_graph,
)

NL = chr(10)
NUL = chr(0)
BS = chr(92)
A = frozenset({"pkg.a"})
EMPTY: frozenset[str] = frozenset()


def code(*lines: str) -> str:
    return NL.join(lines) + NL


def write(root: Path, rel: str, *lines: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code(*lines) if lines else "", encoding="utf-8")


def basic_tree(root: Path) -> None:
    write(root, "tests/test_b.py", "import pkg.b")
    write(root, "src/pkg/b.py", "from pkg import a")
    write(root, "src/pkg/a.py", "VALUE = 1")


class Recorder:
    def __init__(self, stdout: object = b"", stderr: object = b"", returncode: int = 0) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, self.stderr)


def test_selects_test_through_transitive_import(tmp_path: Path) -> None:
    basic_tree(tmp_path)
    result = affected_tests(build_graph(tmp_path), ["src/pkg/a.py"])
    assert result.tests == ["tests/test_b.py"]
    assert result.run_all is False
    assert result.reasons == {"tests/test_b.py": ["src/pkg/a.py"]}
    assert result.warnings == ()


def test_relative_imports_and_init_reexports(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/__init__.py", "from .a import thing")
    write(tmp_path, "src/pkg/a.py", "thing = 1")
    write(tmp_path, "src/pkg/c.py", "from . import a")
    write(tmp_path, "tests/test_t.py", "from pkg import thing")
    graph = build_graph(tmp_path)
    assert graph.imports_of("pkg.c") == frozenset({"pkg", "pkg.a"})
    assert graph.imports_of("pkg") == A
    assert graph.importers_of("pkg.a") == frozenset({"pkg", "pkg.c", "tests.test_t"})
    assert graph.importers_of("pkg.a", transitive=False) == frozenset({"pkg", "pkg.c"})
    result = affected_tests(graph, ["src/pkg/a.py"])
    assert result.tests == ["tests/test_t.py"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('X = "import pkg.a"', EMPTY),
        ("# import pkg.a", EMPTY),
        ('"""import pkg.a"""', EMPTY),
        (code("def f():", "    import pkg.a"), A),
        (code("try:", "    import pkg.a", "except ImportError:", "    pass"), A),
        (code("from typing import TYPE_CHECKING", "if TYPE_CHECKING:", "    import pkg.a"), A),
        ("from pkg.a import *", A),
        ("from ... import z", EMPTY),
    ],
)
def test_adjacency_of_imports(tmp_path: Path, body: str, expected: frozenset[str]) -> None:
    write(tmp_path, "src/pkg/a.py", "VALUE = 1")
    write(tmp_path, "src/pkg/s.py", body)
    assert build_graph(tmp_path).imports_of("pkg.s") == expected


def test_similar_module_names_do_not_collide(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py", "VALUE = 1")
    write(tmp_path, "src/pkg/ab.py", "VALUE = 2")
    write(tmp_path, "tests/test_ab.py", "import pkg.ab")
    write(tmp_path, "tests/test_a_dot.py", "from pkg.a import VALUE")
    write(tmp_path, "tests/test_text.py", 'NAME = "pkg.a"')
    result = affected_tests(build_graph(tmp_path), ["src/pkg/a.py"])
    assert result.tests == ["tests/test_a_dot.py"]


def test_multiple_changes_accumulate_reasons(tmp_path: Path) -> None:
    basic_tree(tmp_path)
    result = affected_tests(build_graph(tmp_path), ["src/pkg/b.py", "src/pkg/a.py"])
    assert result.reasons == {"tests/test_b.py": ["src/pkg/a.py", "src/pkg/b.py"]}


def run_all_tree(root: Path) -> None:
    write(root, "tests/api/test_x.py", "import pkg.a")
    write(root, "tests/api/conftest.py")
    write(root, "tests/web/test_y.py", "VALUE = 1")
    write(root, "src/pkg/a.py", "VALUE = 1")
    write(root, "scripts/x.py", "print(1)")
    write(root, "pyproject.toml", "[project]")
    write(root, "conftest.py")


def test_changed_test_selects_itself(tmp_path: Path) -> None:
    run_all_tree(tmp_path)
    result = affected_tests(build_graph(tmp_path), ["tests/api/test_x.py"])
    assert result.tests == ["tests/api/test_x.py"]
    assert result.reasons == {"tests/api/test_x.py": ["tests/api/test_x.py"]}


def test_nested_conftest_selects_tests_below_it(tmp_path: Path) -> None:
    run_all_tree(tmp_path)
    result = affected_tests(build_graph(tmp_path), ["tests/api/conftest.py"])
    assert result.tests == ["tests/api/test_x.py"]
    assert result.run_all is False
    assert result.reasons == {"tests/api/test_x.py": ["tests/api/conftest.py"]}


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "conftest.py",
        "scripts/x.py",
        "scripts/gone.py",
        "requirements-dev.txt",
        "tox.ini",
    ],
)
def test_run_all_triggers(tmp_path: Path, path: str) -> None:
    run_all_tree(tmp_path)
    result = affected_tests(build_graph(tmp_path), [path])
    assert result.run_all is True
    assert result.reasons == {"*": [path]}
    assert result.tests == ["tests/api/test_x.py", "tests/web/test_y.py"]


def test_script_imported_by_a_test_is_mapped(tmp_path: Path) -> None:
    run_all_tree(tmp_path)
    write(tmp_path, "tests/test_s.py", "import scripts.x")
    result = affected_tests(build_graph(tmp_path), ["scripts/x.py"])
    assert result.run_all is False
    assert result.tests == ["tests/test_s.py"]


def test_non_python_files_are_ignored(tmp_path: Path) -> None:
    run_all_tree(tmp_path)
    result = affected_tests(build_graph(tmp_path), ["README.md", "docs/guide.rst"])
    assert result.tests == []
    assert result.run_all is False
    assert result.reasons == {}


def test_custom_always_run_all_patterns(tmp_path: Path) -> None:
    run_all_tree(tmp_path)
    graph = build_graph(tmp_path)
    assert affected_tests(graph, ["Makefile"], always_run_all=("Makefile",)).run_all is True
    assert affected_tests(graph, ["Makefile"]).run_all is False


def test_syntax_error_and_recursion_error_become_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, "src/pkg/a.py", "VALUE = 1")
    write(tmp_path, "src/pkg/bad.py", "def (:")
    write(tmp_path, "src/pkg/deep.py", "import pkg.a")
    write(tmp_path, "src/pkg/mem.py", "import pkg.a")
    real_parse = ast.parse

    def fake_parse(source: Any, filename: Any = "<unknown>", *args: Any, **kwargs: Any) -> Any:
        if str(filename).endswith("deep.py"):
            raise RecursionError
        if str(filename).endswith("mem.py"):
            raise MemoryError
        return real_parse(source, filename, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", fake_parse)
    graph = build_graph(tmp_path)
    joined = " ".join(graph.warnings)
    assert "src/pkg/bad.py" in joined
    assert "src/pkg/deep.py" in joined
    assert "src/pkg/mem.py" in joined
    assert graph.imports_of("pkg.bad") == EMPTY
    assert graph.imports_of("pkg.deep") == EMPTY
    assert graph.imports_of("pkg.mem") == EMPTY


def test_null_bytes_warn_and_add_no_edges(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py", "VALUE = 1")
    (tmp_path / "src/pkg/nul.py").write_bytes(b"import pkg.a" + NUL.encode())
    graph = build_graph(tmp_path)
    assert any("src/pkg/nul.py" in item for item in graph.warnings)
    assert graph.imports_of("pkg.nul") == EMPTY


def test_dynamic_import_tests_are_always_selected(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py", "VALUE = 1")
    write(tmp_path, "tests/test_dyn.py", "import importlib", 'importlib.import_module("pkg.a")')
    write(tmp_path, "tests/test_dyn2.py", '__import__("pkg.a")')
    write(tmp_path, "tests/test_plain.py", "VALUE = 1")
    write(tmp_path, "tests/test_text.py", 'TEXT = "importlib.import_module"')
    graph = build_graph(tmp_path)
    result = affected_tests(graph, ["src/pkg/a.py"])
    assert result.tests == ["tests/test_dyn.py", "tests/test_dyn2.py"]
    assert result.reasons["tests/test_dyn.py"] == ["dynamic-import"]
    assert affected_tests(graph, ["README.md"]).tests == []


def test_top_level_code_is_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    write(tmp_path, "src/pkg/boom.py", "from pathlib import Path", f"Path({str(marker)!r}).touch()")
    write(tmp_path, "tests/test_boom.py", "import pkg.boom")
    build_graph(tmp_path)
    assert not marker.exists()


def test_git_diff_source_rejects_option_like_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    with pytest.raises(AffectedTestsError) as info:
        GitDiffSource(tmp_path, "--output=x").changed_files()
    assert info.value.code == "invalid_ref"
    assert recorder.calls == []


@pytest.mark.parametrize(
    "ref",
    ["", "-x", "a..b", "a b", "a;b", "$(id)", "main" + NL, "x" * 201, "a@{1}"],
)
def test_git_diff_source_rejects_malformed_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    with pytest.raises(AffectedTestsError) as info:
        GitDiffSource(tmp_path, ref).changed_files()
    assert info.value.code == "invalid_ref"
    assert len(str(info.value)) < 260
    assert recorder.calls == []


def test_git_diff_source_runs_the_exact_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = Recorder(stdout=b"src/pkg/a.py" + NUL.encode() + b"README.md" + NUL.encode())
    monkeypatch.setattr(subprocess, "run", recorder)
    assert GitDiffSource(tmp_path, "main").changed_files() == ["src/pkg/a.py", "README.md"]
    assert len(recorder.calls) == 1
    command, kwargs = recorder.calls[0]
    assert command == [
        "git",
        "-c",
        "core.fsmonitor=false",
        "diff",
        "--name-only",
        "-z",
        "--no-renames",
        "--no-ext-diff",
        "main...HEAD",
        "--",
    ]
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["timeout"] == 30.0


@pytest.mark.parametrize("ref", ["origin/main", "HEAD~3", "v1.0^", "feature/x-1", "_a"])
def test_git_diff_source_accepts_valid_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref: str
) -> None:
    recorder = Recorder(stdout="a.py" + NUL)
    monkeypatch.setattr(subprocess, "run", recorder)
    assert GitDiffSource(tmp_path, ref, timeout=5).changed_files() == ["a.py"]
    assert recorder.calls[0][0][-2] == ref + "...HEAD"


def test_git_diff_source_handles_empty_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "run", Recorder(stdout=None))
    assert GitDiffSource(tmp_path, "main").changed_files() == []


def test_git_diff_source_reports_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", Recorder(stderr=b"fatal: " + b"x" * 500, returncode=128))
    with pytest.raises(AffectedTestsError) as info:
        GitDiffSource(tmp_path, "main").changed_files()
    assert info.value.code == "git_failed"
    assert "fatal" in str(info.value)
    assert len(str(info.value)) < 260


def test_git_diff_source_maps_exceptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(command: list[str], **kwargs: Any) -> Any:
        raise FileNotFoundError

    def slow(command: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(command, 1.0)

    for fake in (missing, slow):
        monkeypatch.setattr(subprocess, "run", fake)
        with pytest.raises(AffectedTestsError) as info:
            GitDiffSource(tmp_path, "main").changed_files()
        assert info.value.code == "git_failed"


def test_git_diff_source_limits_output_and_checks_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = Recorder(stdout=b"a" * 50)
    monkeypatch.setattr(subprocess, "run", recorder)
    monkeypatch.setattr(_git, "MAX_OUTPUT_CHARS", 10)
    with pytest.raises(AffectedTestsError) as info:
        GitDiffSource(tmp_path, "main").changed_files()
    assert info.value.code == "git_failed"
    calls_before = len(recorder.calls)
    with pytest.raises(AffectedTestsError) as missing:
        GitDiffSource(tmp_path / "nope", "main").changed_files()
    assert missing.value.code == "root_missing"
    assert len(recorder.calls) == calls_before
    with pytest.raises(ValueError):
        GitDiffSource(tmp_path, "main", timeout=0)


def test_deleted_module_is_resolved_by_name(tmp_path: Path) -> None:
    write(tmp_path, "tests/test_a.py", "from pkg import a")
    write(tmp_path, "tests/test_other.py", "import pkg.other")
    graph = build_graph(tmp_path)
    result = affected_tests(graph, ["src/pkg/a.py"])
    assert result.tests == ["tests/test_a.py"]
    assert result.run_all is False


def test_deleted_test_file_selects_nothing(tmp_path: Path) -> None:
    write(tmp_path, "tests/test_a.py", "VALUE = 1")
    result = affected_tests(build_graph(tmp_path), ["tests/test_gone.py"])
    assert result.tests == []
    assert result.run_all is False


def test_cycles_terminate(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py", "import pkg.b")
    write(tmp_path, "src/pkg/b.py", "import pkg.a")
    write(tmp_path, "tests/test_a.py", "import pkg.a")
    graph = build_graph(tmp_path)
    assert graph.importers_of("pkg.a") == frozenset({"pkg.b", "tests.test_a"})
    assert affected_tests(graph, ["src/pkg/b.py"]).tests == ["tests/test_a.py"]


def test_flat_layout(tmp_path: Path) -> None:
    write(tmp_path, "mod.py", "VALUE = 1")
    write(tmp_path, "helper.py", "VALUE = 2")
    write(tmp_path, "pkg/__init__.py")
    write(tmp_path, "pkg/m.py", "import mod", "from . import sibling")
    write(tmp_path, "pkg/sibling.py", "VALUE = 3")
    write(tmp_path, "top.py", "from . import helper")
    write(tmp_path, "tests/test_m.py", "import pkg.m")
    graph = build_graph(tmp_path)
    assert graph.module_for("pkg/m.py") == "pkg.m"
    assert graph.imports_of("top") == frozenset({"helper"})
    assert affected_tests(graph, ["mod.py"]).tests == ["tests/test_m.py"]
    assert affected_tests(graph, ["pkg/sibling.py"]).tests == ["tests/test_m.py"]
    assert affected_tests(graph, ["pkg/m.py"]).run_all is False


def test_module_for(tmp_path: Path) -> None:
    basic_tree(tmp_path)
    write(tmp_path, "src/pkg/__init__.py")
    graph = build_graph(tmp_path)
    assert graph.module_for("src/pkg/a.py") == "pkg.a"
    assert graph.module_for("src" + BS + "pkg" + BS + "a.py") == "pkg.a"
    assert graph.module_for("src/pkg/__init__.py") == "pkg"
    assert graph.module_for("src/pkg/new.py") == "pkg.new"
    assert graph.module_for("src/__init__.py") is None
    assert graph.module_for("src/pkg-x/a.py") is None
    assert graph.module_for("README.md") is None
    assert graph.module_for("../x.py") is None
    assert graph.imports_of("unknown") == EMPTY
    assert graph.importers_of("unknown") == EMPTY


def test_custom_source_roots_and_unmapped_python(tmp_path: Path) -> None:
    write(tmp_path, "lib/pkg/a.py", "VALUE = 1")
    write(tmp_path, "tests/test_t.py", "import pkg.a")
    write(tmp_path, "scripts/x.py", "print(1)")
    graph = build_graph(tmp_path, source_roots=("lib",))
    assert graph.module_for("scripts/x.py") is None
    assert affected_tests(graph, ["lib/pkg/a.py"]).tests == ["tests/test_t.py"]
    result = affected_tests(graph, ["scripts/x.py"])
    assert result.run_all is True
    assert result.reasons == {"*": ["scripts/x.py"]}


def test_invalid_arguments(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build_graph(tmp_path, source_roots=("../x",))
    with pytest.raises(ValueError):
        build_graph(tmp_path, source_roots=("/abs",))
    with pytest.raises(ValueError):
        build_graph(tmp_path, max_files=0)
    with pytest.raises(ValueError):
        build_graph(tmp_path, test_globs=("a" * 300,))
    assert build_graph(tmp_path, source_roots="src", test_globs="t/*.py").test_files == frozenset()


def test_root_missing(tmp_path: Path) -> None:
    with pytest.raises(AffectedTestsError) as info:
        build_graph(tmp_path / "nope")
    assert info.value.code == "root_missing"
    write(tmp_path, "file.txt", "x")
    with pytest.raises(AffectedTestsError):
        build_graph(tmp_path / "file.txt")


def test_changed_paths_are_normalised_and_validated(tmp_path: Path) -> None:
    basic_tree(tmp_path)
    graph = build_graph(tmp_path)
    inside = (graph.root / "src" / "pkg" / "a.py").as_posix()
    changed = [
        "src" + BS + "pkg" + BS + "a.py",
        "./src/pkg/a.py",
        inside,
        "../evil.py",
        "/etc/passwd",
        "C:/x.py",
        "a" + NUL + "b.py",
        "",
        "x" * 5000,
    ]
    result = affected_tests(graph, changed)
    assert result.tests == ["tests/test_b.py"]
    assert result.reasons == {"tests/test_b.py": ["src/pkg/a.py"]}
    assert len(result.warnings) == 6
    assert all(len(item) < 260 for item in result.warnings)
    odd = affected_tests(graph, [123])  # type: ignore[list-item]
    assert len(odd.warnings) == 1


def test_accepts_single_string_and_generators(tmp_path: Path) -> None:
    basic_tree(tmp_path)
    graph = build_graph(tmp_path)
    assert affected_tests(graph, "src/pkg/a.py").tests == ["tests/test_b.py"]
    assert affected_tests(graph, (item for item in ["src/pkg/a.py"])).tests == ["tests/test_b.py"]
    assert affected_tests(graph, []).tests == []
    assert affected_tests(graph, [], always_run_all="setup.py").run_all is False


def test_too_many_changed_files_runs_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    basic_tree(tmp_path)
    monkeypatch.setattr(_core, "MAX_CHANGED_FILES", 2)
    result = affected_tests(build_graph(tmp_path), ["a.txt", "b.txt", "c.txt"])
    assert result.run_all is True
    assert result.reasons == {"*": ["too-many-changed-files"]}


def test_file_limit_marks_graph_truncated(tmp_path: Path) -> None:
    for name in ("a.py", "b.py", "c.py"):
        write(tmp_path, name, "VALUE = 1")
    graph = build_graph(tmp_path, max_files=2)
    assert graph.truncated is True
    assert any("file limit" in item for item in graph.warnings)
    result = affected_tests(graph, ["a.py"])
    assert result.run_all is True
    assert result.reasons == {"*": ["graph-truncated"]}
    assert affected_tests(graph, ["README.md"]).run_all is False


def test_large_files_are_skipped(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py", "VALUE = 1")
    write(tmp_path, "src/pkg/big.py", "import pkg.a", "X = '" + "a" * 100 + "'")
    graph = build_graph(tmp_path, max_file_bytes=40)
    assert any("src/pkg/big.py" in item and "larger" in item for item in graph.warnings)
    assert graph.imports_of("pkg.big") == EMPTY


def test_warnings_are_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for index in range(5):
        write(tmp_path, f"src/pkg/bad{index}.py", "def (:")
    monkeypatch.setattr(_core, "MAX_WARNINGS", 3)
    graph = build_graph(tmp_path)
    assert len(graph.warnings) == 4
    assert graph.warnings[-1] == "and 2 more"


def test_hidden_and_vendored_directories_are_skipped(tmp_path: Path) -> None:
    write(tmp_path, ".venv/tests/test_x.py", "VALUE = 1")
    write(tmp_path, "node_modules/pkg/test_y.py", "VALUE = 1")
    write(tmp_path, "tests/test_ok.py", "VALUE = 1")
    assert build_graph(tmp_path).test_files == frozenset({"tests/test_ok.py"})


def test_symbolic_links_are_skipped(tmp_path: Path) -> None:
    write(tmp_path, "tests/test_real.py", "VALUE = 1")
    try:
        os.symlink(tmp_path / "tests/test_real.py", tmp_path / "tests/test_link.py")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available")
    graph = build_graph(tmp_path)
    assert graph.test_files == frozenset({"tests/test_real.py"})
    assert any("symbolic link" in item for item in graph.warnings)


def test_duplicate_modules_warn(tmp_path: Path) -> None:
    write(tmp_path, "src/pkg/a.py", "VALUE = 1")
    write(tmp_path, "pkg/a.py", "VALUE = 2")
    graph = build_graph(tmp_path)
    assert any("duplicate module" in item for item in graph.warnings)


def test_results_are_immutable(tmp_path: Path) -> None:
    basic_tree(tmp_path)
    result = affected_tests(build_graph(tmp_path), ["README.md"])
    with pytest.raises(FrozenInstanceError):
        result.run_all = True  # type: ignore[misc]
