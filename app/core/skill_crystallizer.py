from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.learning_db import get_learning_store

logger = logging.getLogger(__name__)

SKILL_TEMPLATE = """# {title}

{description}

## Triggers
{triggers}

## Learned Behavior
{body}

## Confidence
{confidence}

## Source
{source}

## Metadata
- **Crystallized at**: {crystallized_at}
- **Based on {count} learning(s)**
- **Type**: {skill_type}
"""

MODULE_YAML_TEMPLATE = """name: {name}
description: {description}
version: "1.0"
author: raven-self-improvement

triggers:
{triggers_yaml}

skills:
  - {name}

config:
  confidence_threshold: {confidence}
"""


class SkillCrystallizer:
    """Crystallize learnings from the unified store into persistent SKILL.md files.

    Groups related learnings by topic, picks the highest-confidence representative,
    and writes structured skill files that can be loaded by the SkillRegistry.
    """

    def __init__(self, skills_dir: str | Path = "workspace/skills") -> None:
        self._skills_dir = Path(skills_dir)
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._store = get_learning_store()

    # ── public API ──────────────────────────────────────────────────────

    def crystallize_all(
        self,
        *,
        min_confidence: float = 0.5,
        min_items_per_skill: int = 1,
    ) -> list[str]:
        """Crystallize all qualified learnings into skills. Returns skill names created."""
        created: list[str] = []

        # Group learnings by topic for each type
        topics: dict[str, list[dict[str, Any]]] = {}
        for row in self._store.get_recent(min_confidence=min_confidence):
            topic = row.get("topic", "") or "general"
            key = f"{row['type']}:{topic}"
            topics.setdefault(key, []).append(row)

        for key, items in topics.items():
            if len(items) < min_items_per_skill:
                continue

            type_, topic = key.split(":", 1)
            name = self._generate_skill_name(type_, topic)
            skill_path = self._skills_dir / name / "SKILL.md"
            if skill_path.exists():
                continue  # don't overwrite existing skills

            created.append(name)
            self._write_skill(name, type_, topic, items)

        return created

    def crystallize_topic(
        self,
        type_: str,
        topic: str,
        *,
        min_confidence: float = 0.5,
    ) -> str | None:
        """Crystallize a single topic into a skill. Returns skill name or None."""
        items = self._store.get_by_topic(topic, type_=type_)
        items = [i for i in items if i["confidence"] >= min_confidence]
        if not items:
            return None

        name = self._generate_skill_name(type_, topic)
        self._write_skill(name, type_, topic, items)
        return name

    def get_crystallized_skills(self) -> list[dict[str, Any]]:
        """List all crystallized skills with metadata."""
        skills: list[dict[str, Any]] = []
        for skill_dir in self._skills_dir.iterdir():
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            meta = self._read_skill_metadata(skill_file)
            if meta:
                skills.append(meta)
        return skills

    # ── internal ────────────────────────────────────────────────────────

    def _generate_skill_name(self, type_: str, topic: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        type_prefix = type_.replace("_", "-")
        return f"{type_prefix}--{base}" if base else type_prefix

    def _write_skill(self, name: str, type_: str, topic: str, items: list[dict[str, Any]]) -> None:
        skill_dir = self._skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        best = max(items, key=lambda i: i["confidence"])
        description = f"Learned behavior about {topic} from {type_} signals."
        triggers = self._generate_triggers(topic, type_)
        body = self._format_body(items)
        confidence = f"{best['confidence']:.2f}"

        source = best.get("source", "self-improvement")
        meta = (
            json.loads(best["metadata"])
            if isinstance(best.get("metadata"), str)
            else best.get("metadata", {})
        )
        if meta.get("source"):
            source = f"{source} ({meta['source']})"

        skill_content = SKILL_TEMPLATE.format(
            title=name.replace("--", ": ").replace("-", " ").title(),
            description=description,
            triggers=triggers,
            body=body,
            confidence=confidence,
            source=source,
            crystallized_at=datetime.now(timezone.utc).isoformat(),
            count=len(items),
            skill_type=type_,
        )

        (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")

        triggers_yaml = "\n".join(
            f"  - {t.replace(':', ':').strip()}" for t in triggers.splitlines() if t.strip()
        )
        module_yaml = MODULE_YAML_TEMPLATE.format(
            name=name,
            description=description,
            triggers_yaml=triggers_yaml,
            confidence=confidence,
        )
        (skill_dir / "module.yaml").write_text(module_yaml, encoding="utf-8")

        logger.info("Crystallized skill '%s' from %d %s learnings", name, len(items), type_)

    def _generate_triggers(self, topic: str, type_: str) -> str:
        words = set(re.sub(r"[^a-z0-9\s]", " ", topic.lower()).split())
        triggers = [f"- keyword: `{w}`" for w in sorted(words) if len(w) > 2]
        if not triggers:
            triggers = [f"- keyword: `{topic.lower()}`"]
        if type_.startswith("correction"):
            triggers.append("- intent: `correction`")
        return "\n".join(triggers)

    def _format_body(self, items: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for i, item in enumerate(items, 1):
            confidence = item.get("confidence", 0.0)
            badge = self._confidence_badge(confidence)
            lines.append(f"### Learning {i} {badge}")
            lines.append(f"{item['content']}")
            if item.get("source"):
                lines.append(f"*Source: {item['source']}*")
            meta = (
                json.loads(item["metadata"])
                if isinstance(item.get("metadata"), str)
                else item.get("metadata", {})
            )
            if meta.get("reason"):
                lines.append(f"*Reason: {meta['reason']}*")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _read_skill_metadata(path: Path) -> dict[str, Any] | None:
        try:
            content = path.read_text(encoding="utf-8")
            title = ""
            skill_type = ""
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                elif line.startswith("## Trigger") or line.startswith("## Learned"):
                    pass
                elif line.startswith("- **Type**:"):
                    skill_type = line.split(":", 1)[1].strip()
            return {
                "name": path.parent.name,
                "title": title,
                "skill_type": skill_type,
                "path": str(path),
            }
        except Exception:
            return None

    @staticmethod
    def _confidence_badge(confidence: float) -> str:
        if confidence >= 0.9:
            return "⭐"
        if confidence >= 0.7:
            return "✅"
        if confidence >= 0.5:
            return "🟡"
        return "⚪"

    def clear(self) -> None:
        for child in self._skills_dir.iterdir():
            if child.is_dir():
                for f in child.iterdir():
                    f.unlink()
                child.rmdir()
