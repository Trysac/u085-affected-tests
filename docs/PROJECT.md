# Project record

## Objective

Select the Python test files affected by changed files using a static ast import graph, with conservative run-all triggers. The tool answers which test files a change can affect, without importing or running project code, and falls back to running everything when it cannot be sure.

## Scope

- In scope: static import graph construction with `ast.parse`; reverse-closure selection of test files; conservative run-all triggers; reading committed changes from git with a validated base ref; a command line interface (`python -m affected_tests`) with `lines` and `json` output.
- In scope: the public API documented in [README.md](../README.md), typed and tested.
- Out of scope: coverage measurement; languages other than Python; fixture analysis; runtime dependencies or I/O beyond the documented directory walk and git call.

## Timeline

| Date | Event |
|---|---|
| 2026 | Repository created from the factory utility template. |

## Effort metrics

Measured values only; a value that has not been measured stays "pending measurement".

| Metric | Value |
|---|---|
| Tokens (input / output) | 391299 / 106343 |
| Hours (human) | pending measurement |
| Cost (USD) | 0.7731 |

## Factory run u085 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | claude-sonnet-5-5 | yes | 2455 | 88877 | 0 | 4246 | 0.4473 |
| fix-1 | claude-sonnet-5-5 | no | 4 | 363 | 5928 | 24814 | 0.0209 |
| fix-2 | claude-sonnet-5-5 | no | 8 | 1274 | 10472 | 63593 | 0.0453 |
| audit | claude-sonnet-5-5 | no | 12 | 3597 | 26116 | 122908 | 0.1136 |
| fix-3 | claude-sonnet-5-5 | no | 6 | 2614 | 10478 | 42589 | 0.0566 |
| docs | claude-haiku-5-5 | no | 130664 | 9618 | 0 | 0 | 0.0894 |

Total: $0.7731. Prices: Anthropic list prices.
