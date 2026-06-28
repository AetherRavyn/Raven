"""Tool utilities — shared helpers for graceful error handling."""

from __future__ import annotations

from typing import Any

__all__ = ["tool_error", "tool_success", "deps_error"]


def tool_error(
    msg: str,
    hint: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    """Return a consistent error dict from any tool.

    Args:
        msg: Human-readable error description.
        hint: Optional suggestion for fixing the issue.
        action: The tool action that failed (for context).
    """
    result: dict[str, Any] = {
        "success": False,
        "error": msg,
    }
    if hint:
        result["hint"] = hint
    if action:
        result["action"] = action
    return result


def tool_success(
    data: dict[str, Any] | None = None,
    action: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return a consistent success dict from any tool."""
    result: dict[str, Any] = {"success": True}
    if data:
        result.update(data)
    if action:
        result["action"] = action
    result.update(kwargs)
    return result


def deps_error(
    package: str,
    pip_install: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    """Convenience for missing-dependency errors."""
    hint = f"Install: pip install {pip_install or package}" if pip_install else None
    return tool_error(
        f"Missing dependency: {package}",
        hint=hint,
        action=action,
    )
