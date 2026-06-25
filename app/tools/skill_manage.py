"""Skill Management Tool — Agent-driven skill CRUD.

Allows any agent to list, create, read, update, and delete skills
programmatically via tool calls. Integrates with:
- ``SkillLearner`` persistence format (skills/<name>/module.yaml + SKILL.md)
- ``SkillRegistry`` discovery and health reporting
- Standard Hermes Agent pattern for autonomous skill management
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SkillManagementTool(BaseTool):
    """Manage skills: list, create, read, update, delete.

    Agents call this tool to autonomously manage their skill library.
    Skills are persisted in ``skills/learned/`` as ``module.yaml`` + ``SKILL.md``,
    compatible with both ``SkillLearner`` and ``SkillRegistry``.
    """

    group = "agent"

    def __init__(self, project_root: str | Path | None = None) -> None:
        self._project_root = (
            Path(project_root).resolve() if project_root else _PROJECT_ROOT
        )
        self._learned_dir = self._project_root / "skills" / "learned"
        self._learned_dir.mkdir(parents=True, exist_ok=True)

    def get_name(self) -> str:
        return "skill_manage"

    def get_description(self) -> str:
        return (
            "Manages agent skills: list, create, read, update, and delete. "
            "Skills are reusable multi-step procedures the agent can invoke. "
            "Actions: 'list' (show all skills), 'read' (show skill detail), "
            "'create' (create a new skill), 'update' (patch an existing skill), "
            "'delete' (remove a skill)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: list, read, create, update, delete",
                    required=True,
                    enum=["list", "read", "create", "update", "delete"],
                ),
                ToolParameter(
                    name="name",
                    type="string",
                    description="Skill name (required for read, update, delete; optional for create)",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Skill description (create/update)",
                    required=False,
                ),
                ToolParameter(
                    name="tags",
                    type="string",
                    description="Comma-separated tags for categorization (create/update)",
                    required=False,
                ),
                ToolParameter(
                    name="procedure",
                    type="string",
                    description="Newline-separated procedure steps (create/update)",
                    required=False,
                ),
                ToolParameter(
                    name="trigger_patterns",
                    type="string",
                    description="Comma-separated trigger keyword patterns (create/update)",
                    required=False,
                ),
                ToolParameter(
                    name="tools_used",
                    type="string",
                    description="Comma-separated tool names used by this skill (create/update)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        name = kwargs.get("name", "").strip()
        description = kwargs.get("description", "").strip()
        tags_str = kwargs.get("tags", "").strip()
        procedure_str = kwargs.get("procedure", "").strip()
        triggers_str = kwargs.get("trigger_patterns", "").strip()
        tools_str = kwargs.get("tools_used", "").strip()

        try:
            if action == "list":
                return self._list_skills()
            elif action == "read":
                if not name:
                    return {"success": False, "error": "name is required for read"}
                return self._read_skill(name)
            elif action == "create":
                return self._create_skill(name, description, tags_str, procedure_str, triggers_str, tools_str)
            elif action == "update":
                if not name:
                    return {"success": False, "error": "name is required for update"}
                return self._update_skill(name, description, tags_str, procedure_str, triggers_str, tools_str)
            elif action == "delete":
                if not name:
                    return {"success": False, "error": "name is required for delete"}
                return self._delete_skill(name)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("Skill management failed for action=%s name=%s", action, name)
            return {"success": False, "error": str(e)}

    def _slugify(self, name: str) -> str:
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        return slug or "unnamed_skill"

    def _skill_dir(self, name: str) -> Path:
        return self._learned_dir / self._slugify(name)

    def _list_skills(self) -> dict[str, Any]:
        try:
            from app.core.skill_registry import SkillRegistry
            sr = SkillRegistry(project_root=self._project_root)
            records = sr.discover()
            skills = [
                {
                    "name": r.get("display_name"),
                    "module_id": r.get("module_id"),
                    "description": r.get("description", ""),
                    "tags": r.get("tags", []),
                    "health": r.get("health_state", "unknown"),
                    "source_path": r.get("source_path"),
                }
                for r in records
            ]
            summary = sr.summary(records)
            return {
                "success": True,
                "skills": skills,
                "summary": summary,
            }
        except Exception:
            # Fallback: scan learned dir directly
            skills = []
            for d in sorted(self._learned_dir.iterdir()):
                if not d.is_dir():
                    continue
                manifest = d / "module.yaml"
                if not manifest.exists():
                    continue
                try:
                    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
                    skills.append({
                        "name": data.get("display_name", d.name),
                        "module_id": data.get("module_id", ""),
                        "description": data.get("description", ""),
                        "tags": data.get("tags", []),
                        "health": "unknown",
                        "source_path": str(d.relative_to(self._project_root)),
                    })
                except Exception:
                    continue
            return {
                "success": True,
                "skills": skills,
                "summary": {"count": len(skills), "healthy": 0, "degraded": 0, "unhealthy": 0},
            }

    def _read_skill(self, name: str) -> dict[str, Any]:
        skill_dir = self._skill_dir(name)
        manifest_path = skill_dir / "module.yaml"
        skill_md_path = skill_dir / "SKILL.md"

        if not manifest_path.exists():
            return {"success": False, "error": f"Skill '{name}' not found"}

        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        body = skill_md_path.read_text(encoding="utf-8") if skill_md_path.exists() else ""

        return {
            "success": True,
            "skill": {
                "name": data.get("display_name", name),
                "module_id": data.get("module_id", ""),
                "version": data.get("version", "0.1.0"),
                "description": data.get("description", ""),
                "tags": data.get("tags", []),
                "triggers": data.get("triggers", []),
                "capabilities": data.get("capabilities", []),
                "stability": data.get("stability", "experimental"),
                "confidence": data.get("confidence", 0.0),
                "invocation_count": data.get("invocation_count", 0),
                "success_rate": data.get("success_rate", 0.0),
                "learned_from": data.get("learned_from", ""),
            },
            "body": body[:2000] if body else "",
        }

    def _create_skill(
        self,
        name: str,
        description: str,
        tags_str: str,
        procedure_str: str,
        triggers_str: str,
        tools_str: str,
    ) -> dict[str, Any]:
        if not name:
            return {"success": False, "error": "name is required to create a skill"}

        slug = self._slugify(name)
        skill_dir = self._learned_dir / slug
        manifest_path = skill_dir / "module.yaml"

        if manifest_path.exists():
            return {"success": False, "error": f"Skill '{name}' already exists (use update to modify)"}

        skill_dir.mkdir(parents=True, exist_ok=True)

        tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
        tools_used = [t.strip() for t in tools_str.split(",") if t.strip()] if tools_str else []
        trigger_patterns = [t.strip() for t in triggers_str.split(",") if t.strip()] if triggers_str else []
        procedure_steps = [s.strip() for s in procedure_str.split("\n") if s.strip()] if procedure_str else []

        module_id = f"skill.learned.{slug}"

        manifest = {
            "schema_version": "1.0",
            "module_id": module_id,
            "display_name": name,
            "name": name,
            "version": "0.1.0",
            "category": "skill",
            "description": description or f"Agent-created skill: {name}",
            "tags": tags,
            "capabilities": tools_used,
            "trust_level": "workspace",
            "enabled_by_default": True,
            "stability": "experimental",
            "maturity": "development",
            "origin": "agent_created",
            "confidence": 0.7,
            "invocation_count": 0,
            "success_rate": 1.0,
            "triggers": [
                {"pattern": p, "confidence": 0.7}
                for p in trigger_patterns
            ],
        }

        manifest_path.write_text(
            yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        skill_md_lines = [
            "---",
            f"name: {name}",
            f"module_id: {module_id}",
            "version: 0.1.0",
            "category: skill",
            f"description: {description or f'Agent-created skill: {name}'}",
            f"tags: [{', '.join(tags)}]",
            "origin: agent_created",
            "---",
            "",
            f"# {name}",
            "",
            description or f"Agent-created skill: {name}",
        ]
        if procedure_steps:
            skill_md_lines.extend(["", "## Procedure", ""])
            for i, step in enumerate(procedure_steps, 1):
                skill_md_lines.append(f"{i}. {step}")

        skill_md_path = skill_dir / "SKILL.md"
        skill_md_path.write_text("\n".join(skill_md_lines) + "\n", encoding="utf-8")

        logger.info("Created skill: %s (module_id=%s)", name, module_id)

        return {
            "success": True,
            "message": f"Skill '{name}' created successfully",
            "skill": {
                "name": name,
                "module_id": module_id,
                "tags": tags,
                "triggers": trigger_patterns,
                "tools": tools_used,
                "procedure_steps": len(procedure_steps),
            },
        }

    def _update_skill(
        self,
        name: str,
        description: str,
        tags_str: str,
        procedure_str: str,
        triggers_str: str,
        tools_str: str,
    ) -> dict[str, Any]:
        skill_dir = self._skill_dir(name)
        manifest_path = skill_dir / "module.yaml"

        if not manifest_path.exists():
            return {"success": False, "error": f"Skill '{name}' not found (use create first)"}

        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}

        if description:
            data["description"] = description
        if tags_str:
            data["tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]
        if tools_str:
            data["capabilities"] = [t.strip() for t in tools_str.split(",") if t.strip()]
        if triggers_str:
            trigger_patterns = [t.strip() for t in triggers_str.split(",") if t.strip()]
            data["triggers"] = [
                {"pattern": p, "confidence": data.get("triggers", [{}])[0].get("confidence", 0.7) if data.get("triggers") else 0.7}
                for p in trigger_patterns
            ]
        data["version"] = self._bump_version(data.get("version", "0.1.0"))

        manifest_path.write_text(
            yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        if procedure_str:
            skill_md_path = skill_dir / "SKILL.md"
            procedure_steps = [s.strip() for s in procedure_str.split("\n") if s.strip()]
            skill_md_lines = [
                "---",
                f"name: {data.get('display_name', name)}",
                f"module_id: {data.get('module_id', '')}",
                "version: " + data.get("version", "0.1.0"),
                "category: skill",
                f"description: {data.get('description', '')}",
                f"tags: [{', '.join(data.get('tags', []))}]",
                f"origin: {data.get('origin', 'agent_created')}",
                "---",
                "",
                f"# {data.get('display_name', name)}",
                "",
                data.get("description", ""),
            ]
            if procedure_steps:
                skill_md_lines.extend(["", "## Procedure", ""])
                for i, step in enumerate(procedure_steps, 1):
                    skill_md_lines.append(f"{i}. {step}")
            skill_md_path.write_text("\n".join(skill_md_lines) + "\n", encoding="utf-8")

        logger.info("Updated skill: %s", name)

        return {
            "success": True,
            "message": f"Skill '{name}' updated successfully",
            "version": data.get("version"),
        }

    def _delete_skill(self, name: str) -> dict[str, Any]:
        import shutil

        skill_dir = self._skill_dir(name)
        if not skill_dir.exists():
            return {"success": False, "error": f"Skill '{name}' not found"}

        shutil.rmtree(skill_dir)
        logger.info("Deleted skill: %s", name)

        return {
            "success": True,
            "message": f"Skill '{name}' deleted successfully",
        }

    @staticmethod
    def _bump_version(current: str) -> str:
        parts = current.split(".")
        try:
            patch = int(parts[-1]) + 1 if parts[-1].isdigit() else 1
            parts[-1] = str(patch)
            return ".".join(parts)
        except (ValueError, IndexError):
            return "0.1.1"
