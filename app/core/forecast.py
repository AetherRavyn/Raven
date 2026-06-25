import json
import logging
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.provider.factory import create_provider
from app.settings.config import Config
from app.core.model_router import AutoModelRouter
from app.core.task_ledger import TaskLedger
from app.core.workspace_graph import WorkspaceGraph

logger = logging.getLogger(__name__)


# ── Simple Time-Series Statistics ──────────────────────────────────────

class SimpleTimeSeries:
    """Lightweight time-series analysis without external ML libraries.

    Provides:
    - Moving average + trend detection
    - Simple anomaly detection (z-score)
    - Linear regression forecast
    """

    @staticmethod
    def moving_average(data: List[float], window: int = 5) -> List[float]:
        """Compute simple moving average."""
        if len(data) < window:
            return data
        result = []
        for i in range(len(data) - window + 1):
            result.append(sum(data[i:i + window]) / window)
        return result

    @staticmethod
    def trend(data: List[float]) -> Dict[str, Any]:
        """Detect trend direction and strength using linear regression."""
        n = len(data)
        if n < 3:
            return {"direction": "insufficient_data", "slope": 0, "confidence": 0}

        x_mean = (n - 1) / 2
        y_mean = sum(data) / n

        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(data))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        slope = numerator / denominator if denominator != 0 else 0

        # R² computation
        y_pred = [slope * i + (y_mean - slope * x_mean) for i in range(n)]
        ss_res = sum((y - yp) ** 2 for y, yp in zip(data, y_pred))
        ss_tot = sum((y - y_mean) ** 2 for y in data)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

        if abs(slope) < 0.01:
            direction = "stable"
        elif slope > 0:
            direction = "increasing"
        else:
            direction = "decreasing"

        return {
            "direction": direction,
            "slope": round(slope, 4),
            "r_squared": round(max(0, r_squared), 4),
            "confidence": round(max(0, r_squared), 2),
        }

    @staticmethod
    def forecast_next(data: List[float], steps: int = 3) -> List[float]:
        """Extrapolate next N values using linear regression."""
        n = len(data)
        if n < 2:
            return [data[-1]] * steps if data else [0] * steps

        x_mean = (n - 1) / 2
        y_mean = sum(data) / n
        num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(data))
        den = sum((i - x_mean) ** 2 for i in range(n))
        slope = num / den if den else 0
        intercept = y_mean - slope * x_mean

        return [round(slope * (n + i) + intercept, 2) for i in range(steps)]

    @staticmethod
    def detect_anomalies(data: List[float], threshold: float = 2.0) -> List[Dict]:
        """Detect anomalies via z-score method."""
        if len(data) < 5:
            return []

        mean = sum(data) / len(data)
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std = math.sqrt(variance) if variance > 0 else 1.0

        anomalies = []
        for i, value in enumerate(data):
            z = abs(value - mean) / std
            if z > threshold:
                anomalies.append({
                    "index": i,
                    "value": value,
                    "z_score": round(z, 2),
                    "direction": "spike" if value > mean else "dip",
                })
        return anomalies


# ── System Metrics Collector ───────────────────────────────────────────

