"""Tests for the command line interface."""

from __future__ import annotations

import json
import runpy
import subprocess
from pathlib import Path
from typing import Any

import pytest

from affected_tests import __main__ as cli

NL = chr(10)
NUL = chr(0)
BS = chr(92)


def write(root: Path, rel: str, text: str = "") -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def tree(root: Path) -> None:
    write(root, "tests/test_b.py", "import pkg.b" + NL)
    write(root, "src/pkg/b.py", "from pkg import a" + NL)
    write(root, "src/pkg/a.py", "VALUE = 1" + NL)


def test_readme_only_prints_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--files", "README.md"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_json_format_has_exact_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--files", "README.md", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"run_all", "tests", "reasons", "warnings"}
    assert payload == {"run_all": False, "tests": [], "reasons": {}, "warnings": []}


def test_lines_format_prints_one_test_per_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tree(tmp_path)
    assert cli.main(["--root", str(tmp_path), "--files", "src/pkg/a.py"]) == 0
    assert capsys.readouterr().out == "tests/test_b.py" + NL


def test_backslash_paths_are_accepted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tree(tmp_path)
    path = "src" + BS + "pkg" + BS + "a.py"
    assert cli.main(["--root", str(tmp_path), "--files", path, "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tests"] == ["tests/test_b.py"]
    assert payload["reasons"] == {"tests/test_b.py": ["src/pkg/a.py"]}


def test_run_all_prints_single_tests_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tree(tmp_path)
    assert cli.main(["--root", str(tmp_path), "--files", "pyproject.toml"]) == 0
    assert capsys.readouterr().out == "tests" + NL


def test_warnings_go_to_stderr_in_lines_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tree(tmp_path)
    assert cli.main(["--root", str(tmp_path), "--files", "../x.py"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "warning:" in captured.err


def test_base_uses_git_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree(tmp_path)
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b"src/pkg/a.py" + NUL.encode(), b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert cli.main(["--root", str(tmp_path), "--base", "main"]) == 0
    assert capsys.readouterr().out == "tests/test_b.py" + NL
    assert calls[0][-2] == "main...HEAD"


def test_invalid_ref_and_git_failure_exit_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree(tmp_path)
    assert cli.main(["--root", str(tmp_path), "--base", "--output=x"]) == 2
    assert cli.main(["--root", str(tmp_path), "--base=--output=x"]) == 1
    assert "invalid_ref" in capsys.readouterr().err

    def failing(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 128, b"", b"fatal: bad revision")

    monkeypatch.setattr(subprocess, "run", failing)
    assert cli.main(["--root", str(tmp_path), "--base", "main"]) == 1
    assert "git_failed" in capsys.readouterr().err


def test_usage_and_io_errors_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main([]) == 2
    assert cli.main(["--files", "a.py", "--base", "main"]) == 2
    assert cli.main(["--files", "a.py", "--format", "xml"]) == 2
    assert cli.main(["--root", str(tmp_path / "nope"), "--files", "a.py"]) == 2
    assert "root_missing" in capsys.readouterr().err

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError

    monkeypatch.setattr(cli, "build_graph", broken)
    assert cli.main(["--root", str(tmp_path), "--files", "a.py"]) == 2


def test_help_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    assert "--base" in capsys.readouterr().out


def test_module_entry_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["affected-tests", "--files", "src/pkg/a.py"])
    with pytest.raises(SystemExit) as info:
        runpy.run_module("affected_tests.__main__", run_name="__main__")
    assert info.value.code == 0
    assert capsys.readouterr().out == "tests/test_b.py" + NL
