from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    name: str
    interval_turns: int
    callback: Callable[[], Any] | None = None
    last_run_turn: int = 0
    enabled: bool = True


class TaskScheduler:
    """Turn-based periodic task runner with disk persistence.

    Call ``tick()`` at the end of every System 2 turn.  Tasks whose
    ``interval_turns`` have elapsed since their last run will fire.
    """

    def __init__(self, state_path: str | Path = "workspace/memory/task_scheduler.json") -> None:
        self._state_path = Path(state_path)
        self._tasks: list[ScheduledTask] = []
        self._current_turn = 0
        self._load()

    # ── public API ──────────────────────────────────────────────────────

    def register(self, name: str, interval_turns: int, callback: Callable[[], Any]) -> None:
        task = ScheduledTask(name=name, interval_turns=interval_turns, callback=callback)
        for existing in self._tasks:
            if existing.name == name:
                task.last_run_turn = existing.last_run_turn
                task.enabled = existing.enabled
                break
        self._tasks.append(task)

    def unregister(self, name: str) -> None:
        self._tasks = [t for t in self._tasks if t.name != name]

    def tick(self) -> list[str]:
        """Advance one turn and run any due tasks. Returns names of tasks that ran."""
        self._current_turn += 1
        ran: list[str] = []
        for task in self._tasks:
            if not task.enabled or task.callback is None:
                continue
            if self._current_turn - task.last_run_turn >= task.interval_turns:
                try:
                    task.callback()
                    ran.append(task.name)
                except Exception as e:
                    logger.warning("Task '%s' failed: %s", task.name, e)
                task.last_run_turn = self._current_turn
        if ran:
            self._save()
        return ran

    def reset(self) -> None:
        self._current_turn = 0
        for t in self._tasks:
            t.last_run_turn = 0
        if self._state_path.exists():
            self._state_path.unlink()

    # ── properties ──────────────────────────────────────────────────────

    @property
    def turn(self) -> int:
        return self._current_turn

    @property
    def tasks(self) -> list[ScheduledTask]:
        return list(self._tasks)

    # ── persistence ─────────────────────────────────────────────────────

    def _save(self) -> None:
        data: dict[str, Any] = {
            "current_turn": self._current_turn,
            "tasks": [
                {
                    "name": t.name,
                    "interval_turns": t.interval_turns,
                    "last_run_turn": t.last_run_turn,
                    "enabled": t.enabled,
                }
                for t in self._tasks
            ],
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._current_turn = data.get("current_turn", 0)
            for td in data.get("tasks", []):
                self._tasks.append(
                    ScheduledTask(
                        name=td["name"],
                        interval_turns=td["interval_turns"],
                        callback=None,
                        last_run_turn=td["last_run_turn"],
                        enabled=td.get("enabled", True),
                    )
                )
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            self._current_turn = 0
            self._tasks = []


# Singleton
_scheduler: TaskScheduler | None = None


def get_scheduler(state_path: str | Path | None = None) -> TaskScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler(state_path or "workspace/memory/task_scheduler.json")
    return _scheduler