class MetricsCollector:
    """Collects and stores system metrics over time for trend analysis."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        base = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        self._dir = base / "metrics"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _metrics_file(self, metric_name: str) -> Path:
        return self._dir / f"{metric_name}.jsonl"

    def record(self, metric_name: str, value: float, metadata: Dict | None = None) -> None:
        """Append a timestamped metric data point."""
        entry = {
            "t": datetime.now(timezone.utc).isoformat(),
            "v": value,
        }
        if metadata:
            entry["m"] = metadata
        try:
            with open(self._metrics_file(metric_name), "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def get_series(self, metric_name: str, last_n: int = 100) -> List[float]:
        """Load the last N data points for a metric."""
        path = self._metrics_file(metric_name)
        if not path.exists():
            return []
        try:
            lines = path.read_text().strip().splitlines()
            recent = lines[-last_n:] if len(lines) > last_n else lines
            return [json.loads(line)["v"] for line in recent]
        except Exception:
            return []

    def snapshot_system(self) -> Dict[str, float]:
        """Take a snapshot of current system metrics and record them."""
        stats: Dict[str, float] = {}
        try:
            import psutil
            stats["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            stats["memory_percent"] = mem.percent
            disk = psutil.disk_usage("/")
            stats["disk_percent"] = disk.percent
        except ImportError:
            pass

        for name, value in stats.items():
            self.record(name, value)
        return stats


# ── Enhanced Forecast Engine ───────────────────────────────────────────

class ForecastEngine:
    """Hybrid prediction engine — real statistics + LLM interpretation.

    Level 1: Pure statistical analysis (trend, anomaly, regression)
    Level 2: LLM-augmented scenario generation enriched with statistical findings
    """

    def __init__(self, workspace_dir: str | None = None):
        self.workspace_dir = workspace_dir if workspace_dir else Config.MEMORY_ROOT
        self.ledger = TaskLedger(self.workspace_dir)
        self.graph = WorkspaceGraph(self.workspace_dir)
        self.ts = SimpleTimeSeries()
        self.metrics = MetricsCollector(self.workspace_dir)
        try:
            provider_name, self.model_name = AutoModelRouter.get_best_model("agent")
            self.provider = create_provider(provider_name)
        except Exception:
            self.provider = None
            self.model_name = ""

    def _get_system_stats(self) -> dict[str, Any]:
        """Get current system stats and record to time-series."""
        return self.metrics.snapshot_system()

    # ── Level 1: Statistical Forecasts ─────────────────────────────────

    def generate_statistical_forecasts(self) -> List[Dict[str, Any]]:
        """Generate forecasts purely from statistical analysis — no LLM needed."""
        forecasts = []

        for metric in ["cpu_percent", "memory_percent", "disk_percent"]:
            series = self.metrics.get_series(metric, last_n=60)
            if len(series) < 5:
                continue

            trend = self.ts.trend(series)
            anomalies = self.ts.detect_anomalies(series)
            predicted = self.ts.forecast_next(series, steps=5)

            # Generate alerts based on statistical analysis
            label = metric.replace("_percent", "").upper()

            # Trend-based forecast
            if trend["direction"] == "increasing" and trend["confidence"] > 0.5:
                will_exceed = any(p > 90 for p in predicted)
                forecasts.append({
                    "scenario": f"{label} usage trending upward",
                    "probability": round(min(0.95, trend["confidence"] + 0.1), 2),
                    "impact": "High" if will_exceed else "Medium",
                    "timeframe": "Next 1-2 hours",
                    "rationale": (
                        f"{label} has been {trend['direction']} (slope={trend['slope']}, "
                        f"R²={trend['r_squared']}). "
                        f"Predicted next values: {predicted[:3]}"
                    ),
                    "source": "statistical",
                    "stakeholders": [
                        {"role": "System", "impact": f"{label} approaching capacity"},
                    ],
                    "mitigation_action": f"Monitor {label} and consider freeing resources.",
                })

            # Anomaly-based alerts
            if anomalies:
                latest_anomaly = anomalies[-1]
                forecasts.append({
                    "scenario": f"{label} anomaly detected ({latest_anomaly['direction']})",
                    "probability": round(min(0.9, latest_anomaly["z_score"] / 3), 2),
                    "impact": "High" if latest_anomaly["z_score"] > 3 else "Medium",
                    "timeframe": "Recent",
                    "rationale": (
                        f"Anomalous {label} value: {latest_anomaly['value']} "
                        f"(z-score: {latest_anomaly['z_score']})"
                    ),
                    "source": "statistical",
                    "stakeholders": [
                        {"role": "System", "impact": f"Unusual {label} behavior"},
                    ],
                    "mitigation_action": f"Investigate the {label} {latest_anomaly['direction']}.",
                })

        return forecasts

    # ── Level 2: LLM-Augmented Forecasts ──────────────────────────────

    def _get_recent_context(self, user_id: str) -> dict[str, Any]:
        """Aggregate signals for forecasting."""
        context = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system_stats": self._get_system_stats(),
            "statistical_findings": self.generate_statistical_forecasts(),
            "open_tasks": [],
            "recent_graph_nodes": [],
            "internet_evidence": [],
        }

        # Open Tasks
        all_open = self.ledger.list_tasks(status="open")
        for t in all_open:
            if t.get("task_type") in ("task", "approval"):
                context["open_tasks"].append({
                    "id": t["task_id"],
                    "title": t.get("title", ""),
                    "type": t.get("task_type", ""),
                    "risk": t.get("metadata", {}).get("risk_level", "Low"),
                })

        # Graph Nodes
        try:
            graph_data = self.graph.build_for_user(user_id)
            nodes = graph_data.get("nodes", [])
            context["recent_graph_nodes"] = [
                {"name": n["name"], "kind": n["kind"]} for n in nodes[:20]
            ]
        except Exception as e:
            logger.warning("Forecast graph extraction failed: %s", e)

        # Internet Evidence
        evidence_file = os.path.join(self.workspace_dir, "evidence.jsonl")
        if os.path.exists(evidence_file):
            try:
                with open(evidence_file, "r") as f:
                    lines = f.readlines()
                    for line in lines[-10:]:
                        try:
                            ev = json.loads(line)
                            context["internet_evidence"].append({
                                "topic": ev.get("topic_id"),
                                "claim": ev.get("claims", [""])[0],
                                "sentiment": ev.get("sentiment"),
                                "source": ev.get("source_url"),
                            })
                        except Exception:
                            pass
            except Exception as e:
                logger.warning("Failed to load internet evidence: %s", e)

        return context

    async def generate_forecasts(self, user_id: str) -> list[dict[str, Any]]:
        """Generate hybrid forecasts: statistical first, then LLM-enriched."""
        # Always start with statistical forecasts (no LLM needed)
        statistical = self.generate_statistical_forecasts()

        # If no LLM available, return statistical results only
        if not self.provider:
            logger.info("Forecast: returning %d statistical-only forecasts", len(statistical))
            return statistical

        context = self._get_recent_context(user_id)

        prompt = f"""You are a predictive intelligence engine.
