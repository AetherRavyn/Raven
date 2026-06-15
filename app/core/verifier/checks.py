"""Built-in deterministic checks.

Each check is a function that takes whatever context it needs and
returns a :class:`CheckResult`.  Keep them pure — no I/O surprises,
no global state.  The verifier orchestrates them; this module only
implements the rules.

A check never raises.  Errors are captured as a failed result with
``message`` set to the exception text.  That keeps the verifier
running even when one rule explodes.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from app.core.verifier.types import (
    CheckKind,
    CheckResult,
    Severity,
)

logger = logging.getLogger(__name__)


def _measure(callable_: Callable[[], CheckResult]) -> CheckResult:
    start = time.perf_counter()
    try:
        result = callable_()
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            name="check",
            kind=CheckKind.CUSTOM,
            passed=False,
            severity=Severity.WARNING,
            message=f"check raised: {e}",
        )
    result.duration_ms = max(1, int((time.perf_counter() - start) * 1000))
    return result


# ---------------------------------------------------------------------------
# Text checks
# ---------------------------------------------------------------------------


def check_non_empty(value: Any, *, name: str = "non_empty") -> CheckResult:
    def _run() -> CheckResult:
        passed = value is not None and str(value).strip() != ""
        return CheckResult(
            name=name,
            kind=CheckKind.NON_EMPTY,
            passed=passed,
            message=("" if passed else "value is empty"),
            actual=value
            if isinstance(value, (str, int, float, bool, type(None)))
            else str(value),
        )

    return _measure(_run)


def check_substring(
    text: str,
    needle: str,
    *,
    case_sensitive: bool = True,
    name: str = "substring",
) -> CheckResult:
    def _run() -> CheckResult:
        if not isinstance(text, str):
            return CheckResult(
                name=name,
                kind=CheckKind.SUBSTRING,
                passed=False,
                message=f"text is {type(text).__name__}, not str",
            )
        haystack = text if case_sensitive else text.lower()
        target = needle if case_sensitive else needle.lower()
        passed = target in haystack
        return CheckResult(
            name=name,
            kind=CheckKind.SUBSTRING,
            passed=passed,
            message=("" if passed else f"{needle!r} not found in output"),
            actual=None,
            expected=needle,
        )

    return _measure(_run)


def check_regex(
    text: str,
    pattern: str,
    *,
    name: str | None = None,
    flags: int = 0,
) -> CheckResult:
    def _run() -> CheckResult:
        if not isinstance(text, str):
            return CheckResult(
                name=name or f"regex({pattern!r})",
                kind=CheckKind.REGEX,
                passed=False,
                message=f"text is {type(text).__name__}, not str",
            )
        try:
            m = re.search(pattern, text, flags)
        except re.error as e:
            return CheckResult(
                name=name or f"regex({pattern!r})",
                kind=CheckKind.REGEX,
                passed=False,
                message=f"invalid regex: {e}",
            )
        passed = m is not None
        return CheckResult(
            name=name or f"regex({pattern!r})",
            kind=CheckKind.REGEX,
            passed=passed,
            message=("" if passed else f"pattern {pattern!r} did not match"),
            expected=pattern,
            actual=m.group(0) if m else None,
        )

    return _measure(_run)


def check_json_valid(text: str, *, name: str = "json_valid") -> CheckResult:
    def _run() -> CheckResult:
        if not isinstance(text, str):
            return CheckResult(
                name=name,
                kind=CheckKind.JSON_VALID,
                passed=False,
                message=f"text is {type(text).__name__}, not str",
            )
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            return CheckResult(
                name=name,
                kind=CheckKind.JSON_VALID,
                passed=False,
                message=f"invalid JSON: {e.msg} at line {e.lineno} col {e.colno}",
            )
        return CheckResult(name=name, kind=CheckKind.JSON_VALID, passed=True)

    return _measure(_run)


def check_markdown_well_formed(
    text: str, *, name: str = "markdown_well_formed"
) -> CheckResult:
    """Heuristic: balanced code fences and no unclosed links."""

    def _run() -> CheckResult:
        if not isinstance(text, str):
            return CheckResult(
                name=name,
                kind=CheckKind.MARKDOWN_VALID,
                passed=False,
                message=f"text is {type(text).__name__}, not str",
            )
        fences = text.count("```")
        if fences % 2 != 0:
            return CheckResult(
                name=name,
                kind=CheckKind.MARKDOWN_VALID,
                passed=False,
                severity=Severity.WARNING,
                message="unbalanced code fences",
            )
        # Naive link check: every [ must have a matching ]
        if text.count("[") != text.count("]"):
            return CheckResult(
                name=name,
                kind=CheckKind.MARKDOWN_VALID,
                passed=False,
                severity=Severity.WARNING,
                message="unbalanced markdown links",
            )
        return CheckResult(name=name, kind=CheckKind.MARKDOWN_VALID, passed=True)

    return _measure(_run)


# ---------------------------------------------------------------------------
# Filesystem / shell checks
# ---------------------------------------------------------------------------


def check_file_exists(path: str, *, name: str | None = None) -> CheckResult:
    def _run() -> CheckResult:
        p = Path(path)
        passed = p.exists() and p.is_file()
        return CheckResult(
            name=name or f"file_exists({path})",
            kind=CheckKind.FILE_EXISTS,
            passed=passed,
            message=("" if passed else f"file does not exist: {path}"),
            actual=str(p),
            expected=path,
        )

    return _measure(_run)


def check_file_written(
    path: str, *, min_bytes: int = 1, name: str | None = None
) -> CheckResult:
    def _run() -> CheckResult:
        p = Path(path)
        if not p.exists():
            return CheckResult(
                name=name or f"file_written({path})",
                kind=CheckKind.FILE_WRITTEN,
                passed=False,
                message=f"file does not exist: {path}",
            )
        size = p.stat().st_size
        passed = size >= min_bytes
        return CheckResult(
            name=name or f"file_written({path})",
            kind=CheckKind.FILE_WRITTEN,
            passed=passed,
            message=(
                "" if passed else f"file is {size} bytes, expected >= {min_bytes}"
            ),
            actual=size,
            expected=min_bytes,
        )

    return _measure(_run)


def check_exit_code(
    code: int, expected: int = 0, *, name: str | None = None
) -> CheckResult:
    def _run() -> CheckResult:
        passed = code == expected
        return CheckResult(
            name=name or f"exit_code=={expected}",
            kind=CheckKind.EXIT_CODE,
            passed=passed,
            message=("" if passed else f"exit code {code}, expected {expected}"),
            actual=code,
            expected=expected,
        )

    return _measure(_run)


# ---------------------------------------------------------------------------
# URL check (offline — only structural, no fetch)
# ---------------------------------------------------------------------------


def check_url_well_formed(
    url: str, *, require_https: bool = False, name: str | None = None
) -> CheckResult:
    def _run() -> CheckResult:
        try:
            parsed = urlparse(url)
        except Exception as e:  # noqa: BLE001
            return CheckResult(
                name=name or f"url_well_formed({url})",
                kind=CheckKind.URL_REACHABLE,
                passed=False,
                message=f"URL parse failed: {e}",
            )
        if not parsed.scheme or not parsed.netloc:
            return CheckResult(
                name=name or f"url_well_formed({url})",
                kind=CheckKind.URL_REACHABLE,
                passed=False,
                message="missing scheme or host",
            )
        if require_https and parsed.scheme != "https":
            return CheckResult(
                name=name or f"url_well_formed({url})",
                kind=CheckKind.URL_REACHABLE,
                passed=False,
                severity=Severity.WARNING,
                message=f"scheme {parsed.scheme!r} is not https",
            )
        return CheckResult(
            name=name or f"url_well_formed({url})",
            kind=CheckKind.URL_REACHABLE,
            passed=True,
        )

    return _measure(_run)


# ---------------------------------------------------------------------------
# Structure check: required keys are present in a dict
# ---------------------------------------------------------------------------


def check_structure(
    value: Any,
    required_keys: list[str],
    *,
    name: str = "structure",
) -> CheckResult:
    def _run() -> CheckResult:
        if not isinstance(value, Mapping):
            return CheckResult(
                name=name,
                kind=CheckKind.STRUCTURE,
                passed=False,
                message=f"value is {type(value).__name__}, not a mapping",
            )
        missing = [k for k in required_keys if k not in value]
        passed = not missing
        return CheckResult(
            name=name,
            kind=CheckKind.STRUCTURE,
            passed=passed,
            message=("" if passed else f"missing keys: {missing}"),
            actual=sorted(value.keys()),
            expected=required_keys,
        )

    return _measure(_run)


__all__ = [
    "check_non_empty",
    "check_substring",
    "check_regex",
    "check_json_valid",
    "check_markdown_well_formed",
    "check_file_exists",
    "check_file_written",
    "check_exit_code",
    "check_url_well_formed",
    "check_structure",
]
