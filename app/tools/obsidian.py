from __future__ import annotations

import base64
import json
import os
import platform
from mimetypes import guess_type
from pathlib import Path
from typing import Any, Dict

from app.media.image.xai import understand_image
from app.provider.xai import XAIGrpcClient
from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema


def get_obsidian_config_path() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"
    elif system == "Darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "obsidian"
            / "obsidian.json"
        )
    else:
        return Path.home() / ".config" / "obsidian" / "obsidian.json"


def get_active_vault_path() -> Path | None:
    config_path = get_obsidian_config_path()
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        vaults = data.get("vaults", {})

        # 1. Explicitly open vault
        for info in vaults.values():
            if info.get("open") is True:
                p = Path(info.get("path", ""))
                if p.exists():
                    return p.resolve()

        # 2. Most recent
        if vaults:
            latest = max(vaults.values(), key=lambda x: x.get("ts", 0))
            p = Path(latest.get("path", ""))
            if p.exists():
                return p.resolve()
    except Exception:
        pass
    return None


class ObsidianOperationTool(BaseTool):
    """Single unified Obsidian tool — exactly matches your GitOperationTool style."""

    def __init__(
        self,
        client: XAIGrpcClient | None = None,
        default_model: str | None = None,
    ) -> None:
        self._client = client or XAIGrpcClient()
        self._default_model = default_model or Config.XAI_VISION_MODEL
        self.MAX_OUTPUT_LENGTH = 8000

    def get_name(self) -> str:
        return "obsidian_ops"

    def get_description(self) -> str:
        return (
            "Complete Obsidian vault management: discover vault, read/write/search notes, "
            "and understand images stored in your vault (Attachments or anywhere)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The Obsidian operation to perform.",
                    required=True,
                    enum=[
                        "get_vault",
                        "read_note",
                        "search_content",
                        "write_note",
                        "image_understand",
                    ],
                ),
                # Common optional parameters
                ToolParameter(
                    name="vault_path",
                    type="string",
                    description="Optional absolute vault path (auto-detects active vault otherwise)",
                    required=False,
                ),
                # read_note / write_note / image_understand
                ToolParameter(
                    name="note_path",
                    type="string",
                    description="Relative path inside vault (e.g. 'Daily/2026-02-26.md' or 'Attachments/photo.jpg')",
                    required=False,
                ),
                # write_note
                ToolParameter(
                    name="content",
                    type="string",
                    description="Markdown content to write/append",
                    required=False,
                ),
                ToolParameter(
                    name="mode",
                    type="string",
                    description="write_note mode: append (default), overwrite, create",
                    required=False,
                    enum=["append", "overwrite", "create"],
                    default="append",
                ),
                # search_content
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search phrase for search_content",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max results for search_content",
                    required=False,
                    default=10,
                ),
                # image_understand
                ToolParameter(
                    name="image_path",
                    type="string",
                    description="Relative path to image inside vault",
                    required=False,
                ),
                ToolParameter(
                    name="prompt",
                    type="string",
                    description="What to analyze in the image",
                    required=False,
                ),
                ToolParameter(
                    name="model",
                    type="string",
                    description="Optional xAI vision model override",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation")
        vault_path_str = str(kwargs.get("vault_path", "")).strip()
        vault = (
            Path(vault_path_str).resolve()
            if vault_path_str
            else get_active_vault_path()
        )

        if not vault or not vault.exists():
            if op == "get_vault":
                pass  # get_vault still returns config info
            else:
                return {
                    "success": False,
                    "error": "Vault not found. Call get_vault first.",
                }

        # ─────────────────────────────────────────────────────────────
        if op == "get_vault":
            config_path = get_obsidian_config_path()
            result: Dict[str, Any] = {
                "success": True,
                "active_vault": str(vault) if vault else None,
                "config_path": str(config_path),
                "config_exists": config_path.exists(),
            }
            try:
                if config_path.exists():
                    data = json.loads(config_path.read_text(encoding="utf-8"))
                    result["known_vaults"] = {
                        vid: {
                            "path": info.get("path"),
                            "open": info.get("open", False),
                            "ts": info.get("ts"),
                        }
                        for vid, info in data.get("vaults", {}).items()
                    }
            except Exception as e:
                result["parse_error"] = str(e)
            return result

        # ─────────────────────────────────────────────────────────────
        elif op == "read_note":
            note_path = str(kwargs.get("note_path", "")).strip()
            if not note_path:
                return self._error("note_path required")
            if not note_path.endswith(".md"):
                note_path += ".md"
            full_path = (vault / note_path).resolve()
            if not str(full_path).startswith(str(vault)):
                return self._error("Path traversal blocked")
            if not full_path.is_file():
                return self._error(f"Note not found: {note_path}")
            content = full_path.read_text(encoding="utf-8")
            return {
                "success": True,
                "vault": str(vault),
                "note_path": str(full_path.relative_to(vault)),
                "content": content,
            }

        # ─────────────────────────────────────────────────────────────
        elif op == "search_content":
            query = str(kwargs.get("query", "")).strip().lower()
            limit = int(kwargs.get("limit", 10))
            if not query:
                return self._error("query required")
            results = []
            for file_path in vault.rglob("*.md"):
                try:
                    text = file_path.read_text(encoding="utf-8").lower()
                    if query in text:
                        rel = str(file_path.relative_to(vault))
                        idx = text.find(query)
                        snippet = (
                            text[max(0, idx - 80) : idx + 200]
                            .replace("\n", " ")
                            .strip()
                        )
                        results.append({"path": rel, "snippet": f"...{snippet}..."})
                        if len(results) >= limit:
                            break
                except Exception:
                    continue
            return {
                "success": True,
                "query": query,
                "results": results[:limit],
                "count": len(results),
            }

        # ─────────────────────────────────────────────────────────────
        elif op == "write_note":
            note_path = str(kwargs.get("note_path", "")).strip()
            content = str(kwargs.get("content", ""))
            mode = str(kwargs.get("mode", "append")).lower()
            if not note_path or not content:
                return self._error("note_path and content required")
            if not note_path.endswith(".md"):
                note_path += ".md"
            full_path = (vault / note_path).resolve()
            if not str(full_path).startswith(str(vault)):
                return self._error("Path outside vault blocked")
            full_path.parent.mkdir(parents=True, exist_ok=True)

            if mode == "create" and full_path.exists():
                return self._error("Note already exists")
            if mode == "append" and full_path.exists():
                existing = full_path.read_text(encoding="utf-8").rstrip()
                new_content = existing + "\n\n" + content
            else:
                new_content = content

            full_path.write_text(new_content, encoding="utf-8")
            return {
                "success": True,
                "vault": str(vault),
                "note_path": str(full_path.relative_to(vault)),
                "mode": mode,
            }

        # ─────────────────────────────────────────────────────────────
        elif op == "image_understand":
            image_path_str = str(kwargs.get("image_path", "")).strip()
            prompt = (
                str(kwargs.get("prompt", "")).strip()
                or "Describe this image from my Obsidian vault."
            )
            model = str(kwargs.get("model", "")).strip() or self._default_model
            if not image_path_str:
                return self._error("image_path required")

            if os.path.isabs(image_path_str):
                full_image_path = Path(image_path_str).resolve()
            else:
                full_image_path = (vault / image_path_str).resolve()

            if not str(full_image_path).startswith(str(vault)):
                return self._error("Image must be inside the vault")
            if not full_image_path.is_file():
                return self._error(f"Image not found: {image_path_str}")

            mime_type, _ = guess_type(full_image_path)
            if not mime_type or not mime_type.startswith("image/"):
                mime_type = "image/jpeg"

            image_bytes = full_image_path.read_bytes()
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            data_url = f"data:{mime_type};base64,{b64}"

            return understand_image(
                image_url=data_url,
                prompt=prompt,
                model=model,
                image_detail="auto",
                client=self._client,
            )

        else:
            return self._error(f"Unknown operation: {op}")

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "error": msg, "output": f"Error: {msg}"}
