from __future__ import annotations

import json
import logging
import random
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Experience ──────────────────────────────────────────────────────────

@dataclass
class Experience:
    state_key: str
    action: str
    reward: float
    next_state_key: str
    done: bool
    timestamp: str = ""


# ── Q-Table ─────────────────────────────────────────────────────────────

@dataclass
class QEntry:
    q_value: float = 0.0
    visits: int = 0


class QTable:
    """Simple tabular Q-learning with UCB exploration."""

    def __init__(self, alpha: float = 0.1, gamma: float = 0.9, epsilon: float = 0.15) -> None:
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self._table: dict[str, dict[str, QEntry]] = defaultdict(lambda: defaultdict(QEntry))

    def get_q(self, state_key: str, action: str) -> float:
        return self._table[state_key][action].q_value

    def update(self, state_key: str, action: str, reward: float, next_state_key: str) -> None:
        entry = self._table[state_key][action]
        entry.visits += 1
        max_next = max(
            (self._table[next_state_key][a].q_value for a in self._table[next_state_key]),
            default=0.0,
        )
        td_target = reward + self.gamma * max_next
        entry.q_value += self.alpha * (td_target - entry.q_value)

    def best_action(self, state_key: str, available_actions: list[str]) -> str:
        if not available_actions:
            raise ValueError("No actions available")
        if random.random() < self.epsilon:
            return random.choice(available_actions)
        return max(
            available_actions,
            key=lambda a: self._table[state_key][a].q_value,
        )

    def best_q(self, state_key: str, available_actions: list[str]) -> float:
        if not available_actions:
            return 0.0
        return max(self._table[state_key][a].q_value for a in available_actions)

    def to_dict(self) -> dict[str, dict[str, dict[str, float]]]:
        return {
            state: {act: {"q": e.q_value, "visits": e.visits} for act, e in actions.items()}
            for state, actions in self._table.items()
        }

    @classmethod
    def from_dict(cls, data: dict[str, dict[str, dict[str, float]]], **kwargs: Any) -> QTable:
        qt = cls(**kwargs)
        for state, actions in data.items():
            for act, vals in actions.items():
                qt._table[state][act].q_value = vals.get("q", 0.0)
                qt._table[state][act].visits = int(vals.get("visits", 0))
        return qt


# ── Reinforcement Learner ───────────────────────────────────────────────

@dataclass
class RLStats:
    total_episodes: int = 0
    total_reward: float = 0.0
    avg_reward: float = 0.0
    best_reward: float = float("-inf")
    last_episode_reward: float = 0.0
    recent_rewards: list[float] = field(default_factory=list)

    def record(self, reward: float) -> None:
        self.total_episodes += 1
        self.total_reward += reward
        self.avg_reward = self.total_reward / self.total_episodes
        if reward > self.best_reward:
            self.best_reward = reward
        self.last_episode_reward = reward
        self.recent_rewards.append(reward)
        self.recent_rewards = self.recent_rewards[-100:]


