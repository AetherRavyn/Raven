"""Curator — Data curation pipeline for training-quality datasets.

Extracts conversations and learnings from Raven's stores, cleans them
(dedup, PII redaction), enriches with quality scores and domain tags,
and exports in standard formats (JSONL, ShareGPT, Alpaca, ChatML).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── PII Redaction Patterns ───────────────────────────────────────────

_PII_PATTERNS: list[tuple[str, str]] = [
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL]"),
    (r"\b\+?[\d\-\(\)]{7,15}\b", "[PHONE]"),
    (r"[A-Za-z0-9_-]{20,}", "[API_KEY]"),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP_ADDRESS]"),
]

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "coding": [
        "code",
        "function",
        "bug",
        "debug",
        "implement",
        "api",
        "script",
        "python",
        "javascript",
    ],
    "research": ["research", "paper", "study", "findings", "literature", "analyze", "investigate"],
    "writing": ["write", "essay", "draft", "edit", "rewrite", "compose", "story", "article"],
    "general": ["help", "question", "explain", "what", "how", "why", "tell", "describe"],
    "planning": ["plan", "schedule", "organize", "strategy", "timeline", "milestone", "goal"],
    "data": ["data", "dataset", "analysis", "statistics", "visualization", "chart", "metrics"],
}


@dataclass
class CurationConfig:
    """Configuration for the curation pipeline."""

    export_dir: str = "workspace/curated"
    min_confidence: float = 0.7
    dedup_threshold: float = 0.95
    pii_redact: bool = True
    max_samples: int = 10000
    formats: list[str] = field(default_factory=lambda: ["jsonl"])


@dataclass
class CuratedSample:
    """A single curated training sample."""

    id: str
    instruction: str
    response: str
    source: str
    domain: str
    tools_used: list[str] = field(default_factory=list)
    agent_used: str = ""
    confidence: float = 0.0
    quality_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CurationStats:
    """Aggregate statistics from a curation pipeline run."""

    total_samples: int = 0
    after_dedup: int = 0
    after_filter: int = 0
    by_domain: dict[str, int] = field(default_factory=dict)
    by_agent: dict[str, int] = field(default_factory=dict)
    avg_quality: float = 0.0
    pii_redacted: int = 0


class ExportFormat(str, Enum):
    JSONL = "jsonl"
    SHAREGPT = "sharegpt"
    ALPACA = "alpaca"
    CHATML = "chatml"


class Curator:
    """End-to-end data curation pipeline.

    Extraction → Cleaning (dedup, PII) → Enrichment (domain, quality) → Export.
    """

    def __init__(
        self,
        config: CurationConfig | None = None,
        learning_store=None,
        memory_manager=None,
        session_manager=None,
    ) -> None:
        self.config = config or CurationConfig()
        self._export_dir = Path(self.config.export_dir)
        self._export_dir.mkdir(parents=True, exist_ok=True)

        self._learning_store = learning_store
        self._memory_manager = memory_manager
        self._session_manager = session_manager

        self._stats = CurationStats()

    # ── Extraction ───────────────────────────────────────────────────

    async def extract_conversations(self, limit: int = 1000) -> list[CuratedSample]:
        """Extract curated samples from conversation sessions."""
        samples: list[CuratedSample] = []

        if self._session_manager is None:
            logger.warning("No session_manager provided; returning empty extraction")
            return samples

        try:
            # Load recent sessions
            sessions = getattr(self._session_manager, "list_sessions", None)
            if sessions is not None:
                session_ids = sessions()[:limit]
            else:
                session_ids = []

            for sid in session_ids:
                messages = self._session_manager.load_session(sid)
                for i, msg in enumerate(messages):
                    if msg.get("role") != "user":
                        continue
                    if i + 1 < len(messages) and messages[i + 1].get("role") == "assistant":
                        instruction = msg.get("content", "")
                        response = messages[i + 1].get("content", "")
                        if instruction and response and len(response) > 10:
                            samples.append(
                                CuratedSample(
                                    id=hashlib.sha256(f"{sid}:{i}".encode()).hexdigest()[:12],
                                    instruction=instruction,
                                    response=response,
                                    source="conversation",
                                    domain=self._classify_domain(instruction + " " + response),
                                    agent_used=msg.get("agent", ""),
                                    confidence=0.8,
                                )
                            )

            logger.info("Extracted %d conversation samples", len(samples))
        except Exception as exc:
            logger.warning("Conversation extraction failed: %s", exc)

        return samples

    async def extract_learnings(self, min_confidence: float = 0.7) -> list[CuratedSample]:
        """Extract curated samples from the learning store."""
        samples: list[CuratedSample] = []

        if self._learning_store is None:
            logger.warning("No learning_store provided; returning empty extraction")
            return samples

        try:
            items = []
            search = getattr(self._learning_store, "search", None)
            if search is not None:
                items = search("") or []
            else:
                items = getattr(self._learning_store, "get_all", lambda: [])()

            for item in items:
                confidence = item.get("confidence", 0.5) if isinstance(item, dict) else 0.5
                if confidence < min_confidence:
                    continue

                content = item.get("content", "") if isinstance(item, dict) else str(item)
                topic = item.get("topic", "") if isinstance(item, dict) else ""
                source = item.get("source", "learning") if isinstance(item, dict) else "learning"

                samples.append(
                    CuratedSample(
                        id=hashlib.sha256(content.encode()).hexdigest()[:12],
                        instruction=topic or "General learning",
                        response=content,
                        source=source,
                        domain=self._classify_domain(content),
                        confidence=confidence,
                    )
                )

            logger.info("Extracted %d learning samples", len(samples))
        except Exception as exc:
            logger.warning("Learning extraction failed: %s", exc)

        return samples

    # ── Cleaning ─────────────────────────────────────────────────────

    async def clean(self, samples: list[CuratedSample]) -> list[CuratedSample]:
        """Deduplicate and redact PII from samples."""
        result = self._dedup(samples)
        result = self._redact_pii(result)
        return result

    def _dedup(self, samples: list[CuratedSample]) -> list[CuratedSample]:
        """Remove exact and fuzzy duplicates."""
        seen_exact: set[str] = set()
        unique: list[CuratedSample] = []

        # Exact dedup
        for sample in samples:
            key = hashlib.sha256((sample.instruction + sample.response).encode()).hexdigest()
            if key not in seen_exact:
                seen_exact.add(key)
                unique.append(sample)

        logger.info("Exact dedup: %d → %d", len(samples), len(unique))

        # Fuzzy dedup
        threshold = self.config.dedup_threshold
        if threshold < 1.0 and len(unique) > 1:
            unique = self._fuzzy_dedup(unique, threshold)

        logger.info("Fuzzy dedup: %d → %d", len(samples), len(unique))
        return unique

    def _fuzzy_dedup(
        self,
        samples: list[CuratedSample],
        threshold: float,
    ) -> list[CuratedSample]:
        """Remove near-duplicate samples using embedding or text overlap."""
        # Try embedding-based dedup first
        try:
            return self._embedding_dedup(samples, threshold)
        except Exception:
            pass

        # Fallback: n-gram overlap
        return self._ngram_dedup(samples, threshold)

    def _embedding_dedup(
        self,
        samples: list[CuratedSample],
        threshold: float,
    ) -> list[CuratedSample]:
        """Use sentence-transformers embeddings for fuzzy dedup."""
        from sentence_transformers import SentenceTransformer
        import numpy as np

        model = SentenceTransformer("all-MiniLM-L6-v2")
        texts = [f"{s.instruction} {s.response}" for s in samples]
        embeddings = model.encode(texts, normalize_embeddings=True)

        keep = [True] * len(samples)
        for i in range(len(samples)):
            if not keep[i]:
                continue
            for j in range(i + 1, len(samples)):
                if not keep[j]:
                    continue
                sim = float(np.dot(embeddings[i], embeddings[j]))
                if sim >= threshold:
                    keep[j] = False

        result = [s for i, s in enumerate(samples) if keep[i]]
        return result

    def _ngram_dedup(
        self,
        samples: list[CuratedSample],
        threshold: float,
    ) -> list[CuratedSample]:
        """Fallback fuzzy dedup using word n-gram Jaccard similarity."""
        keep = [True] * len(samples)
        for i in range(len(samples)):
            if not keep[i]:
                continue
            tokens_i = set(self._tokenize(samples[i]))
            for j in range(i + 1, len(samples)):
                if not keep[j]:
                    continue
                tokens_j = set(self._tokenize(samples[j]))
                intersection = tokens_i & tokens_j
                union = tokens_i | tokens_j
                sim = len(intersection) / len(union) if union else 0.0
                if sim >= threshold:
                    keep[j] = False

        return [s for i, s in enumerate(samples) if keep[i]]

    @staticmethod
    def _tokenize(sample: CuratedSample) -> list[str]:
        """Tokenize a sample into lowercase n-gram tokens."""
        text = f"{sample.instruction} {sample.response}".lower()
        words = re.findall(r"\b\w{3,}\b", text)
        # Generate character trigrams for robust matching
        grams: list[str] = []
        for w in words:
            if len(w) >= 3:
                for k in range(len(w) - 2):
                    grams.append(w[k : k + 3])
        return grams if grams else words

    def _redact_pii(self, samples: list[CuratedSample]) -> list[CuratedSample]:
        """Redact personally identifiable information from samples."""
        if not self.config.pii_redact:
            return samples

        total_redactions = 0
        for sample in samples:
            for pattern, replacement in _PII_PATTERNS:
                before = sample.instruction
                sample.instruction = re.sub(pattern, replacement, sample.instruction)
                total_redactions += 1 if sample.instruction != before else 0

                before = sample.response
                sample.response = re.sub(pattern, replacement, sample.response)
                total_redactions += 1 if sample.response != before else 0

        self._stats.pii_redacted = total_redactions
        logger.info("PII redaction: %d occurrences replaced", total_redactions)
        return samples

    # ── Enrichment ───────────────────────────────────────────────────

    async def enrich(self, samples: list[CuratedSample]) -> list[CuratedSample]:
        """Add domain tags, quality scores, and tool usage metadata."""
        for sample in samples:
            sample.domain = self._classify_domain(sample.instruction + " " + sample.response)
            sample.quality_score = self._compute_quality(sample)

        logger.info("Enriched %d samples with domain tags and quality scores", len(samples))
        return samples

    @staticmethod
    def _classify_domain(text: str) -> str:
        """Classify text into a domain based on keyword matching."""
        text_lower = text.lower()
        scores: dict[str, int] = {}
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            scores[domain] = sum(1 for kw in keywords if kw in text_lower)

        if not scores or all(v == 0 for v in scores.values()):
            return "general"

        return max(scores, key=scores.get)

    @staticmethod
    def _compute_quality(sample: CuratedSample) -> float:
        """Compute quality score (0.0–1.0) for a sample."""
        score = 0.0

        # Response length: penalize too short or too long
        resp_len = len(sample.response)
        if 50 <= resp_len <= 2000:
            score += 0.3
        elif 20 <= resp_len < 50:
            score += 0.15
        elif resp_len > 2000:
            score += 0.2
        else:
            score += 0.05

        # Instruction is meaningful
        if len(sample.instruction) >= 10:
            score += 0.15
        else:
            score += 0.05

        # Tool usage: more tools = higher quality signal
        tool_bonus = min(0.2, len(sample.tools_used) * 0.05)
        score += tool_bonus

        # Confidence component
        score += sample.confidence * 0.2

        # Metadata boost (e.g., user feedback)
        feedback = sample.metadata.get("feedback_score", 0) if sample.metadata else 0
        score += feedback * 0.15

        return min(1.0, round(score, 4))

    # ── Export ───────────────────────────────────────────────────────

    async def export(self, samples: list[CuratedSample], format: str = "jsonl") -> str:
        """Export samples to a file in the specified format.

        Returns the path to the exported file.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        exporters = {
            "jsonl": self._to_jsonl,
            "sharegpt": self._to_sharegpt,
            "alpaca": self._to_alpaca,
            "chatml": self._to_chatml,
        }

        exporter = exporters.get(format)
        if exporter is None:
            msg = f"Unsupported export format: {format}. Supported: {list(exporters)}"
            raise ValueError(msg)

        data = exporter(samples)
        ext = "jsonl" if format == "jsonl" else "json"
        out_path = self._export_dir / f"curated_{timestamp}.{ext}"

        if format == "jsonl":
            out_path.write_text(data, encoding="utf-8")
        else:
            out_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        logger.info("Exported %d samples to %s (format=%s)", len(samples), out_path, format)
        return str(out_path)

    @staticmethod
    def _to_jsonl(samples: list[CuratedSample]) -> str:
        """Convert samples to JSON Lines format."""
        lines: list[str] = []
        for s in samples:
            lines.append(json.dumps(asdict(s), ensure_ascii=False) + "\n")
        return "".join(lines)

    @staticmethod
    def _to_sharegpt(samples: list[CuratedSample]) -> list[dict[str, Any]]:
        """Convert samples to ShareGPT conversation format."""
        output: list[dict[str, Any]] = []
        for s in samples:
            output.append(
                {
                    "conversations": [
                        {"from": "human", "value": s.instruction},
                        {"from": "gpt", "value": s.response},
                    ],
                    "system": "",
                    "tools_used": s.tools_used,
                    "source": s.source,
                    "domain": s.domain,
                    "quality_score": s.quality_score,
                }
            )
        return output

    @staticmethod
    def _to_alpaca(samples: list[CuratedSample]) -> list[dict[str, Any]]:
        """Convert samples to Alpaca instruction format."""
        output: list[dict[str, Any]] = []
        for s in samples:
            output.append(
                {
                    "instruction": s.instruction,
                    "input": "",
                    "output": s.response,
                    "source": s.source,
                    "domain": s.domain,
                }
            )
        return output

    @staticmethod
    def _to_chatml(samples: list[CuratedSample]) -> list[dict[str, Any]]:
        """Convert samples to ChatML conversation format."""
        output: list[dict[str, Any]] = []
        for s in samples:
            output.append(
                {
                    "messages": [
                        {"role": "user", "content": s.instruction},
                        {"role": "assistant", "content": s.response},
                    ],
                    "source": s.source,
                    "domain": s.domain,
                    "quality_score": s.quality_score,
                }
            )
        return output

    # ── Pipeline ─────────────────────────────────────────────────────

    async def run_pipeline(self) -> CurationStats:
        """End-to-end curation: extract → clean → enrich → export."""
        samples: list[CuratedSample] = []

        conv = await self.extract_conversations(limit=self.config.max_samples)
        samples.extend(conv)

        learn = await self.extract_learnings(min_confidence=self.config.min_confidence)
        samples.extend(learn)

        self._stats.total_samples = len(samples)

        if not samples:
            logger.warning("No samples extracted; pipeline complete with empty result")
            return self._stats

        samples = await self.clean(samples)
        self._stats.after_dedup = len(samples)

        samples = await self.enrich(samples)

        # Filter by min confidence
        samples = [s for s in samples if s.confidence >= self.config.min_confidence]
        self._stats.after_filter = len(samples)

        # Cut to max_samples
        samples = samples[: self.config.max_samples]

        # Export in all requested formats
        for fmt in self.config.formats:
            await self.export(samples, format=fmt)

        # Compute stats
        self._stats.avg_quality = (
            round(sum(s.quality_score for s in samples) / len(samples), 4) if samples else 0.0
        )

        by_domain: dict[str, int] = {}
        by_agent: dict[str, int] = {}
        for s in samples:
            by_domain[s.domain] = by_domain.get(s.domain, 0) + 1
            if s.agent_used:
                by_agent[s.agent_used] = by_agent.get(s.agent_used, 0) + 1
        self._stats.by_domain = by_domain
        self._stats.by_agent = by_agent

        logger.info(
            "Pipeline complete: %d total → %d after dedup → %d after filter, avg quality %.3f",
            self._stats.total_samples,
            self._stats.after_dedup,
            self._stats.after_filter,
            self._stats.avg_quality,
        )

        return self._stats

    def get_stats(self) -> CurationStats:
        """Return the current curation statistics."""
        return self._stats
