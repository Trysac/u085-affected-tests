"""Command line interface: ``python -m affected_tests``.

Exit codes: 0 success, 1 domain failure (invalid ref, git failure), 2 usage, I/O or missing root.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ._core import AffectedResult, affected_tests, build_graph
from ._errors import AffectedTestsError
from ._git import GitDiffSource

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="affected-tests",
        description="Select the Python test files affected by changed files.",
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=".", help="project root (default: current directory)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", metavar="REF", help="diff HEAD against the merge base with REF")
    group.add_argument("--files", nargs="+", metavar="PATH", help="changed paths, relative to root")
    parser.add_argument("--format", choices=("lines", "json"), default="lines")
    return parser


def _emit(result: AffectedResult, output_format: str) -> None:
    if output_format == "json":
        payload = {
            "run_all": result.run_all,
            "tests": result.tests,
            "reasons": result.reasons,
            "warnings": list(result.warnings),
        }
        print(json.dumps(payload))
        return
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if result.run_all:
        print("tests")
        return
    for test in result.tests:
        print(test)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    root = Path(args.root)
    try:
        if args.base is not None:
            changed = GitDiffSource(root, args.base).changed_files()
        else:
            changed = list(args.files)
        graph = build_graph(root)
        result = affected_tests(graph, changed)
    except AffectedTestsError as exc:
        print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return 2 if exc.code == "root_missing" else 1
    except OSError:
        print("error: input/output failure", file=sys.stderr)
        return 2
    _emit(result, args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
