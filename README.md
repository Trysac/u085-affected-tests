# affected-tests

[![PyPI version](https://img.shields.io/pypi/v/trysac-affected-tests)](https://pypi.org/project/trysac-affected-tests/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-affected-tests)](LICENSE)
[![CI](https://github.com/Trysac/u085-affected-tests/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u085-affected-tests/actions/workflows/ci.yml)

Select the Python test files affected by changed files using a static ast import graph, with conservative run-all triggers

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-affected-tests
# or
uv add trysac-affected-tests
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import affected_tests

# normalize() trims surrounding whitespace and lower-cases the text.
print(affected_tests.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    affected_tests.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
