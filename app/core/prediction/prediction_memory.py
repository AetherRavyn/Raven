"""Prediction Memory — Tracks predictions, outcomes, and learning over time.

This is how Raven gets smarter: by remembering what it predicted, why, 
and how accurate it was. Enables meta-learning and confidence calibration.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PredictionRecord:
    """A complete prediction record with full context."""
    prediction_id: str
    prediction_type: str  # forecast, scenario, causal, opportunity, risk
    query: str  # What was being predicted
    prediction: dict[str, Any]  # The actual prediction content
    confidence: float  # 0-1
    reasoning: str  # Why this prediction was made
    assumptions: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)  # Sources, data points
    time_horizon: str = ""  # e.g., "7 days", "30 days", "Q3 2026"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    context: dict[str, Any] = field(default_factory=dict)  # World state at prediction time
    
    # Outcome tracking
    outcome: dict[str, Any] | None = None
    actual_outcome: str | None = None
    accuracy: float | None = None  # 0-1, set after outcome known
    calibrated: bool = False
    outcome_recorded_at: str | None = None
    
    # Learning
    lessons_learned: list[str] = field(default_factory=list)
    model_version: str = "1.0"
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PredictionCluster:
    """A cluster of related predictions for pattern analysis."""
    cluster_id: str
    theme: str
    prediction_ids: list[str]
    common_factors: list[str]
    success_rate: float = 0.0
    avg_confidence: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PredictionMemory:
    """Long-term memory for predictions and their outcomes."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "prediction" / "memory"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._predictions_file = self._dir / "predictions.jsonl"
        self._clusters_file = self._dir / "clusters.json"
        self._index_file = self._dir / "index.json"
        
        self._predictions: dict[str, PredictionRecord] = {}
        self._clusters: dict[str, PredictionCluster] = {}
        self._index: dict[str, list[str]] = defaultdict(list)  # tag -> prediction_ids
        self._load()

    def _load(self) -> None:
        try:
            if self._predictions_file.exists():
                for line in self._predictions_file.read_text(encoding="utf-8").strip().splitlines():
                    if line.strip():
                        record = PredictionRecord(**json.loads(line))
                        self._predictions[record.prediction_id] = record
                        for tag in record.tags:
                            self._index[tag].append(record.prediction_id)
            if self._clusters_file.exists():
                data = json.loads(self._clusters_file.read_text(encoding="utf-8"))
                self._clusters = {k: PredictionCluster(**v) for k, v in data.items()}
        except Exception as e:
            logger.warning("Failed to load prediction memory: %s", e)

    def _save(self) -> None:
        try:
            # Append new predictions
            with open(self._predictions_file, "a", encoding="utf-8") as f:
                for pred in self._predictions.values():
                    # Only write if not already in file (simplified: check if outcome recorded)
                    if pred.calibrated and pred.outcome_recorded_at:
                        f.write(json.dumps(asdict(pred), ensure_ascii=False) + "\n")
            
            self._clusters_file.write_text(
                json.dumps({k: asdict(v) for k, v in self._clusters.items()}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save prediction memory: %s", e)

    def record_prediction(
        self,
        prediction_type: str,
        query: str,
        prediction: dict[str, Any],
        confidence: float,
        reasoning: str,
        assumptions: list[str] | None = None,
        evidence: list[str] | None = None,
        time_horizon: str = "",
        context: dict[str, Any] | None = None,
        tags: list[str] | None = None
    ) -> str:
        """Record a new prediction."""
        prediction_id = f"pred_{uuid.uuid4().hex[:12]}"
        
        record = PredictionRecord(
            prediction_id=prediction_id,
            prediction_type=prediction_type,
            query=query,
            prediction=prediction,
            confidence=confidence,
            reasoning=reasoning,
            assumptions=assumptions or [],
            evidence=evidence or [],
            time_horizon=time_horizon,
            context=context or {},
            tags=tags or []
        )
        
        self._predictions[prediction_id] = record
        for tag in record.tags:
            self._index[tag].append(prediction_id)
        
        # Save immediately for durability
        with open(self._predictions_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        
        return prediction_id

    def record_outcome(
        self,
        prediction_id: str,
        actual_outcome: str,
        outcome_data: dict[str, Any] | None = None,
        accuracy: float | None = None
    ) -> bool:
        """Record the actual outcome for a prediction."""
        record = self._predictions.get(prediction_id)
        if not record:
            logger.warning(f"Prediction {prediction_id} not found")
            return False
        
        record.actual_outcome = actual_outcome
        record.outcome = outcome_data or {}
        record.accuracy = accuracy
        record.calibrated = True
        record.outcome_recorded_at = datetime.now(timezone.utc).isoformat()
        
        # Auto-generate lessons learned
        if accuracy is not None:
            if accuracy > 0.8:
                record.lessons_learned.append(f"High accuracy ({accuracy:.0%}) - reasoning was sound")
            elif accuracy > 0.5:
                record.lessons_learned.append(f"Moderate accuracy ({accuracy:.0%}) - some factors missed")
            else:
                record.lessons_learned.append(f"Low accuracy ({accuracy:.0%}) - reassess assumptions: {', '.join(record.assumptions[:3])}")
        
        # Re-save the updated record
        self._rewrite_predictions_file()
        return True

    def _rewrite_predictions_file(self) -> None:
        """Rewrite the entire predictions file with current state."""
        try:
            with open(self._predictions_file, "w", encoding="utf-8") as f:
                for record in self._predictions.values():
                    f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to rewrite predictions file: %s", e)

    def get_prediction(self, prediction_id: str) -> PredictionRecord | None:
        return self._predictions.get(prediction_id)

    def get_predictions_by_tag(self, tag: str) -> list[PredictionRecord]:
        ids = self._index.get(tag, [])
        return [self._predictions[pid] for pid in ids if pid in self._predictions]

    def get_predictions_by_type(self, prediction_type: str) -> list[PredictionRecord]:
        return [p for p in self._predictions.values() if p.prediction_type == prediction_type]

    def get_recent_predictions(self, n: int = 50) -> list[PredictionRecord]:
        sorted_preds = sorted(
            self._predictions.values(),
            key=lambda p: p.created_at,
            reverse=True
        )
        return sorted_preds[:n]

    def get_calibrated_predictions(self) -> list[PredictionRecord]:
        return [p for p in self._predictions.values() if p.calibrated]

    # ── Analytics ─────────────────────────────────────────────────

    def get_accuracy_by_type(self) -> dict[str, dict[str, float]]:
        """Get accuracy statistics grouped by prediction type."""
        calibrated = self.get_calibrated_predictions()
        if not calibrated:
            return {}
        
        by_type = defaultdict(list)
        for p in calibrated:
            if p.accuracy is not None:
                by_type[p.prediction_type].append(p.accuracy)
        
        return {
            ptype: {
                "count": len(accs),
                "mean_accuracy": sum(accs) / len(accs),
                "min_accuracy": min(accs),
                "max_accuracy": max(accs),
                "high_accuracy_rate": sum(1 for a in accs if a > 0.8) / len(accs)
            }
            for ptype, accs in by_type.items()
        }

    def get_confidence_vs_accuracy(self) -> list[dict[str, Any]]:
        """Get confidence vs actual accuracy for calibration analysis."""
        calibrated = self.get_calibrated_predictions()
        return [
            {
                "prediction_id": p.prediction_id,
                "confidence": p.confidence,
                "accuracy": p.accuracy,
                "calibration_error": abs(p.confidence - p.accuracy) if p.accuracy is not None else None,
                "type": p.prediction_type
            }
            for p in calibrated if p.accuracy is not None
        ]

    def get_lessons_learned(self, limit: int = 20) -> list[str]:
        """Extract key lessons from prediction history."""
        calibrated = self.get_calibrated_predictions()
        all_lessons = []
        for p in calibrated:
            all_lessons.extend(p.lessons_learned)
        
        # Count frequency
        lesson_counts = defaultdict(int)
        for lesson in all_lessons:
            lesson_counts[lesson] += 1
        
        sorted_lessons = sorted(lesson_counts.items(), key=lambda x: -x[1])
        return [lesson for lesson, count in sorted_lessons[:limit]]

    def find_similar_predictions(
        self,
        query: str,
        prediction_type: str | None = None,
        limit: int = 10
    ) -> list[PredictionRecord]:
        """Find historically similar predictions (simple text matching)."""
        query_lower = query.lower()
        candidates = self._predictions.values()
        if prediction_type:
            candidates = [p for p in candidates if p.prediction_type == prediction_type]
        
        scored = []
        for p in candidates:
            score = 0
            # Match query terms
            for term in query_lower.split():
                if term in p.query.lower():
                    score += 2
                if term in p.reasoning.lower():
                    score += 1
            # Match tags
            for tag in p.tags:
                if tag.lower() in query_lower:
                    score += 3
            if score > 0:
                scored.append((score, p))
        
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:limit]]

    # ── Clustering ────────────────────────────────────────────────

    def cluster_predictions(self, min_cluster_size: int = 3) -> list[PredictionCluster]:
        """Cluster predictions by common tags/themes."""
        # Group by tags
        tag_groups = defaultdict(list)
        for p in self._predictions.values():
            for tag in p.tags:
                tag_groups[tag].append(p.prediction_id)
        
        clusters = []
        for tag, pred_ids in tag_groups.items():
            if len(pred_ids) >= min_cluster_size:
                calibrated_in_cluster = [self._predictions[pid] for pid in pred_ids if self._predictions[pid].calibrated]
                if calibrated_in_cluster:
                    accuracies = [p.accuracy for p in calibrated_in_cluster if p.accuracy is not None]
                    confidences = [p.confidence for p in calibrated_in_cluster]
                    
                    cluster = PredictionCluster(
                        cluster_id=f"cluster_{uuid.uuid4().hex[:8]}",
                        theme=tag,
                        prediction_ids=pred_ids,
                        common_factors=[tag],
                        success_rate=sum(1 for a in accuracies if a > 0.7) / len(accuracies) if accuracies else 0,
                        avg_confidence=sum(confidences) / len(confidences) if confidences else 0
                    )
                    clusters.append(cluster)
                    self._clusters[cluster.cluster_id] = cluster
        
        self._clusters_file.write_text(
            json.dumps({k: asdict(v) for k, v in self._clusters.items()}, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        return clusters

    # ── Reporting ─────────────────────────────────────────────────

    def generate_performance_report(self) -> dict[str, Any]:
        """Generate comprehensive prediction performance report."""
        calibrated = self.get_calibrated_predictions()
        total = len(self._predictions)
        calibrated_count = len(calibrated)
        
        if calibrated_count == 0:
            return {
                "total_predictions": total,
                "calibrated": 0,
                "calibration_rate": 0,
                "message": "No calibrated predictions yet"
            }
        
        accuracies = [p.accuracy for p in calibrated if p.accuracy is not None]
        
        return {
            "total_predictions": total,
            "calibrated": calibrated_count,
            "calibration_rate": calibrated_count / total,
            "overall_accuracy": {
                "mean": sum(accuracies) / len(accuracies) if accuracies else 0,
                "median": sorted(accuracies)[len(accuracies)//2] if accuracies else 0,
                "high_accuracy_rate": sum(1 for a in accuracies if a > 0.8) / len(accuracies) if accuracies else 0,
                "low_accuracy_rate": sum(1 for a in accuracies if a < 0.4) / len(accuracies) if accuracies else 0,
            },
            "by_type": self.get_accuracy_by_type(),
            "confidence_calibration": self.get_confidence_vs_accuracy(),
            "top_lessons": self.get_lessons_learned(10),
            "recent_predictions": len(self.get_recent_predictions(20)),
            "clusters": len(self._clusters)
        }


class OutcomeTracker:
    """Tracks outcomes of decisions/actions based on predictions."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "prediction" / "outcomes"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._outcomes_file = self._dir / "outcomes.jsonl"
        self._outcomes: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            if self._outcomes_file.exists():
                for line in self._outcomes_file.read_text(encoding="utf-8").strip().splitlines():
                    if line.strip():
                        self._outcomes.append(json.loads(line))
        except Exception as e:
            logger.warning("Failed to load outcomes: %s", e)

    def record_outcome(
        self,
        prediction_id: str,
        action_taken: str,
        expected_outcome: str,
        actual_outcome: str,
        success: bool,
        metadata: dict[str, Any] | None = None
    ) -> str:
        """Record the outcome of an action taken based on a prediction."""
        outcome_id = f"outcome_{uuid.uuid4().hex[:8]}"
        record = {
            "outcome_id": outcome_id,
            "prediction_id": prediction_id,
            "action_taken": action_taken,
            "expected_outcome": expected_outcome,
            "actual_outcome": actual_outcome,
            "success": success,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._outcomes.append(record)
        
        with open(self._outcomes_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        
        return outcome_id

    def get_outcomes_for_prediction(self, prediction_id: str) -> list[dict[str, Any]]:
        return [o for o in self._outcomes if o["prediction_id"] == prediction_id]

    def get_success_rate(self, prediction_type: str | None = None) -> float:
        if not self._outcomes:
            return 0.0
        relevant = self._outcomes
        if prediction_type:
            # Would need to join with predictions to filter by type
            pass
        return sum(1 for o in relevant if o["success"]) / len(relevant)