"""Analogy Engine — Case-based reasoning from past experience.

Finds similar past problems and transfers their solutions to new situations.
Uses embedding similarity over past interaction records stored in memory.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SolvedCase:
    """A past problem-solution pair."""

    id: str = ""
    problem: str = ""
    solution: str = ""
    tools_used: list[str] = field(default_factory=list)
    category: str = "general"
    success: bool = True
    confidence: float = 1.0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Analogy:
    """A retrieved analogy: a past case + its similarity score."""

    case: SolvedCase
    similarity: float  # 0.0 to 1.0
    transferable: bool = True  # Whether the solution likely applies


class AnalogyEngine:
    """Case-based reasoning — finds past solutions for current problems.

    Maintains a case library of past solved problems. When a new problem
    arrives, finds the most similar cases and suggests adaptations.

    Uses keyword overlap for lightweight similarity. Can be upgraded to
    vector similarity when embeddings are available.
    """

    def __init__(self, store_dir: str | Path | None = None) -> None:
        if store_dir is None:
            from app.settings.config import Config
            store_dir = Path(Config.MEMORY_ROOT) / "analogy"
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._cases: list[SolvedCase] = []
        self._load()

    # ── Case Recording ──────────────────────────────────────────────

    def record_case(
        self,
        problem: str,
        solution: str,
        tools_used: list[str] | None = None,
        category: str = "general",
        success: bool = True,
        confidence: float = 1.0,
    ) -> SolvedCase:
        """Record a solved problem for future analogical retrieval."""
        import hashlib
        case_id = hashlib.sha256(problem.encode()).hexdigest()[:12]

        keywords = self._extract_keywords(problem + " " + solution)

        case = SolvedCase(
            id=case_id,
            problem=problem,
            solution=solution,
            tools_used=tools_used or [],
            category=category,
            success=success,
            confidence=confidence,
            keywords=keywords,
        )

        # Deduplicate by id
        self._cases = [c for c in self._cases if c.id != case_id]
        self._cases.append(case)

        # Keep library bounded
        if len(self._cases) > 500:
            self._cases = self._cases[-500:]

        self._save()
        logger.debug("Recorded case: %s (%d keywords)", case_id, len(keywords))
        return case

    # ── Retrieval ───────────────────────────────────────────────────

    def find_analogies(
        self,
        problem: str,
        top_k: int = 3,
        min_similarity: float = 0.15,
        category: str | None = None,
    ) -> list[Analogy]:
        """Find similar past problems and their solutions.

        Uses embedding cosine similarity when the SentenceTransformer
        model is available, falls back to keyword Jaccard similarity.
        """
        # Try embedding similarity first
        embedding_sim = self._embedding_similarity(problem)
        if embedding_sim is not None:
            return self._find_by_embeddings(
                problem, embedding_sim, top_k, min_similarity, category
            )

        # Fallback: keyword Jaccard similarity
        query_keywords = set(self._extract_keywords(problem))
        if not query_keywords:
            return []

        candidates: list[Analogy] = []

        for case in self._cases:
            if not case.success:
                continue
            if category and case.category != category:
                continue

            case_keywords = set(case.keywords)
            if not case_keywords:
                continue

            # Jaccard similarity
            intersection = query_keywords & case_keywords
            union = query_keywords | case_keywords
            similarity = len(intersection) / len(union) if union else 0.0

            # Boost for category match
            if case.category == (category or "general"):
                similarity *= 1.1

            similarity = min(1.0, similarity)

            if similarity >= min_similarity:
                candidates.append(Analogy(
                    case=case,
                    similarity=similarity,
                    transferable=similarity >= 0.3,
                ))

        candidates.sort(key=lambda a: -a.similarity)
        return candidates[:top_k]

    def _embedding_similarity(self, text: str):
        """Get embedding function if model is available, else None."""
        try:
            from app.db.memory_helix import _get_embedding_model
            model = _get_embedding_model("all-MiniLM-L6-v2")
            return model.encode
        except Exception:
            return None

    def _find_by_embeddings(
        self,
        problem: str,
        encode_fn,
        top_k: int,
        min_similarity: float,
        category: str | None,
    ) -> list[Analogy]:
        """Find analogies using cosine similarity over embeddings."""
        import numpy as np

        query_vec = encode_fn(problem)
        candidates: list[Analogy] = []

        for case in self._cases:
            if not case.success:
                continue
            if category and case.category != category:
                continue

            case_text = f"{case.problem} {case.solution}"
            case_vec = encode_fn(case_text)

            # Cosine similarity
            sim = float(np.dot(query_vec, case_vec) / (
                np.linalg.norm(query_vec) * np.linalg.norm(case_vec) + 1e-8
            ))

            # Boost for category match
            if case.category == (category or "general"):
                sim = min(1.0, sim * 1.1)

            if sim >= min_similarity:
                candidates.append(Analogy(
                    case=case,
                    similarity=sim,
                    transferable=sim >= 0.3,
                ))

        candidates.sort(key=lambda a: -a.similarity)
        return candidates[:top_k]

    def suggest_approach(self, problem: str, category: str = "general") -> str:
        """Generate a suggestion based on past analogies."""
        analogies = self.find_analogies(problem, top_k=3, category=category)
        if not analogies:
            return ""

        lines: list[str] = ["## 💡 Analogical Suggestions\n"]
        for i, analogy in enumerate(analogies, 1):
            sim_pct = f"{analogy.similarity:.0%}"
            lines.append(f"### Analogy {i} ({sim_pct} similar)")
            lines.append(f"**Past Problem**: {analogy.case.problem[:200]}")
            lines.append(f"**Solution Used**: {analogy.case.solution[:300]}")
            if analogy.case.tools_used:
                lines.append(f"**Tools**: {', '.join(analogy.case.tools_used)}")
            lines.append("")

        return "\n".join(lines)

    # ── Statistics ──────────────────────────────────────────────────

    @property
    def case_count(self) -> int:
        return len(self._cases)

    def get_categories(self) -> dict[str, int]:
        """Return category → count mapping."""
        cats: dict[str, int] = {}
        for case in self._cases:
            cats[case.category] = cats.get(case.category, 0) + 1
        return cats

    # ── Keyword Extraction ──────────────────────────────────────────

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """Extract meaningful keywords from text."""
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "can", "shall",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after", "and",
            "but", "or", "nor", "not", "no", "so", "if", "then", "than",
            "too", "very", "just", "about", "up", "out", "it", "its",
            "this", "that", "these", "those", "i", "you", "he", "she",
            "we", "they", "me", "him", "her", "us", "them", "my", "your",
            "his", "our", "their", "what", "which", "who", "how", "when",
            "where", "why", "all", "each", "every", "any", "few", "more",
        }
        import re
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        return [w for w in words if w not in stop_words]

    # ── Persistence ─────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            path = self._store_dir / "cases.json"
            data = [asdict(c) for c in self._cases]
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to save analogy cases: %s", exc)

    def _load(self) -> None:
        path = self._store_dir / "cases.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._cases = [SolvedCase(**c) for c in data]
        except Exception as exc:
            logger.warning("Failed to load analogy cases: %s", exc)


_GLOBAL_ANALOGY: AnalogyEngine | None = None


def get_analogy_engine() -> AnalogyEngine:
    global _GLOBAL_ANALOGY
    if _GLOBAL_ANALOGY is None:
        _GLOBAL_ANALOGY = AnalogyEngine()
    return _GLOBAL_ANALOGY
