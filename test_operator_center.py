from __future__ import annotations

from app.core.feedback import FeedbackStore
from app.core.skill_registry import SkillRegistry
from app.core.task_inbox import TaskInboxStore
from app.core.task_ledger import TaskLedger
from app.core.user_profile import UserProfileStore


def test_operator_inputs_exist(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    profile = UserProfileStore(str(workspace))
    profile.update_from_text("u1", "My name is Alex. I prefer concise answers.")

    inbox = TaskInboxStore(str(workspace))
    inbox.add_item("u1", "Follow up on roadmap", kind="follow_up")

    ledger = TaskLedger(str(workspace))
    ledger.add_task("task_1", "task", "Review onboarding")

    feedback = FeedbackStore(str(workspace))
    feedback.add_feedback("u1", "route", "local", 1.0)

    skills_dir = workspace / "skills" / "demo"
    skills_dir.mkdir(parents=True)
    (skills_dir / "module.yaml").write_text(
        """
schema_version: "1.0"
module_id: skill.demo
display_name: Demo Skill
version: "1.0.0"
category: skill
description: Demo skill
capabilities:
  - demo
""",
        encoding="utf-8",
    )

    registry = SkillRegistry(project_root=workspace)
    records = registry.discover()
    summary = registry.summary(records)

    assert records
    assert summary["count"] == 1
    assert summary["onboarding_queue"] == 0
    assert inbox.list_items(user_id="u1")
    assert ledger.list_tasks()
    assert feedback.summary("u1")["count"] == 1


def test_skill_registry_default_scans_repository_root() -> None:
    registry = SkillRegistry()
    records = registry.discover()
    summary = registry.summary(records)

    assert records
    assert any(record["display_name"] == "VirusTotal Scanner" for record in records)
    assert any(record["display_name"] == "Agent Reach" for record in records)
    assert summary["canonical"] == summary["count"]
    assert summary["inferred"] == 0
