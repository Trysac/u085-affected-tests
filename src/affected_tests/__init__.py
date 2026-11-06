"""Select the Python test files affected by changed files.

``build_graph`` parses a project with :func:`ast.parse` and builds a static import graph;
``affected_tests`` walks it backwards from the changed files and returns the test files that can
be affected, falling back to "run everything" whenever it cannot be sure.

Safety: project code is only ever parsed with ``ast.parse``; it is never imported, compiled or
executed. Files larger than ``max_file_bytes`` are skipped with a warning, the number of files,
changed paths and warnings is capped, and ``RecursionError`` / ``MemoryError`` raised while
parsing a single file are caught and reported as warnings. ``GitDiffSource`` validates the base
ref, never uses a shell and runs git with a timeout.
"""

from __future__ import annotations

from ._core import AffectedResult, ImportGraph, affected_tests, build_graph
from ._errors import AffectedTestsError
from ._git import GitDiffSource

__all__ = [
    "AffectedResult",
    "AffectedTestsError",
    "GitDiffSource",
    "ImportGraph",
    "__version__",
    "affected_tests",
    "build_graph",
]

__version__ = "0.1.0"
