"""Skill Hub Tool — Browse, search, install, and publish skills.

Agents use this to discover skills from remote hubs, install them with
security scanning, and manage their skill library.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class SkillHubTool(BaseTool):
    """Discover, install, publish, and manage skills from hubs.

    Integrates with the SkillMarketplace for multi-source discovery
    and security-scanned installation.
    """

    group = "agent"

    def get_name(self) -> str:
        return "skill_hub"

    def get_description(self) -> str:
        return (
            "Discovers, installs, publishes, and manages skills. "
            "Actions: 'search' (find skills), 'list' (installed/bundled/community), "
            "'info' (skill details), 'hubs' (available remote sources), "
            "'browse' (remote hub skills), 'install' (download with security scan), "
            "'remove' (delete installed skill), 'publish' (share to community), "
            "'scan' (security check a skill directory)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation",
                    required=True,
                    enum=[
                        "search",
                        "list",
                        "info",
                        "hubs",
                        "browse",
                        "install",
                        "remove",
                        "publish",
                        "scan",
                    ],
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (for search, browse)",
                    required=False,
                ),
                ToolParameter(
                    name="skill_name",
                    type="string",
                    description="Skill name (for info, remove)",
                    required=False,
                ),
                ToolParameter(
                    name="source",
                    type="string",
                    description="Install source: GitHub URL, file path, or hub URL",
                    required=False,
                ),
                ToolParameter(
                    name="trust_level",
                    type="string",
                    description="Install trust level: 'trust' (skip scan), 'warn' (scan+warn), 'block' (scan+reject)",
                    required=False,
                    enum=["trust", "warn", "block"],
                ),
                ToolParameter(
                    name="hub_name",
                    type="string",
                    description="Hub name (for browse)",
                    required=False,
                ),
                ToolParameter(
                    name="skill_dir",
                    type="string",
                    description="Local skill directory path (for publish, scan)",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Skill description (for publish)",
                    required=False,
                ),
                ToolParameter(
                    name="tags",
                    type="string",
                    description="Comma-separated tags (for publish)",
                    required=False,
                ),
                ToolParameter(
                    name="include_remote",
                    type="boolean",
                    description="Include remote hubs in search results (default: false)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        try:
            from app.core.skill_marketplace import get_skill_marketplace

            mkt = get_skill_marketplace()

            if action == "search":
                return self._search(mkt, kwargs)
            elif action == "list":
                return self._list(mkt)
            elif action == "info":
                return self._info(mkt, kwargs)
            elif action == "hubs":
                return self._hubs(mkt)
            elif action == "browse":
                return self._browse(mkt, kwargs)
            elif action == "install":
                return await self._install(mkt, kwargs)
            elif action == "remove":
                return self._remove(mkt, kwargs)
            elif action == "publish":
                return self._publish(mkt, kwargs)
            elif action == "scan":
                return self._scan(kwargs)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("Skill hub action=%s failed", action)
            return {"success": False, "error": str(e)}

    def _search(self, mkt, kwargs: dict[str, Any]) -> dict[str, Any]:
        query = kwargs.get("query", "").strip()
        include_remote = kwargs.get("include_remote", False)
        if not query:
            return {"success": False, "error": "query is required"}
        results = mkt.search(query, include_remote=include_remote)
        return {
            "success": True,
            "query": query,
            "count": len(results),
            "results": [
                {
                    "name": r.get("name"),
                    "source": r.get("source", "unknown"),
                    "description": (r.get("description") or "")[:200],
                    "tags": r.get("tags", []),
                    "version": r.get("version", ""),
                }
                for r in results
            ],
        }

    def _list(self, mkt) -> dict[str, Any]:
        catalog = mkt.list_all()
        total = sum(len(v) for v in catalog.values())
        return {
            "success": True,
            "total_skills": total,
            "catalog": catalog,
        }

    def _info(self, mkt, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("skill_name", "").strip()
        if not name:
            return {"success": False, "error": "skill_name is required"}
        info = mkt.get_info(name)
        if info is None:
            return {"success": False, "error": f"Skill '{name}' not found"}
        return {"success": True, "skill": info}

    def _hubs(self, mkt) -> dict[str, Any]:
        hubs = mkt.list_hubs()
        return {
            "success": True,
            "hub_count": len(hubs),
            "hubs": hubs,
        }

    def _browse(self, mkt, kwargs: dict[str, Any]) -> dict[str, Any]:
        hub_name = kwargs.get("hub_name", "").strip()
        query = kwargs.get("query", "").strip()
        if not hub_name:
            return {
                "success": False,
                "error": "hub_name is required (use hubs action to see available hubs)",
            }
        results = mkt.browse_hub(hub_name, query=query)
        return {
            "success": True,
            "hub": hub_name,
            "count": len(results),
            "skills": results,
        }

    async def _install(self, mkt, kwargs: dict[str, Any]) -> dict[str, Any]:
        source = kwargs.get("source", "").strip()
        trust_level = kwargs.get("trust_level", "warn")
        if not source:
            return {"success": False, "error": "source is required (GitHub URL, file path, or URL)"}
        result = mkt.install(source, trust_level=trust_level)
        return result

    def _remove(self, mkt, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("skill_name", "").strip()
        if not name:
            return {"success": False, "error": "skill_name is required"}
        return mkt.remove(name)

    def _publish(self, mkt, kwargs: dict[str, Any]) -> dict[str, Any]:
        skill_dir = kwargs.get("skill_dir", "").strip()
        description = kwargs.get("description", "").strip()
        tags_str = kwargs.get("tags", "").strip()
        if not skill_dir:
            return {"success": False, "error": "skill_dir is required"}
        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else None
        return mkt.publish(skill_dir, description=description, tags=tags)

    def _scan(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        skill_dir = kwargs.get("skill_dir", "").strip()
        if not skill_dir:
            return {"success": False, "error": "skill_dir is required"}
        from app.core.skill_marketplace import SkillSecurityScanner
        from pathlib import Path

        path = Path(skill_dir).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"Directory not found: {path}"}
        scanner = SkillSecurityScanner()
        result = scanner.scan(path)
        return {
            "success": True,
            "scanned_path": str(path),
            **result,
        }