class ReinforcementLearner:
    """Q-learning agent that optimises routing, tool, and strategy selection.

    State dimensions:
      - task_category (str)
      - hour_bucket (int: 0-5)
      - user_tier (str: new|regular|power)

    Action domains:
      - agent: which agent to route to
      - strategy: which reasoning strategy to use
      - tool: which tool to try first

    Rewards:
      +1.0  explicit positive feedback
      -1.0  explicit negative feedback
      +0.5  successful tool call
      -0.3  tool call failure
      -0.2  user repeated themselves
      +0.2  task completed successfully
    """

    DATA_DIR = "reinforcement_learning"

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config

        base = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        self._data_dir = base / self.DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self.q_table = QTable()
        self.stats = RLStats()
        self._replay_buffer: list[Experience] = []
        self._max_buffer = 5000

        self._load()

    # ── Persistence ─────────────────────────────────────────────────────

    def _q_path(self) -> Path:
        return self._data_dir / "q_table.json"

    def _stats_path(self) -> Path:
        return self._data_dir / "stats.json"

    def _buffer_path(self) -> Path:
        return self._data_dir / "replay_buffer.jsonl"

    def _save(self) -> None:
        try:
            self._q_path().write_text(json.dumps(self.q_table.to_dict(), indent=2))
            self._stats_path().write_text(json.dumps(asdict(self.stats), indent=2))
            with open(self._buffer_path(), "w") as f:
                for exp in self._replay_buffer[-1000:]:
                    f.write(json.dumps(asdict(exp)) + "\n")
        except Exception as e:
            logger.debug("RL save failed: %s", e)

    def _load(self) -> None:
        try:
            if self._q_path().exists():
                data = json.loads(self._q_path().read_text())
                self.q_table = QTable.from_dict(data)
        except Exception as e:
            logger.debug("RL load q_table failed: %s", e)
        try:
            if self._stats_path().exists():
                data = json.loads(self._stats_path().read_text())
                self.stats = RLStats(**data)
        except Exception as e:
            logger.debug("RL load stats failed: %s", e)
        try:
            if self._buffer_path().exists():
                with open(self._buffer_path()) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            self._replay_buffer.append(Experience(**json.loads(line)))
        except Exception as e:
            logger.debug("RL load buffer failed: %s", e)

    # ── State key builder ──────────────────────────────────────────────

    @staticmethod
    def _hour_bucket(hour: int | None = None) -> int:
        if hour is None:
            hour = datetime.now().hour
        if 5 <= hour < 9:
            return 0  # morning
        if 9 <= hour < 13:
            return 1  # late morning
        if 13 <= hour < 17:
            return 2  # afternoon
        if 17 <= hour < 22:
            return 3  # evening
        return 4  # night

    def _user_tier(self, interaction_count: int) -> str:
        if interaction_count < 10:
            return "new"
        if interaction_count < 100:
            return "regular"
        return "power"

    def state_key(self, task_category: str, interaction_count: int = 0) -> str:
        hb = self._hour_bucket()
        tier = self._user_tier(interaction_count)
        return f"{task_category}|{hb}|{tier}"

    # ── Core RL operations ─────────────────────────────────────────────

    def select_action(
        self,
        state_key: str,
        available_actions: list[str],
    ) -> str:
        """Select best action via Q-learning with epsilon-greedy."""
        return self.q_table.best_action(state_key, available_actions)

    def learn(
        self,
        state_key: str,
        action: str,
        reward: float,
        next_state_key: str,
        done: bool = False,
    ) -> None:
        """Single-step Q-learning update + buffer append."""
        self.q_table.update(state_key, action, reward, next_state_key)
        exp = Experience(
            state_key=state_key,
            action=action,
            reward=reward,
            next_state_key=next_state_key,
            done=done,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._replay_buffer.append(exp)
        if len(self._replay_buffer) > self._max_buffer:
            self._replay_buffer = self._replay_buffer[-self._max_buffer:]
        self.stats.record(reward)
        self._save()

    def replay(self, batch_size: int = 32) -> int:
        """Sample from replay buffer and train on it. Returns count trained."""
        if len(self._replay_buffer) < 2:
            return 0
        batch = random.sample(self._replay_buffer, min(batch_size, len(self._replay_buffer)))
        for exp in batch:
            self.q_table.update(exp.state_key, exp.action, exp.reward, exp.next_state_key)
        self._save()
        return len(batch)

    # ── Feedback integration ──────────────────────────────────────────

    def record_outcome(
        self,
        task_category: str,
        action: str,
        success: bool,
        interaction_count: int = 0,
        user_rating: float | None = None,
    ) -> None:
        """Record a single outcome and learn from it."""
        sk = self.state_key(task_category, interaction_count)
        reward = self._compute_reward(success, user_rating)
        # Next state is the same state (within-episode)
        self.learn(sk, action, reward, sk, done=True)

    @staticmethod
    def _compute_reward(success: bool, user_rating: float | None = None) -> float:
        if user_rating is not None:
            return user_rating
        return 0.5 if success else -0.3

    # ── Dashboard data ────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Return a snapshot for the dashboard."""
        return {
            "stats": asdict(self.stats),
            "replay_buffer_size": len(self._replay_buffer),
            "state_count": len(self.q_table._table),
            "total_actions": sum(
                len(actions) for actions in self.q_table._table.values()
            ),
            "top_states": [
                {
                    "state": s,
                    "actions": {
                        a: {"q": round(e.q_value, 3), "visits": e.visits}
                        for a, e in acts.items()
                    },
                }
                for s, acts in sorted(
                    self.q_table._table.items(),
                    key=lambda x: sum(e.visits for e in x[1].values()),
                    reverse=True,
                )[:20]
            ],
        }


# ── Module singleton ───────────────────────────────────────────────────

_RL_INSTANCE: ReinforcementLearner | None = None


def get_reinforcement_learner() -> ReinforcementLearner:
    global _RL_INSTANCE
    if _RL_INSTANCE is None:
        _RL_INSTANCE = ReinforcementLearner()
    return _RL_INSTANCE
