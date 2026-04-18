# -*- coding: utf-8 -*-
"""XiaoHongShu — check whether mcporter + xiaohongshu MCP is available."""

import json
import platform
import shutil
import subprocess
from .base import Channel


def format_xhs_result(data):
    """Clean XHS API response, keeping only useful fields.

    Handles both single note objects and lists of notes (search results).
    Drastically reduces token usage by stripping structural redundancy (#134).
    """
    if isinstance(data, list):
        return [_clean_note(item) for item in data]
    if isinstance(data, dict):
        # Handle search_feeds wrapper: {"items": [...]} or {"data": {"items": [...]}}
        items = None
        if "items" in data:
            items = data["items"]
        elif "data" in data and isinstance(data.get("data"), dict):
            items = data["data"].get("items") or data["data"].get("notes")
        if items and isinstance(items, list):
            return [_clean_note(item) for item in items]
        # Single note
        return _clean_note(data)
    return data


def _clean_note(note):
    """Extract useful fields from a single XHS note/feed item."""
    if not isinstance(note, dict):
        return note

    # Some responses nest the note under "note_card" or "note"
    inner = note.get("note_card") or note.get("note") or note

    result = {}

    # Basic info
    for key in ("id", "note_id", "xsec_token", "title", "desc", "type", "time"):
        if key in inner:
            result[key] = inner[key]

    # Content (may be in desc or content)
    if "content" in inner and "desc" not in result:
        result["content"] = inner["content"]

    # Author
    user = inner.get("user") or inner.get("author")
    if isinstance(user, dict):
        result["user"] = {
            k: user[k] for k in ("nickname", "user_id", "nick_name") if k in user
        }

    # Engagement metrics
    interact = inner.get("interact_info") or inner.get("note_interact_info") or {}
    if isinstance(interact, dict):
        for key in ("liked_count", "collected_count", "comment_count", "share_count"):
            if key in interact:
                result[key] = interact[key]
    # Also check top-level (some API formats)
    for key in ("liked_count", "collected_count", "comment_count", "share_count"):
        if key in inner and key not in result:
            result[key] = inner[key]

    # Images — just URLs
    images = inner.get("image_list") or inner.get("images_list") or []
    if isinstance(images, list):
        urls = []
        for img in images:
            if isinstance(img, dict):
                url = img.get("url") or img.get("url_default") or img.get("original")
                if url:
                    urls.append(url)
            elif isinstance(img, str):
                urls.append(img)
        if urls:
            result["images"] = urls

    # Tags
    tags = inner.get("tag_list") or inner.get("tags") or []
    if isinstance(tags, list):
        tag_names = []
        for t in tags:
            if isinstance(t, dict) and "name" in t:
                tag_names.append(t["name"])
            elif isinstance(t, str):
                tag_names.append(t)
        if tag_names:
            result["tags"] = tag_names

    # Comments (if present, e.g. from get_feed_detail with comments)
    comments = inner.get("comments") or []
    if isinstance(comments, list) and comments:
        result["comments"] = [_clean_comment(c) for c in comments]

    return result


def _clean_comment(comment):
    """Extract useful fields from a comment."""
    if not isinstance(comment, dict):
        return comment
    result = {}
    if "content" in comment:
        result["content"] = comment["content"]
    user = comment.get("user_info") or comment.get("user")
    if isinstance(user, dict):
        result["user"] = user.get("nickname") or user.get("nick_name", "")
    for key in ("like_count", "sub_comment_count"):
        if key in comment:
            result[key] = comment[key]
    return result


def _is_arm64() -> bool:
    """Detect ARM64 architecture (e.g. Apple Silicon)."""
    machine = platform.machine().lower()
    return machine in ("arm64", "aarch64")


def _mcporter_status_ok(stdout: str) -> bool:
    """Return True if mcporter JSON output indicates status == 'ok'.

    Uses proper JSON parsing to handle Windows BOM, CRLF line endings, and
    whitespace variations.  Falls back to normalised string matching so the
    check still works if mcporter ever returns non-JSON text.
    """
    text = stdout.strip()
    # Strip UTF-8 BOM that Windows PowerShell sometimes prepends.
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return str(data.get("status", "")).lower() == "ok"
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: normalise whitespace and CRLF, then do string search.
    normalised = text.lower().replace("\r\n", "\n").replace("\r", "\n").replace(" ", "")
    return '"status":"ok"' in normalised


def _docker_run_hint() -> str:
    """Return the docker run command, with --platform flag for ARM64."""
    if _is_arm64():
        return (
            "  docker run -d --name xiaohongshu-mcp -p 18060:18060 "
            "--platform linux/amd64 xpzouying/xiaohongshu-mcp\n"
            "  # ARM64 also: build from source: "
            "https://github.com/xpzouying/xiaohongshu-mcp"
        )
    return (
        "  docker run -d --name xiaohongshu-mcp -p 18060:18060 "
        "xpzouying/xiaohongshu-mcp"
    )


class XiaoHongShuChannel(Channel):
    name = "xiaohongshu"
    description = "Xiaohongshu notes"
    backends = ["xiaohongshu-mcp"]
    tier = 2

    def can_handle(self, url: str) -> bool:
        from urllib.parse import urlparse

        d = urlparse(url).netloc.lower()
        return "xiaohongshu.com" in d or "xhslink.com" in d

    def check(self, config=None):
        mcporter = shutil.which("mcporter")
        if not mcporter:
            return "off", (
                "Requires mcporter + xiaohongshu-mcp. Install steps:\n"
                "  1. npm install -g mcporter\n"
                "  2. " + _docker_run_hint().strip() + "\n"
                "  3. mcporter config add xiaohongshu http://localhost:18060/mcp\n"
                "  See https://github.com/xpzouying/xiaohongshu-mcp"
            )
        is_windows = platform.system() == "Windows"
        config_timeout = 15 if is_windows else 5
        try:
            r = subprocess.run(
                [mcporter, "config", "get", "xiaohongshu", "--json"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=config_timeout,
            )
            if r.returncode != 0 or "xiaohongshu" not in r.stdout.lower():
                return "off", (
                    "mcporter is installed but the Xiaohongshu MCP is not configured. Run:\n"
                    + _docker_run_hint()
                    + "\n"
                    "  mcporter config add xiaohongshu http://localhost:18060/mcp"
                )
        except Exception:
            return "off", "mcporter connection error"

        # Use longer timeouts on Windows where mcporter may be slower to respond.
        list_timeout = 30 if is_windows else 10
        try:
            r = subprocess.run(
                [mcporter, "list", "xiaohongshu", "--json"],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=list_timeout,
            )
            if r.returncode == 0 and _mcporter_status_ok(r.stdout):
                return "ok", "MCP connected (read, search, post, comment, like)"
            return (
                "warn",
                "MCP is configured, but the connection is unstable; check the xiaohongshu-mcp service status",
            )
        except subprocess.TimeoutExpired:
            return (
                "warn",
                "MCP is configured, but the health check timed out; check the xiaohongshu-mcp service status",
            )
        except Exception:
            return (
                "warn",
                "MCP is configured, but the connection is unstable; check the xiaohongshu-mcp service status",
            )
