from __future__ import annotations

from app.core.skill_registry import SkillRegistry


def test_skill_registry_discovers_canonical_manifest(tmp_path) -> None:
    project_root = tmp_path
    skills_dir = project_root / "skills" / "virustotal-scanner"
    skills_dir.mkdir(parents=True)
    (skills_dir / "module.yaml").write_text(
        """
schema_version: "1.0"
module_id: integration.virustotal_scanner
display_name: VirusTotal Scanner
version: "1.0.0"
category: integration
description: VirusTotal scanning skill
capabilities:
  - lookup
""",
        encoding="utf-8",
    )

    registry = SkillRegistry(project_root=project_root)
    records = registry.discover()

    assert len(records) == 1
    record = records[0]
    assert record["module_id"] == "integration.virustotal_scanner"
    assert record["canonical_manifest"] is True
    assert record["health_state"] in {"healthy", "degraded"}


def test_skill_registry_summary_counts(tmp_path) -> None:
    project_root = tmp_path
    skills_dir = project_root / "skills" / "basic-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        """
---
name: basic-skill
description: Basic skill
---

# Basic Skill
""",
        encoding="utf-8",
    )

    registry = SkillRegistry(project_root=project_root)
    summary = registry.summary(registry.discover())

    assert summary["count"] == 1
    assert summary["canonical"] == 0
    assert summary["inferred"] == 1
    assert summary["onboarding_queue"] == 1
