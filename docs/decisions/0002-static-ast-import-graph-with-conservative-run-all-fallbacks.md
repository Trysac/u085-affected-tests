# Static AST import graph with conservative run-all fallbacks

Status: accepted (generated, pending human review)

## Context

Large test suites run in full on every pull request. pytest-testmon needs coverage data from a previous run. A stateless, dependency-free way to pick affected tests is needed, and it must never import or execute project code, because the inputs are untrusted repositories.

## Decision

Parse every Python file with ast.parse only, build a file-level import graph where every Import and ImportFrom node counts, resolve names to project modules (including package __init__ files and submodule-versus-name resolution), and compute the reverse closure with an iterative BFS. When a change cannot be mapped (root conftest, configuration files, unmapped Python files, truncated graph, too many changes) the result is run_all. Git is invoked through a fixed argument list after validating the base ref, without a shell and with a timeout.

## Consequences

Selection is stateless and safe to run on untrusted code, with zero runtime dependencies. It is conservative: dynamic imports, fixtures and non-Python data files are not analysed, so test files using import_module are always selected and unmappable changes run everything. The static graph can over-select (for example package __init__ re-exports) but should not under-select for ordinary imports. Limits on files, bytes, changes and warnings bound resource use.
