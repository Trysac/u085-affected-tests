"""Typed errors for the affected-tests library."""

from __future__ import annotations

from typing import Literal

ErrorCode = Literal["invalid_ref", "git_failed", "root_missing"]

MAX_MESSAGE_INPUT = 200


def clip(text: str, limit: int = MAX_MESSAGE_INPUT) -> str:
    """Return ``text`` cut to at most ``limit`` characters."""
    return text[:limit]


class AffectedTestsError(Exception):
    """Base error of the library; ``code`` is a stable machine-readable identifier."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
