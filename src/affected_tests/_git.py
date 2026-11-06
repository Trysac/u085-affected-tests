"""Read the files changed since a merge base from ``git diff`` without a shell."""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from ._errors import AffectedTestsError, clip

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

MAX_OUTPUT_CHARS = 8_000_000
_REF_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._/~^-]{0,199}$")
_NUL = chr(0)


def _to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


class GitDiffSource:
    """List files changed on ``HEAD`` since its merge base with ``base``.

    Only committed changes are seen (``base...HEAD``). Paths are relative to the top level of
    the git repository; when ``root`` is a subdirectory they are re-based onto ``root`` (files
    outside it are dropped). The base ref is validated before git is started, so it can never be
    interpreted as an option, and git runs without a shell and with a timeout.
    """

    def __init__(self, root: Path | str, base: str, *, timeout: float = 30.0) -> None:
        if not timeout > 0:
            raise ValueError("timeout must be positive")
        self.root = Path(root)
        self.base = base
        self.timeout = timeout

    def changed_files(self) -> list[str]:
        """Return the changed paths.

        Raises:
            AffectedTestsError: ``invalid_ref`` for a malformed base, ``root_missing`` when the
                root is not a directory, ``git_failed`` when git fails, times out or is missing.
        """
        base = self.base
        if not isinstance(base, str) or _REF_PATTERN.fullmatch(base) is None or ".." in base:
            raise AffectedTestsError("invalid_ref", f"invalid base ref: {clip(repr(base))}")
        if not self.root.is_dir():
            raise AffectedTestsError("root_missing", "repository root is not a directory")
        command = [
            "git",
            "-c",
            "core.fsmonitor=false",
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "--no-ext-diff",
            f"{base}...HEAD",
            "--",
        ]
        try:
            proc = subprocess.run(
                command,
                cwd=str(self.root),
                capture_output=True,
                shell=False,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AffectedTestsError("git_failed", "git diff timed out") from exc
        except OSError as exc:
            raise AffectedTestsError("git_failed", "git could not be executed") from exc
        if proc.returncode != 0:
            detail = _to_text(proc.stderr).strip()[:200]
            message = f"git diff failed with exit code {proc.returncode}: {detail}"
            raise AffectedTestsError("git_failed", message)
        output = _to_text(proc.stdout)
        if len(output) > MAX_OUTPUT_CHARS:
            raise AffectedTestsError("git_failed", "git diff output is too large")
        logger.debug("git diff reported %d bytes of output", len(output))
        entries = [entry for entry in output.split(_NUL) if entry]
        prefix = self._root_prefix()
        if not prefix:
            return entries
        return [entry[len(prefix) :] for entry in entries if entry.startswith(prefix)]

    def _root_prefix(self) -> str:
        """Return ``root`` relative to the repo top level as ``"sub/dir/"``, or ``""``.

        git prints paths relative to the top level. The top level is found by looking for a
        ``.git`` entry upwards (no extra git call, so the argv stays fixed).
        """
        try:
            root = self.root.resolve()
            for parent in (root, *root.parents):
                if (parent / ".git").exists():
                    rel = root.relative_to(parent).as_posix()
                    return "" if rel == "." else rel + "/"
        except OSError:
            return ""
        return ""
