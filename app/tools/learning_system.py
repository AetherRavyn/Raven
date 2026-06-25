"""Learning System — study plans, quizzes, flashcards, and spaced repetition.

A comprehensive learning assistant that helps users:
- Create structured study plans from topics
- Generate quizzes with varying difficulty
- Track learning progress with spaced repetition
- Review and reinforce weak areas
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class LearningSystemTool(BaseTool):
    """Learning system with study plans, quizzes, and spaced repetition."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "learning"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._flashcards_file = self._dir / "flashcards.json"
        self._progress_file = self._dir / "progress.jsonl"
        self._plans_file = self._dir / "study_plans.json"
        self._quizzes_file = self._dir / "quiz_history.jsonl"

    def get_name(self) -> str:
        return "learning_system"

    def get_description(self) -> str:
        return (
            "Learning assistant: create study plans, generate quizzes, "
            "manage flashcards with spaced repetition, and track progress."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["create_plan", "list_plans", "add_flashcards", "quiz", "review",
                             "progress", "get_weak_areas", "reset_progress"],
                    "description": "Learning operation",
                },
                "topic": {"type": "string", "description": "Topic or subject"},
                "goals": {"type": "array", "description": "Learning goals for study plan"},
                "flashcards": {"type": "array", "description": "Flashcards [{question, answer, category}]"},
                "questions": {"type": "array", "description": "Quiz questions to evaluate"},
                "answers": {"type": "array", "description": "User answers to quiz questions"},
                "card_ids": {"type": "array", "description": "Flashcard IDs to review"},
                "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"], "description": "Quiz difficulty"},
                "plan_id": {"type": "string", "description": "Study plan ID"},
            },
            "required": ["operation"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        operation = kwargs.get("operation", "progress")

        if operation == "create_plan":
            return self._create_plan(kwargs.get("topic", ""), kwargs.get("goals", []))
        elif operation == "list_plans":
            return self._list_plans()
        elif operation == "add_flashcards":
            return self._add_flashcards(kwargs.get("flashcards", []), kwargs.get("topic", ""))
        elif operation == "quiz":
            return self._generate_quiz(kwargs.get("topic", ""), kwargs.get("difficulty", "medium"))
        elif operation == "review":
            return self._review_flashcards(kwargs.get("card_ids", []))
        elif operation == "progress":
            return self._get_progress(kwargs.get("topic"))
        elif operation == "get_weak_areas":
            return self._get_weak_areas()
        elif operation == "reset_progress":
            return self._reset_progress(kwargs.get("topic"))
        return {"error": f"Unknown operation: {operation}"}

    def _create_plan(self, topic: str, goals: list[str]) -> dict:
        """Create a structured study plan."""
        if not topic:
            return {"error": "topic is required"}

        import uuid
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"

        # Generate study milestones from goals
        milestones = []
        if goals:
            for i, goal in enumerate(goals):
                milestones.append({
                    "milestone": i + 1,
                    "goal": goal,
                    "status": "pending",
                    "estimated_hours": 2,
                })
        else:
            # Default milestones for any topic
            milestones = [
                {"milestone": 1, "goal": f"Understand core concepts of {topic}", "status": "pending", "estimated_hours": 4},
                {"milestone": 2, "goal": "Study key terminology and definitions", "status": "pending", "estimated_hours": 3},
                {"milestone": 3, "goal": "Practice with exercises and examples", "status": "pending", "estimated_hours": 4},
                {"milestone": 4, "goal": "Apply knowledge to real-world problems", "status": "pending", "estimated_hours": 5},
                {"milestone": 5, "goal": "Review and test understanding", "status": "pending", "estimated_hours": 3},
            ]

        plan = {
            "id": plan_id,
            "topic": topic,
            "goals": goals or [f"Master {topic}"],
            "milestones": milestones,
            "total_hours": sum(m.get("estimated_hours", 2) for m in milestones),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "progress": 0.0,
        }

        plans = self._load_plans()
        plans.append(plan)
        self._save_plans(plans)

        return {"success": True, "plan": plan}

    def _list_plans(self) -> list[dict]:
        return self._load_plans()

    def _add_flashcards(self, cards: list[dict], topic: str) -> dict:
        """Add flashcards with spaced repetition data."""
        if not cards:
            return {"error": "No flashcards provided"}

        existing = self._load_flashcards()
        new_count = 0

        for card in cards:
            if "question" not in card or "answer" not in card:
                continue
            import uuid
            card_id = f"card_{uuid.uuid4().hex[:8]}"
            new_card = {
                "id": card_id,
                "question": card["question"],
                "answer": card["answer"],
                "category": card.get("category", topic or "general"),
                # Spaced repetition fields
                "interval": 1,  # days
                "ease_factor": 2.5,
                "repetitions": 0,
                "next_review": time.time() + 86400,  # Tomorrow
                "last_review": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            existing.append(new_card)
            new_count += 1

        self._save_flashcards(existing)
        return {"success": True, "added": new_count, "total_cards": len(existing)}

    def _generate_quiz(self, topic: str, difficulty: str) -> dict:
        """Generate quiz questions for a topic."""
        # Generate questions from flashcards if available
        all_cards = self._load_flashcards()
        topic_cards = [c for c in all_cards if not topic or c.get("category", "").lower() == topic.lower()]

        if not topic_cards:
            topic_cards = all_cards  # Use all cards if no topic filter

        if not topic_cards:
            return {"error": f"No flashcards found for '{topic}'. Add flashcards first."}

        # Select cards for quiz based on difficulty
        n_questions = {"easy": 3, "medium": 5, "hard": 8}.get(difficulty, 5)
        selected = random.sample(topic_cards, min(n_questions, len(topic_cards)))

        questions = []
        for card in selected:
            # Generate options (correct + 3 distractors)
            wrong_answers = [c["answer"] for c in all_cards if c["id"] != card["id"]][:3]
            while len(wrong_answers) < 3:
                wrong_answers.append("Incorrect answer")

            options = [card["answer"]] + wrong_answers[:3]
            random.shuffle(options)

            questions.append({
                "id": card["id"],
                "question": card["question"],
                "options": options,
                "correct_answer": card["answer"],
                "category": card.get("category", ""),
            })

        return {
            "success": True,
            "topic": topic,
            "difficulty": difficulty,
            "questions": questions,
            "total_questions": len(questions),
        }

    def _review_flashcards(self, card_ids: list[str] | None = None) -> dict:
        """Get flashcards due for review (spaced repetition)."""
        all_cards = self._load_flashcards()
        now = time.time()

        if card_ids:
            due = [c for c in all_cards if c["id"] in card_ids]
        else:
            # Get cards due for review
            due = [c for c in all_cards if c.get("next_review", 0) <= now]

        if not due:
            # Return cards closest to due
            due = sorted(all_cards, key=lambda c: c.get("next_review", 0))[:5]

        return {"cards": due, "count": len(due)}

    def _update_flashcard(self, card_id: str, quality: int) -> dict:
        """Update flashcard based on review quality (0-5 scale, SM-2 algorithm)."""
        all_cards = self._load_flashcards()

        for card in all_cards:
            if card["id"] == card_id:
                # SM-2 spaced repetition algorithm
                if quality >= 3:  # Correct response
                    if card["repetitions"] == 0:
                        card["interval"] = 1
                    elif card["repetitions"] == 1:
                        card["interval"] = 6
                    else:
                        card["interval"] = round(card["interval"] * card["ease_factor"])
                    card["repetitions"] += 1
                else:  # Incorrect response
                    card["repetitions"] = 0
                    card["interval"] = 1

                # Update ease factor
                card["ease_factor"] = max(1.3, card["ease_factor"] + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
                card["last_review"] = time.time()
                card["next_review"] = time.time() + card["interval"] * 86400

                self._save_flashcards(all_cards)
                return {"success": True, "card": card}

        return {"error": f"Card {card_id} not found"}

    def _get_progress(self, topic: str | None = None) -> dict:
        """Get learning progress summary."""
        all_cards = self._load_flashcards()
        plans = self._load_plans()

        if topic:
            all_cards = [c for c in all_cards if c.get("category", "").lower() == topic.lower()]

        total = len(all_cards)
        mastered = sum(1 for c in all_cards if c.get("repetitions", 0) >= 3)
        learning = sum(1 for c in all_cards if 0 < c.get("repetitions", 0) < 3)
        new = sum(1 for c in all_cards if c.get("repetitions", 0) == 0)

        # Count overdue reviews
        now = time.time()
        overdue = sum(1 for c in all_cards if c.get("next_review", 0) <= now)

        plan_progress = 0.0
        if plans:
            for plan in plans:
                completed = sum(1 for m in plan.get("milestones", []) if m.get("status") == "completed")
                total_ms = len(plan.get("milestones", []))
                plan_progress += completed / max(total_ms, 1)
            plan_progress /= len(plans)

        return {
            "total_cards": total,
            "mastered": mastered,
            "learning": learning,
            "new": new,
            "overdue_reviews": overdue,
            "mastery_rate": f"{mastered / max(total, 1) * 100:.1f}%",
            "plans_count": len(plans),
            "plan_progress": f"{plan_progress * 100:.1f}%",
        }

    def _get_weak_areas(self) -> list[dict]:
        """Identify weak areas based on flashcard performance."""
        all_cards = self._load_flashcards()
        by_category: dict[str, list] = {}

        for card in all_cards:
            cat = card.get("category", "general")
            by_category.setdefault(cat, []).append(card)

        weak_areas = []
        for category, cards in by_category.items():
            avg_ease = sum(c.get("ease_factor", 2.5) for c in cards) / len(cards)
            avg_reps = sum(c.get("repetitions", 0) for c in cards) / len(cards)
            overdue = sum(1 for c in cards if c.get("next_review", 0) <= time.time())

            if avg_ease < 2.0 or overdue > len(cards) * 0.3:
                weak_areas.append({
                    "category": category,
                    "card_count": len(cards),
                    "avg_ease_factor": round(avg_ease, 2),
                    "avg_repetitions": round(avg_reps, 1),
                    "overdue": overdue,
                    "strength": "weak" if avg_ease < 2.0 else "needs_review",
                })

        weak_areas.sort(key=lambda x: x["avg_ease_factor"])
        return weak_areas

    def _reset_progress(self, topic: str | None = None) -> dict:
        """Reset learning progress."""
        if topic:
            all_cards = self._load_flashcards()
            reset = 0
            for card in all_cards:
                if card.get("category", "").lower() == topic.lower():
                    card["interval"] = 1
                    card["ease_factor"] = 2.5
                    card["repetitions"] = 0
                    card["next_review"] = time.time() + 86400
                    card["last_review"] = None
                    reset += 1
            self._save_flashcards(all_cards)
            return {"success": True, "reset": reset, "topic": topic}
        else:
            self._save_flashcards([])
            self._save_plans([])
            return {"success": True, "message": "All progress reset"}

    def _load_flashcards(self) -> list[dict]:
        if not self._flashcards_file.exists():
            return []
        try:
            return json.loads(self._flashcards_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_flashcards(self, cards: list[dict]) -> None:
        self._flashcards_file.write_text(json.dumps(cards, indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_plans(self) -> list[dict]:
        if not self._plans_file.exists():
            return []
        try:
            return json.loads(self._plans_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_plans(self, plans: list[dict]) -> None:
        self._plans_file.write_text(json.dumps(plans, indent=2, ensure_ascii=False), encoding="utf-8")
