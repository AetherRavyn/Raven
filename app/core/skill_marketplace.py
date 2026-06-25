"""Skill Marketplace — discover, install, publish, and share skills.

Provides a SkillMarketplace class that manages:
- Local skill catalog (bundled + installed)
- Remote skill discovery (GitHub repos)
- Skill versioning and updates
- Skill publishing (package + export)
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillMarketplace:
    """Manages the skill ecosystem: discover, install, publish, update."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._workspace = workspace_dir or Config.MEMORY_ROOT
        self._skills_dir = Path(self._workspace) / "skills"
        self._community_dir = self._skills_dir / "community"
        self._installed_dir = self._skills_dir / "installed"
        self._catalog_file = self._skills_dir / "catalog.json"
        self._community_dir.mkdir(parents=True, exist_ok=True)
        self._installed_dir.mkdir(parents=True, exist_ok=True)

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search for skills by name, description, or tags."""
        results = []
        query_lower = query.lower()

        # Search bundled skills
        bundled_dir = Path("skills/bundled")
        if bundled_dir.exists():
            for skill_dir in bundled_dir.iterdir():
                if skill_dir.is_dir():
                    meta = self._read_skill_meta(skill_dir)
                    if meta and self._matches_query(meta, query_lower):
                        meta["source"] = "bundled"
                        results.append(meta)

        # Search installed skills
        for skill_dir in self._installed_dir.iterdir():
            if skill_dir.is_dir():
                meta = self._read_skill_meta(skill_dir)
                if meta and self._matches_query(meta, query_lower):
                    meta["source"] = "installed"
                    results.append(meta)

        # Search community skills
        for skill_dir in self._community_dir.iterdir():
            if skill_dir.is_dir():
                meta = self._read_skill_meta(skill_dir)
                if meta and self._matches_query(meta, query_lower):
                    meta["source"] = "community"
                    results.append(meta)

        return results

    def list_installed(self) -> list[dict[str, Any]]:
        """List all installed (non-bundled) skills."""
        results = []
        for skill_dir in self._installed_dir.iterdir():
            if skill_dir.is_dir():
                meta = self._read_skill_meta(skill_dir)
                if meta:
                    results.append(meta)
        return results

    def list_all(self) -> dict[str, list[dict[str, Any]]]:
        """List all skills grouped by source."""
        catalog: dict[str, list[dict[str, Any]]] = {"bundled": [], "installed": [], "community": []}

        for source, base_dir in [("bundled", Path("skills/bundled")), ("installed", self._installed_dir), ("community", self._community_dir)]:
            if base_dir.exists():
                for skill_dir in base_dir.iterdir():
                    if skill_dir.is_dir():
                        meta = self._read_skill_meta(skill_dir)
                        if meta:
                            meta["source"] = source
                            catalog[source].append(meta)
        return catalog

    def install_from_url(self, url: str, name: str = "") -> dict[str, Any]:
        """Install a skill from a GitHub URL or local path."""
        import subprocess

        skill_name = name or url.split("/")[-1].replace(".git", "")
        target_dir = self._installed_dir / skill_name

        if target_dir.exists():
            return {"error": f"Skill '{skill_name}' already installed"}

        try:
            if url.startswith("/") or url.startswith("./"):
                # Local path — copy
                shutil.copytree(url, str(target_dir))
            else:
                # Git clone
                subprocess.run(
                    ["git", "clone", "--depth=1", url, str(target_dir)],
                    capture_output=True, timeout=60,
                )
                if not target_dir.exists():
                    return {"error": "Clone failed"}

            meta = self._read_skill_meta(target_dir)
            return {"success": True, "name": skill_name, "path": str(target_dir), "meta": meta}

        except Exception as e:
            return {"error": str(e)[:500]}

    def publish(self, skill_dir: str, description: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        """Publish a skill to the community directory."""
        source = Path(skill_dir)
        if not source.exists():
            return {"error": f"Skill directory not found: {skill_dir}"}

        name = source.name
        target = self._community_dir / name

        # Create module.yaml if not present
        yaml_path = source / "module.yaml"
        if not yaml_path.exists():
            manifest = {
                "schema_version": "1.0",
                "module_id": f"skill.community.{name}",
                "display_name": name.replace("_", " ").title(),
                "version": "1.0.0",
                "category": "skill",
                "description": description or f"Community skill: {name}",
                "tags": tags or [],
                "origin": "community",
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
            yaml_path.write_text(
                "\n".join(f"{k}: {json.dumps(v) if isinstance(v, (list, dict)) else v}" for k, v in manifest.items()),
                encoding="utf-8",
            )

        # Copy to community directory
        shutil.copytree(str(source), str(target), dirs_exist_ok=True)

        return {"success": True, "name": name, "path": str(target)}

    def remove(self, skill_name: str) -> dict[str, Any]:
        """Remove an installed skill."""
        target = self._installed_dir / skill_name
        if not target.exists():
            return {"error": f"Skill '{skill_name}' not found in installed directory"}

        shutil.rmtree(str(target))
        return {"success": True, "removed": skill_name}

    def get_info(self, skill_name: str) -> dict[str, Any] | None:
        """Get detailed info about a skill."""
        for base in [Path("skills/bundled"), self._installed_dir, self._community_dir]:
            skill_dir = base / skill_name
            if skill_dir.exists():
                meta = self._read_skill_meta(skill_dir)
                if meta:
                    # Read SKILL.md for full description
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        meta["full_description"] = skill_md.read_text(encoding="utf-8")[:2000]
                    meta["path"] = str(skill_dir)
                    meta["source"] = "bundled" if "bundled" in str(base) else "installed" if "installed" in str(base) else "community"
                    return meta
        return None

    def _read_skill_meta(self, skill_dir: Path) -> dict[str, Any] | None:
        """Read skill metadata from module.yaml or SKILL.md."""
        yaml_path = skill_dir / "module.yaml"
        meta: dict[str, Any] = {"name": skill_dir.name, "path": str(skill_dir)}

        if yaml_path.exists():
            try:
                for line in yaml_path.read_text(encoding="utf-8").splitlines():
                    if ":" in line:
                        key, _, value = line.partition(":")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and value:
                            meta[key] = value
            except Exception:
                pass
        else:
            # Try SKILL.md
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")[:500]
                meta["description"] = content[:200]

        return meta if meta.get("name") else None

    def _matches_query(self, meta: dict, query: str) -> bool:
        """Check if a skill matches a search query."""
        searchable = " ".join(str(v) for v in meta.values()).lower()
        return query in searchable


# Singleton
_marketplace: SkillMarketplace | None = None


def get_skill_marketplace() -> SkillMarketplace:
    global _marketplace
    if _marketplace is None:
        _marketplace = SkillMarketplace()
    return _marketplace
