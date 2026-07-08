"""Skill Feedback & Auto-Invocation — Enhances SkillLearner with explicit feedback and auto-invocation."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.skill_learner import SkillLearner, ExecutionTrace, SkillDraft

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SkillFeedback:
    """Explicit user feedback on a skill execution."""
    feedback_id: str
    skill_id: str
    interaction_id: str
    feedback_type: str  # thumbs_up, thumbs_down, correction, ignore
    comment: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(slots=True)
class SkillInvocationRecord:
    """Record of a skill being auto-invoked."""
    invocation_id: str
    skill_id: str
    trigger_pattern: str
    user_message: str
    success: bool
    latency_ms: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    context: dict[str, Any] = field(default_factory=dict)


class SkillFeedbackCollector:
    """Collects and processes explicit user feedback for skills."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "skills" / "feedback"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._feedback_file = self._dir / "feedback.jsonl"
        self._invocations_file = self._dir / "invocations.jsonl"
        self._stats_file = self._dir / "skill_stats.json"
        
        self._stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "invocations": 0,
            "successes": 0,
            "failures": 0,
            "thumbs_up": 0,
            "thumbs_down": 0,
            "corrections": 0,
            "avg_latency_ms": 0.0
        })
        self._load_stats()
    
    def _load_stats(self) -> None:
        try:
            if self._stats_file.exists():
                self._stats = defaultdict(lambda: {
                    "invocations": 0,
                    "successes": 0,
                    "failures": 0,
                    "thumbs_up": 0,
                    "thumbs_down": 0,
                    "corrections": 0,
                    "avg_latency_ms": 0.0
                }, json.loads(self._stats_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    
    def _save_stats(self) -> None:
        try:
            self._stats_file.write_text(
                json.dumps(dict(self._stats), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save skill stats: %s", e)
    
    def record_feedback(
        self,
        skill_id: str,
        interaction_id: str,
        feedback_type: str,
        comment: str = ""
    ) -> SkillFeedback:
        """Record explicit user feedback."""
        feedback = SkillFeedback(
            feedback_id=f"fb_{interaction_id}_{feedback_type}",
            skill_id=skill_id,
            interaction_id=interaction_id,
            feedback_type=feedback_type,
            comment=comment
        )
        
        # Persist
        try:
            with open(self._feedback_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(feedback), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to save feedback: %s", e)
        
        # Update stats
        stats = self._stats[skill_id]
        if feedback_type == "thumbs_up":
            stats["thumbs_up"] += 1
        elif feedback_type == "thumbs_down":
            stats["thumbs_down"] += 1
        elif feedback_type == "correction":
            stats["corrections"] += 1
        self._save_stats()
        
        return feedback
    
    def record_invocation(
        self,
        skill_id: str,
        trigger_pattern: str,
        user_message: str,
        success: bool,
        latency_ms: float,
        context: dict[str, Any] | None = None
    ) -> SkillInvocationRecord:
        """Record a skill auto-invocation."""
        invocation = SkillInvocationRecord(
            invocation_id=f"inv_{skill_id}_{int(datetime.now().timestamp() * 1000)}",
            skill_id=skill_id,
            trigger_pattern=trigger_pattern,
            user_message=user_message,
            success=success,
            latency_ms=latency_ms,
            context=context or {}
        )
        
        # Persist
        try:
            with open(self._invocations_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(invocation), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to save invocation: %s", e)
        
        # Update stats
        stats = self._stats[skill_id]
        stats["invocations"] += 1
        if success:
            stats["successes"] += 1
        else:
            stats["failures"] += 1
        
        # Update avg latency
        total = stats["invocations"]
        stats["avg_latency_ms"] = (
            (stats["avg_latency_ms"] * (total - 1) + latency_ms) / total
        )
        
        self._save_stats()
        
        return invocation
    
    def get_skill_stats(self, skill_id: str) -> dict[str, Any]:
        """Get statistics for a skill."""
        return dict(self._stats.get(skill_id, {}))
    
    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all skills."""
        return {k: dict(v) for k, v in self._stats.items()}
    
    def get_feedback_for_skill(self, skill_id: str) -> list[SkillFeedback]:
        """Get all feedback for a skill."""
        feedback = []
        try:
            if self._feedback_file.exists():
                for line in self._feedback_file.read_text(encoding="utf-8").strip().splitlines():
                    if line.strip():
                        fb = SkillFeedback(**json.loads(line))
                        if fb.skill_id == skill_id:
                            feedback.append(fb)
        except Exception as e:
            logger.error("Failed to load feedback: %s", e)
        return feedback


class SkillAutoInvoker:
    """Matches user messages to learned skill trigger patterns and auto-invokes them."""
    
    def __init__(
        self,
        skill_learner: SkillLearner,
        feedback_collector: SkillFeedbackCollector,
        min_confidence: float = 0.6
    ) -> None:
        self.skill_learner = skill_learner
        self.feedback_collector = feedback_collector
        self.min_confidence = min_confidence
        self._skill_cache: dict[str, dict[str, Any]] = {}
        self._reload_skills()
    
    def _reload_skills(self) -> None:
        """Reload all learned skills and their trigger patterns."""
        self._skill_cache.clear()
        learned_dir = self.skill_learner._learned_dir
        
        for skill_dir in learned_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            manifest_path = skill_dir / "module.yaml"
            if not manifest_path.exists():
                continue
            try:
                import yaml
                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
                module_id = manifest.get("module_id", "")
                triggers = manifest.get("triggers", [])
                
                if module_id and triggers:
                    self._skill_cache[module_id] = {
                        "name": manifest.get("display_name", module_id),
                        "triggers": triggers,
                        "confidence": manifest.get("confidence", 0.7),
                        "tools": manifest.get("capabilities", []),
                        "description": manifest.get("description", ""),
                        "manifest": manifest
                    }
            except Exception as e:
                logger.debug("Failed to load skill %s: %s", skill_dir.name, e)
        
        logger.info(f"Loaded {len(self._skill_cache)} learned skills for auto-invocation")
    
    def match_skills(self, user_message: str) -> list[dict[str, Any]]:
        """Find skills that match the user message."""
        matches = []
        msg_lower = user_message.lower()
        
        for skill_id, skill_data in self._skill_cache.items():
            for trigger in skill_data["triggers"]:
                pattern = trigger.get("pattern", "")
                confidence = trigger.get("confidence", skill_data["confidence"])
                
                if not pattern:
                    continue
                
                # Try regex match
                try:
                    if re.search(pattern, msg_lower, re.IGNORECASE):
                        matches.append({
                            "skill_id": skill_id,
                            "skill_name": skill_data["name"],
                            "trigger_pattern": pattern,
                            "confidence": confidence,
                            "tools": skill_data["tools"],
                            "description": skill_data["description"]
                        })
                        break  # Only count first matching trigger per skill
                except re.error:
                    # Fallback to simple substring match
                    if pattern.lower() in msg_lower:
                        matches.append({
                            "skill_id": skill_id,
                            "skill_name": skill_data["name"],
                            "trigger_pattern": pattern,
                            "confidence": confidence,
                            "tools": skill_data["tools"],
                            "description": skill_data["description"]
                        })
                        break
        
        # Sort by confidence
        matches.sort(key=lambda m: -m["confidence"])
        return matches
    
    def get_skill_manifest(self, skill_id: str) -> dict[str, Any] | None:
        """Get the full manifest for a skill."""
        return self._skill_cache.get(skill_id, {}).get("manifest")
    
    def invalidate_cache(self) -> None:
        """Force reload of skills."""
        self._reload_skills()


class EnhancedSkillLearner:
    """Enhanced SkillLearner with feedback integration and auto-invocation."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self.workspace_dir = workspace_dir
        self.base_learner = SkillLearner(project_root=workspace_dir)
        self.feedback_collector = SkillFeedbackCollector(workspace_dir)
        self.auto_invoker = SkillAutoInvoker(self.base_learner, self.feedback_collector)
        
        # Patch the base learner's save method to update auto-invoker cache
        original_save = self.base_learner.save
        
        async def enhanced_save(draft: SkillDraft) -> dict[str, Any]:
            result = await original_save(draft)
            self.auto_invoker.invalidate_cache()
            return result
        
        self.base_learner.save = enhanced_save
    
    async def observe(self, trace: ExecutionTrace) -> SkillDraft | None:
        """Observe an execution trace (delegates to base learner)."""
        return await self.base_learner.observe(trace)
    
    def record_feedback(
        self,
        skill_id: str,
        interaction_id: str,
        feedback_type: str,
        comment: str = ""
    ) -> SkillFeedback:
        """Record explicit user feedback."""
        return self.feedback_collector.record_feedback(skill_id, interaction_id, feedback_type, comment)
    
    def match_and_get_skills(self, user_message: str) -> list[dict[str, Any]]:
        """Find matching skills for a user message."""
        return self.auto_invoker.match_skills(user_message)
    
    def get_skill_performance(self, skill_id: str) -> dict[str, Any]:
        """Get performance stats for a skill."""
        return self.feedback_collector.get_skill_stats(skill_id)
    
    def get_all_skill_performance(self) -> dict[str, dict[str, Any]]:
        """Get performance for all skills."""
        return self.feedback_collector.get_all_stats()


# Global instance
_enhanced_skill_learner: EnhancedSkillLearner | None = None


def get_enhanced_skill_learner(workspace_dir: str = "workspace") -> EnhancedSkillLearner:
    """Get global enhanced skill learner instance."""
    global _enhanced_skill_learner
    if _enhanced_skill_learner is None:
        _enhanced_skill_learner = EnhancedSkillLearner(workspace_dir)
    return _enhanced_skill_learner