"""Behavior tests for the public API of affected_tests."""

from __future__ import annotations

import pytest

import affected_tests


def test_normalize_trims_and_lowercases() -> None:
    assert affected_tests.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        affected_tests.normalize(value)


def test_version_is_semver() -> None:
    parts = affected_tests.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
