"""Self-improvement loop — verifies corrections are actually applied.

When the system stores a correction (Phase 8), this module:
1. Generates a probe question from the correction's topic
2. Runs it through a lightweight LLM call
3. Checks the response contains the corrected claim but not the wrong one
4. Tracks pass/fail stats and can trigger re-learning on failures

Architecture:
    CorrectionVerifier  — generates probes, checks responses, persistence
    SelfImprovementLoop — orchestrates verify-on-store, batch runs, stats
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VERIFICATION_PROMPT = """You are a verification engine. A user asked: "{probe}"

The correct answer should include: "{expected}"

The wrong answer (to avoid) is: "{wrong}"

Does the following response contain the CORRECT information and AVOID the wrong information?

Response: "{response}"

Reply with ONLY valid JSON:
{{"pass": true, "reason": "brief explanation"}}
or
{{"pass": false, "reason": "what went wrong"}}
"""

PROBE_TEMPLATES: dict[str, str] = {
    "correction": "What is the correct information about {topic}?",
    "fact": "Can you tell me about {topic}?",
    "general": "I'd like to know more about {topic}.",
}


@dataclass
class VerificationResult:
    correction_id: int
    probe: str
    response: str
    passed: bool
    reason: str
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())


class CorrectionVerifier:
    """Generates probe questions and checks responses for correctness.

    Uses an LLM call to evaluate whether a response contains the corrected
    information and avoids the old wrong information.
    """

    def __init__(self, db_path: str | Path = "workspace/memory/verification.db") -> None:
        """Initialize the verifier with a SQLite-backed store.

        Args:
            db_path: Path to the verification database.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                correction_id INTEGER NOT NULL,
                probe TEXT NOT NULL,
                response TEXT NOT NULL DEFAULT '',
                passed INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_verif_correction ON verifications(correction_id);
            CREATE INDEX IF NOT EXISTS idx_verif_passed ON verifications(passed);
        """)

    def generate_probe(self, topic: str, type_: str = "correction") -> str:
        """Generate a probe question from a correction's topic."""
        template = PROBE_TEMPLATES.get(type_, PROBE_TEMPLATES["general"])
        return template.format(topic=topic or "this")

    async def verify(
        self,
        correction: dict[str, Any],
        provider: Any | None = None,
    ) -> VerificationResult:
        """Run verification for a single correction.

        Args:
            correction: dict with at least 'topic', 'content' (corrected_claim),
                       and metadata.wrong_segment keys.
            provider: Optional LLM provider. Uses default if None.

        Returns:
            VerificationResult with pass/fail and reason.
        """
        topic = correction.get("topic", "")
        corrected_claim = correction.get("content", "")
        metadata = correction.get("metadata", {})
        wrong_segment = metadata.get("wrong_segment", "") if isinstance(metadata, dict) else ""

        if not corrected_claim:
            return VerificationResult(
                correction_id=correction.get("id", 0),
                probe="",
                response="",
                passed=False,
                reason="No corrected claim to verify",
            )

        probe = self.generate_probe(topic)

        # Get an LLM response to the probe
        from app.core.model_router import AutoModelRouter

        model = AutoModelRouter.get_best_model("quick")
        try:
            provider_instance = provider or model.get("provider")
            if not provider_instance:
                from app.core.model_router import ModelRouter

                router = ModelRouter()
                response_text = router.resolve(probe)
                if not response_text:
                    response_text = f"I don't have enough information about {topic}."
            else:
                resp = await provider_instance.chat_completion_resilient(
                    messages=[{"role": "user", "content": probe}],
                    preferred_models=[model.get("model", "gpt-4o-mini")],
                )
                response_text = resp.get("content", "") if resp else ""
        except Exception:
            response_text = ""

        if not response_text:
            return VerificationResult(
                correction_id=correction.get("id", 0),
                probe=probe,
                response="",
                passed=False,
                reason="Failed to get LLM response",
            )

        # Check the response contains the corrected claim and avoids the wrong segment
        passed, reason = await self._evaluate_response(
            probe=probe,
            response=response_text,
            expected=corrected_claim,
            wrong=wrong_segment,
            provider=provider,
        )

        result = VerificationResult(
            correction_id=correction.get("id", 0),
            probe=probe,
            response=response_text[:500],
            passed=passed,
            reason=reason,
        )

        self._save(result)
        return result

    async def _evaluate_response(
        self,
        probe: str,
        response: str,
        expected: str,
        wrong: str,
        provider: Any | None = None,
    ) -> tuple[bool, str]:
        """Use an LLM to evaluate if the response is correct."""
        if not wrong:
            # Simple check: does response contain the expected info?
            contains_expected = expected.lower() in response.lower()
            return (
                contains_expected,
                "present in response" if contains_expected else "missing expected info",
            )

        prompt = VERIFICATION_PROMPT.format(
            probe=probe,
            expected=expected,
            wrong=wrong,
            response=response,
        )

        try:
            if provider and hasattr(provider, "chat_completion_resilient"):
                resp = await provider.chat_completion_resilient(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=300,
                )
                text = resp.get("content", "") if isinstance(resp, dict) else ""
            else:
                from app.core.model_router import ModelRouter

                router = ModelRouter()
                text = router.resolve(prompt)

            if text:
                text = text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                data = json.loads(text)
                return (bool(data.get("pass", False)), data.get("reason", ""))
        except Exception as e:
            logger.debug("Verification evaluation failed: %s", e)

        # Fallback: heuristic check
        has_expected = expected.lower() in response.lower()
        has_wrong = wrong.lower() in response.lower() if wrong else False
        if has_expected and not has_wrong:
            return (True, "heuristic: expected present, wrong absent")
        elif has_wrong:
            return (False, f"heuristic: still contains wrong info: {wrong[:80]}")
        elif not has_expected:
            return (False, f"heuristic: missing expected info: {expected[:80]}")
        return (False, "heuristic: ambiguous")

    def _save(self, result: VerificationResult) -> int:
        """Persist a verification result to the database.

        Args:
            result: The verification result to save.

        Returns:
            The new row ID.
        """
        cur = self._conn.execute(
            "INSERT INTO verifications (correction_id, probe, response, passed, reason) VALUES (?, ?, ?, ?, ?)",
            (
                result.correction_id,
                result.probe,
                result.response,
                1 if result.passed else 0,
                result.reason,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate verification statistics.

        Returns:
            Dict with total, passed, failed counts, pass rate, and recent results.
        """
        total = self._conn.execute("SELECT COUNT(*) FROM verifications").fetchone()[0]
        passed = self._conn.execute(
            "SELECT COUNT(*) FROM verifications WHERE passed = 1"
        ).fetchone()[0]
        failed = total - passed
        recent = self._conn.execute(
            "SELECT * FROM verifications ORDER BY created_at DESC LIMIT 20",
        ).fetchall()
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": (passed / max(total, 1)),
            "recent": [dict(r) for r in recent],
        }

    def get_failed(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get failed verifications for review.

        Args:
            limit: Max results.

        Returns:
            List of failed verification rows.
        """
        rows = self._conn.execute(
            "SELECT * FROM verifications WHERE passed = 0 ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_for_correction(self, correction_id: int) -> list[dict[str, Any]]:
        """Get all verifications for a specific correction.

        Args:
            correction_id: The correction ID.

        Returns:
            List of verification rows ordered by creation time DESC.
        """
        rows = self._conn.execute(
            "SELECT * FROM verifications WHERE correction_id = ? ORDER BY created_at DESC",
            (correction_id,),
        ).fetchall()
        return [dict(r) for r in rows]


class SelfImprovementLoop:
    """Orchestrates the full verify-on-store and batch verification cycle."""

    def __init__(
        self,
        verifier: CorrectionVerifier | None = None,
    ) -> None:
        """Initialize the self-improvement loop.

        Args:
            verifier: Optional shared verifier instance. Creates a new one if None.
        """
        self._verifier = verifier or CorrectionVerifier()

    async def on_correction_stored(self, correction_id: int) -> VerificationResult | None:
        """Called after a correction is stored — verify it immediately."""
        try:
            from app.core.learning_db import get_learning_store

            store = get_learning_store()
            correction = store.get(correction_id)
            if not correction:
                logger.debug("Correction %d not found for verification", correction_id)
                return None
            result = await self._verifier.verify(correction)
            if not result.passed:
                logger.info(
                    "Verification FAILED for correction %d: %s",
                    correction_id,
                    result.reason,
                )
            return result
        except Exception as e:
            logger.debug("Self-improvement on_correction_stored failed: %s", e)
            return None

    async def run_batch(self, limit: int = 20) -> list[VerificationResult]:
        """Verify all unverified corrections from the learning store."""
        from app.core.learning_db import get_learning_store

        store = get_learning_store()
        corrections = store.get_recent(type_="correction", limit=limit, min_confidence=0.0)

        results: list[VerificationResult] = []
        for corr in corrections:
            corr_id = corr.get("id", 0)
            if not corr_id:
                continue
            existing = self._verifier.get_for_correction(corr_id)
            if existing:
                continue  # already verified
            result = await self._verifier.verify(corr)
            results.append(result)

        return results

    def get_stats(self) -> dict[str, Any]:
        """Return verification stats from the underlying verifier."""
        return self._verifier.get_stats()


# Singleton
_verifier: CorrectionVerifier | None = None
_loop: SelfImprovementLoop | None = None


def get_verifier() -> CorrectionVerifier:
    """Return the singleton CorrectionVerifier instance."""
    global _verifier
    if _verifier is None:
        _verifier = CorrectionVerifier()
    return _verifier


def get_self_improvement_loop() -> SelfImprovementLoop:
    """Return the singleton SelfImprovementLoop instance."""
    global _loop
    if _loop is None:
        _loop = SelfImprovementLoop()
    return _loop
