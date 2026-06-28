"""Context References — inject files, folders, git diffs, URLs into messages.

Enables @reference syntax: @file/path, @folder/path, @diff, @url
to pull external context into conversations.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ContextReferenceResolver:
    """Resolve @references in user messages to inject external context."""

    REFERENCE_PATTERNS = [
        (re.compile(r"@file\s+([^\s]+)"), "file"),
        (re.compile(r"@folder\s+([^\s]+)"), "folder"),
        (re.compile(r"@diff\s*(.*)", re.DOTALL), "diff"),
        (re.compile(r"@url\s+(https?://\S+)"), "url"),
        (re.compile(r"@git\s+diff", re.I), "git_diff"),
        (re.compile(r"@git\s+log\s*(.*)", re.I), "git_log"),
        (re.compile(r"@context\s+([^\s]+)"), "context_file"),
    ]

    def __init__(self, workspace_dir: str = ".") -> None:
        self._workspace = Path(workspace_dir)

    def extract_references(self, text: str) -> list[dict[str, Any]]:
        """Extract all @references from text."""
        references = []
        for pattern, ref_type in self.REFERENCE_PATTERNS:
            for match in pattern.finditer(text):
                ref = {
                    "type": ref_type,
                    "query": match.group(1).strip() if match.lastindex else "",
                    "start": match.start(),
                    "end": match.end(),
                    "full_match": match.group(0),
                }
                references.append(ref)
        return references

    def resolve_references(self, text: str) -> tuple[str, list[dict[str, Any]]]:
        """Resolve all references and inject content. Returns (modified_text, resolved_refs)."""
        references = self.extract_references(text)
        resolved = []
        result = text

        for ref in reversed(references):  # Process in reverse to preserve positions
            content = self._resolve_single(ref)
            if content:
                ref["content_preview"] = content[:500]
                ref["content_length"] = len(content)
                resolved.append(ref)
                # Replace the reference with expanded content
                injection = f"\n[{ref['type'].upper()}: {ref.get('query', '')}]\n{content}\n"
                result = result[: ref["start"]] + injection + result[ref["end"] :]

        return result, resolved

    def _resolve_single(self, ref: dict) -> str:
        """Resolve a single reference to its content."""
        ref_type = ref["type"]
        query = ref.get("query", "")

        if ref_type == "file":
            return self._resolve_file(query)
        elif ref_type == "folder":
            return self._resolve_folder(query)
        elif ref_type in ("diff", "git_diff"):
            return self._resolve_git_diff()
        elif ref_type == "url":
            return self._resolve_url(query)
        elif ref_type == "git_log":
            return self._resolve_git_log(query)
        elif ref_type == "context_file":
            return self._resolve_context_file(query)
        return ""

    def _resolve_file(self, path: str) -> str:
        target = Path(path) if os.path.isabs(path) else self._workspace / path
        if not target.exists():
            return f"[File not found: {path}]"
        if target.stat().st_size > 100_000:
            return target.read_text(encoding="utf-8", errors="replace")[:100_000]
        return target.read_text(encoding="utf-8", errors="replace")

    def _resolve_folder(self, path: str) -> str:
        target = Path(path) if os.path.isabs(path) else self._workspace / path
        if not target.exists() or not target.is_dir():
            return f"[Folder not found: {path}]"
        entries = []
        for entry in sorted(target.iterdir()):
            prefix = "d" if entry.is_dir() else "f"
            size = f" ({entry.stat().st_size}b)" if entry.is_file() else ""
            entries.append(f"  [{prefix}] {entry.name}{size}")
        return f"Folder: {path}\n" + "\n".join(entries[:200])

    def _resolve_git_diff(self) -> str:
        import subprocess

        try:
            result = subprocess.run(
                ["git", "diff", "HEAD~1", "--stat"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(self._workspace),
            )
            return result.stdout[:5000]
        except Exception:
            return "[Git diff not available]"

    def _resolve_url(self, url: str) -> str:
        import subprocess

        try:
            result = subprocess.run(
                ["curl", "-sL", "--max-time", "10", url],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.stdout[:10000]
        except Exception:
            return f"[Failed to fetch URL: {url}]"

    def _resolve_git_log(self, args: str) -> str:
        import subprocess

        count = args.strip() or "10"
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"-{count}"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(self._workspace),
            )
            return result.stdout[:3000]
        except Exception:
            return "[Git log not available]"

    def _resolve_context_file(self, name: str) -> str:
        candidates = [name, f"{name}.md", f".{name}", "AGENTS.md"]
        for candidate in candidates:
            target = self._workspace / candidate
            if target.exists():
                return target.read_text(encoding="utf-8", errors="replace")[:5000]
        return f"[Context file not found: {name}]"


# Singleton
_resolver: ContextReferenceResolver | None = None


def get_context_resolver() -> ContextReferenceResolver:
    global _resolver
    if _resolver is None:
        _resolver = ContextReferenceResolver()
    return _resolver
