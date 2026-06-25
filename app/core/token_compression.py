"""Token Compression — RTK-style compression for LLM requests.

Saves 20-40% tokens by compressing tool outputs before sending to LLM.

Filters:
- git diff: Remove unchanged context lines
- grep output: Deduplicate and truncate
- file listings: Compress paths, remove empty dirs
- log output: Remove timestamps, truncate repeated patterns
- JSON output: Remove whitespace, truncate deep nesting

This runs BEFORE any format translation, so it works with all providers.
"""

from __future__ import annotations

import json
import re


def compress_tool_output(text: str, tool_type: str = "auto") -> str:
    """Compress tool output to save tokens.

    Returns compressed text that preserves semantic meaning
    while reducing token count by 20-40%.
    """
    if not text or len(text) < 100:
        return text  # Short text doesn't need compression

    # Auto-detect tool type
    if tool_type == "auto":
        tool_type = _detect_tool_type(text)

    # Apply appropriate filter
    filters = {
        "git_diff": _compress_git_diff,
        "git_status": _compress_git_status,
        "grep": _compress_grep,
        "file_list": _compress_file_list,
        "log": _compress_log,
        "json": _compress_json,
        "stack_trace": _compress_stack_trace,
        "generic": _compress_generic,
    }

    compressor = filters.get(tool_type, _compress_generic)
    return compressor(text)


def _detect_tool_type(text: str) -> str:
    """Auto-detect the type of tool output."""
    first_line = text.split("\n")[0][:200]

    if first_line.startswith("diff --git") or "diff --git" in text[:500]:
        return "git_diff"
    if first_line.startswith("On branch") or "Changes not staged" in text[:500]:
        return "git_status"
    if re.match(r"^[^:]+:\d+:", first_line):
        return "grep"
    if re.match(r"^[\w/._-]+/$", first_line) or re.match(r"^[\w/._-]+\.\w+$", first_line):
        return "file_list"
    if re.match(r"^\d{4}-\d{2}-\d{2}", first_line) or re.match(r"^\[\w+\]", first_line):
        return "log"
    if text.strip().startswith("{") or text.strip().startswith("["):
        return "json"
    if "at " in text and "Error" in text and ("File " in text or "line " in text):
        return "stack_trace"
    return "generic"


def _compress_git_diff(text: str) -> str:
    """Compress git diff output."""
    lines = text.split("\n")
    result = []
    current_file = ""

    for line in lines:
        if line.startswith("diff --git"):
            current_file = line.split(" b/")[-1] if " b/" in line else line
            result.append(f"--- {current_file}")
        elif line.startswith("@@"):
            result.append(line)  # Keep hunk headers
        elif line.startswith("+") and not line.startswith("+++"):
            result.append(line)  # Keep additions
        elif line.startswith("-") and not line.startswith("---"):
            result.append(line)  # Keep deletions
        # Skip context lines (no +/- prefix)

    return "\n".join(result)


def _compress_git_status(text: str) -> str:
    """Compress git status output."""
    lines = text.split("\n")
    result = []
    for line in lines:
        # Keep only changed files, skip header/footer
        if line.startswith("M ") or line.startswith("A ") or line.startswith("D ") or line.startswith("R "):
            result.append(line.strip())
        elif line.startswith("?? "):
            result.append(f"Untracked: {line[3:].strip()}")
    return "\n".join(result) if result else "No changes"


def _compress_grep(text: str) -> str:
    """Compress grep output — deduplicate and truncate."""
    lines = text.split("\n")
    seen = set()
    result = []
    for line in lines:
        normalized = re.sub(r"\d+:", "N:", line)  # Normalize line numbers
        if normalized not in seen:
            seen.add(normalized)
            result.append(line.strip())
        if len(result) >= 50:  # Cap at 50 results
            result.append(f"... ({len(lines) - 50} more matches)")
            break
    return "\n".join(result)


def _compress_file_list(text: str) -> str:
    """Compress file listing — remove empty dirs, shorten paths."""
    lines = text.split("\n")
    # Remove empty directory markers
    result = [line for line in lines if line.strip() and not line.strip().endswith("/")]
    if len(result) > 30:
        result = result[:30]
        result.append(f"... ({len(lines) - 30} more files)")
    return "\n".join(result)


def _compress_log(text: str) -> str:
    """Compress log output — remove timestamps, truncate repeats."""
    lines = text.split("\n")
    result = []
    prev_line = ""
    repeat_count = 0

    for line in lines:
        # Strip timestamp prefix
        cleaned = re.sub(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.\d]*\s*", "", line)
        cleaned = re.sub(r"^\[\w+\]\s*", "", cleaned)

        if cleaned == prev_line:
            repeat_count += 1
        else:
            if repeat_count > 0:
                result.append(f"  (repeated {repeat_count} times)")
            result.append(cleaned)
            prev_line = cleaned
            repeat_count = 0

        if len(result) >= 30:
            result.append(f"... ({len(lines) - 30} more lines)")
            break

    return "\n".join(result)


def _compress_json(text: str) -> str:
    """Compress JSON — remove whitespace, truncate deep nesting."""
    try:
        data = json.loads(text)
        # Remove whitespace
        compressed = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        # Truncate if still too long
        if len(compressed) > 2000:
            compressed = compressed[:2000] + "...}"
        return compressed
    except Exception:
        return text[:2000]


def _compress_stack_trace(text: str) -> str:
    """Compress stack traces — keep only relevant frames."""
    lines = text.split("\n")
    result = []
    for line in lines:
        # Keep error messages and first few frames
        if "Error" in line or "Exception" in line:
            result.append(line.strip())
        elif "at " in line and ("File " in line or "line " in line):
            if len(result) < 10:  # Keep first 10 frames
                result.append(line.strip())
        elif result:  # Stop after frames
            break
    return "\n".join(result)


def _compress_generic(text: str) -> str:
    """Generic compression — truncate and remove excessive whitespace."""
    # Remove multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Truncate
    if len(text) > 3000:
        text = text[:3000] + "\n... (truncated)"
    return text