You have access to both statistical analysis results AND contextual data.

IMPORTANT: The statistical findings below are from REAL data analysis (trend detection, anomaly detection, linear regression). Use them as your primary evidence. Do NOT hallucinate statistics.

Input Context:
{json.dumps(context, indent=2)}

Generate 1 to 3 additional near-term scenarios or risks that the statistical analysis may have missed. Focus on:
1. Cross-signal patterns (e.g., high CPU + many open tasks = bottleneck risk)
2. User workflow risks (overdue tasks, blocked goals)
3. External dependency risks

Output exactly valid JSON array, and nothing else:
[
  {{
    "scenario": "Short title",
    "probability": 0.85,
    "impact": "High",
    "timeframe": "Next 24 hours",
    "rationale": "Clear reason grounded in the data above.",
    "source": "hybrid",
    "stakeholders": [
      {{ "role": "User", "impact": "..." }}
    ],
    "mitigation_action": "Concrete suggestion."
  }}
]"""

        try:
            resilient = getattr(self.provider, "chat_completion_resilient", None)
            if resilient:
                result = await resilient(
                    messages=[{"role": "user", "content": prompt}],
                    preferred_models=[
                        "big-pickle",
                        "deepseek-v4-flash-free",
                    ],
                    free_only_guard=True,
                )
            else:
                result = await self.provider.chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.model_name or "big-pickle",
                )

            if not result.get("success"):
                logger.warning("Forecast LLM failed: %s", result.get("error"))
                return statistical

            content = result.get("content", "").strip()
            if content.startswith("```json"):
                content = content[7:-3].strip()
            elif content.startswith("```"):
                content = content[3:-3].strip()

            llm_forecasts = json.loads(content)
            if isinstance(llm_forecasts, list):
                return statistical + llm_forecasts

        except Exception as e:
            logger.error("Forecast LLM error: %s", e)

        return statistical

    async def run_cycle(self, user_id: str) -> None:
        """Run the forecasting cycle and save to ledger."""
        logger.info("Running forecast cycle for user %s...", user_id)

        # Always record current metrics
        self._get_system_stats()

        new_forecasts = await self.generate_forecasts(user_id)

        if not new_forecasts:
            logger.info("No forecasts generated.")
            return

        # Clear old forecasts from ledger
        all_tasks = self.ledger.list_tasks(status="open")
        for t in all_tasks:
            if t.get("task_type") == "forecast" and t.get("user_id") == user_id:
                self.ledger.update_status(t["task_id"], "superseded")

        # Insert new forecasts
        import uuid
        for fc in new_forecasts:
            task_id = f"fc_{uuid.uuid4().hex[:8]}"
            self.ledger.add_task(
                task_id=task_id,
                task_type="forecast",
                title=fc.get("scenario", "Unknown Scenario"),
                user_id=user_id,
                metadata={
                    "probability": fc.get("probability", 0.5),
                    "impact": fc.get("impact", "Medium"),
                    "timeframe": fc.get("timeframe", "Unknown"),
                    "rationale": fc.get("rationale", ""),
                    "stakeholders": fc.get("stakeholders", []),
                    "mitigation_action": fc.get("mitigation_action", ""),
                    "source": fc.get("source", "hybrid"),
                },
            )
        logger.info(
            "Saved %d forecasts (%d statistical, rest LLM-augmented)",
            len(new_forecasts),
            sum(1 for f in new_forecasts if f.get("source") == "statistical"),
        )
