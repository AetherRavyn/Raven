"""Phase F1 — Trust & Explainability: Explanation export.

Bundles everything the trust module knows about a turn into a
single user-facing report:

  * the final response text
  * every citation attached during the turn
  * every rollback action registered during the turn
  * every audit event for the turn
  * an optional fact-check verdict

The report renders as plain text, Markdown (for chat UIs), or
JSON (for programmatic consumers).  It is the dashboard's
"Why did the agent say that?" view.

Typical usage::

    builder = ExplanationBuilder(
        audit_viewer=audit_viewer,
        rollback_manager=rollback_manager,
        citation_injector=citation_injector,
        fact_checker=fact_checker,
    )
    report = builder.explain_turn(
        turn_id=ctx.turn_id,
        user_id="u1",
        session_id="s1",
        response_text="Acme shipped 3 features[1].",
    )
    markdown = format_explanation_markdown(report)
    # Use it in a /explain slash command, a dashboard panel,
    # or a "Why?" button next to the agent's response.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.core.trust.audit_viewer import AuditEvent, AuditFilter, AuditViewer
from app.core.trust.citation_runtime import CitationContext, CitationInjector
from app.core.trust.citations import Citation, format_sources_list
from app.core.trust.fact_check import FactCheckReport, FactChecker
from app.core.trust.rollback import RollbackAction, RollbackManager, RollbackStatus


class Verdict(str, Enum):
    """Overall trust verdict for a turn."""

    TRUSTED = "trusted"  # all citations verified, no audit failures
    NEEDS_REVIEW = "needs_review"  # some uncertainty (e.g. unsourced claim)
    FAILED = "failed"  # audit failures or unverified rollback
    UNKNOWN = "unknown"  # not enough data to decide


def _enum_value(v: Any) -> str:
    """Coerce an enum or string to its string value."""
    if v is None:
        return ""
    if hasattr(v, "value"):
        return str(v.value)
    return str(v)


@dataclass(slots=True)
class ExplanationReport:
    """Bundled trust data for a single turn.

    All four trust modules contribute to this report.
    Fields with no data default to empty lists — the
    report is always well-formed regardless of which
    modules were active during the turn.
    """

    turn_id: str
    user_id: str
    session_id: str
    response_text: str = ""
    citations: list[Citation] = field(default_factory=list)
    rollback_actions: list[RollbackAction] = field(default_factory=list)
    audit_events: list[AuditEvent] = field(default_factory=list)
    fact_check: FactCheckReport | None = None
    verdict: Verdict = Verdict.UNKNOWN
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
    report_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # -- counts --------------------------------------------------------

    def citation_count(self) -> int:
        return len(self.citations)

    def rollback_count(self) -> int:
        return len(self.rollback_actions)

    def audit_count(self) -> int:
        return len(self.audit_events)

    def has_evidence(self) -> bool:
        """True if the response has at least one citation."""
        return bool(self.citations)

    def has_fact_check(self) -> bool:
        return self.fact_check is not None

    # -- serialization -------------------------------------------------

    def _rollback_to_dict(self, a: RollbackAction) -> dict[str, Any]:
        return {
            "action_id": a.action_id,
            "tool_name": a.tool_name,
            "description": a.description,
            "user_id": a.user_id,
            "args": dict(a.args),
            "timestamp": a.timestamp.isoformat(),
            "undone": a.undone,
            "undone_at": a.undone_at.isoformat() if a.undone_at else None,
            "undo_error": a.undo_error,
            "status": _enum_value(a.status),
            "metadata": dict(a.metadata),
        }

    def _audit_to_dict(self, ev: AuditEvent) -> dict[str, Any]:
        return {
            "id": ev.id,
            "kind": _enum_value(ev.kind),
            "actor": ev.actor,
            "action": ev.action,
            "target": ev.target,
            "success": ev.success,
            "detail": ev.detail,
            "risk_level": _enum_value(ev.risk_level),
            "timestamp": ev.timestamp.isoformat(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "turn_id": self.turn_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "response_text": self.response_text,
            "citations": [
                {
                    "id": c.id,
                    "source": c.source.value,
                    "ref": c.ref,
                    "title": c.title,
                    "snippet": c.snippet,
                    "timestamp": c.timestamp.isoformat(),
                    "metadata": dict(c.metadata),
                }
                for c in self.citations
            ],
            "rollback_actions": [self._rollback_to_dict(a) for a in self.rollback_actions],
            "audit_events": [self._audit_to_dict(ev) for ev in self.audit_events],
            "fact_check": self.fact_check.to_dict() if self.fact_check else None,
            "verdict": self.verdict.value,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# -- builder ---------------------------------------------------------------


class ExplanationBuilder:
    """Orchestrates the four trust modules to produce reports.

    Holds optional references to each module.  Missing
    modules are skipped silently — the report is still
    produced from whatever data is available.
    """

    def __init__(
        self,
        *,
        audit_viewer: AuditViewer | None = None,
        rollback_manager: RollbackManager | None = None,
        citation_injector: CitationInjector | None = None,
        fact_checker: FactChecker | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._audit_viewer = audit_viewer
        self._rollback_manager = rollback_manager
        self._citation_injector = citation_injector
        self._fact_checker = fact_checker

    # -- module setters (for late wiring) -------------------------------

    def set_audit_viewer(self, viewer: AuditViewer | None) -> None:
        with self._lock:
            self._audit_viewer = viewer

    def set_rollback_manager(self, manager: RollbackManager | None) -> None:
        with self._lock:
            self._rollback_manager = manager

    def set_citation_injector(self, injector: CitationInjector | None) -> None:
        with self._lock:
            self._citation_injector = injector

    def set_fact_checker(self, checker: FactChecker | None) -> None:
        with self._lock:
            self._fact_checker = checker

    # -- the main API ---------------------------------------------------

    def explain_turn(
        self,
        turn_id: str,
        *,
        user_id: str = "",
        session_id: str = "",
        response_text: str = "",
        include_audit: bool = True,
        include_rollback: bool = True,
        include_citations: bool = True,
        include_fact_check: bool = True,
        fact_check_evidence_provider: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExplanationReport:
        """Build a report for a single turn.

        Pulls citations from the citation injector, rollbacks
        from the rollback manager (filtered by turn_id in
        metadata), and audit events from the audit viewer
        (filtered by session_id/turn_id).
        """
        with self._lock:
            citations: list[Citation] = []
            if include_citations and self._citation_injector is not None:
                ctx = self._citation_injector.get_context(turn_id)
                if ctx is not None:
                    citations = list(ctx.citations)

            rollback_actions: list[RollbackAction] = []
            if include_rollback and self._rollback_manager is not None:
                # Filter by turn_id in metadata
                all_actions = self._rollback_manager.history()
                rollback_actions = [a for a in all_actions if a.metadata.get("turn_id") == turn_id]

            audit_events: list[AuditEvent] = []
            if include_audit and self._audit_viewer is not None:
                if session_id:
                    # Use AuditFilter with user_id + turn_id
                    audit_events = self._audit_viewer.query(
                        AuditFilter(
                            user_id=user_id or None,
                            turn_id=turn_id,
                        )
                    )

            fact_check: FactCheckReport | None = None
            if (
                include_fact_check
                and self._fact_checker is not None
                and response_text
                and fact_check_evidence_provider is not None
            ):
                fact_check = self._fact_checker.check(
                    response_text,
                    evidence_provider=fact_check_evidence_provider,
                )

            verdict = self._compute_verdict(
                citations=citations,
                rollback_actions=rollback_actions,
                audit_events=audit_events,
                fact_check=fact_check,
            )

            return ExplanationReport(
                turn_id=turn_id,
                user_id=user_id,
                session_id=session_id,
                response_text=response_text,
                citations=citations,
                rollback_actions=rollback_actions,
                audit_events=audit_events,
                fact_check=fact_check,
                verdict=verdict,
                metadata=dict(metadata or {}),
            )

    def explain_action(
        self,
        action_id: str,
        *,
        user_id: str = "",
        session_id: str = "",
    ) -> ExplanationReport | None:
        """Build a report scoped to a single rollback action.

        Returns ``None`` if the action is unknown.
        """
        with self._lock:
            if self._rollback_manager is None:
                return None
            # Scan history for the action_id (no direct get())
            target: RollbackAction | None = None
            for a in self._rollback_manager.history():
                if a.action_id == action_id:
                    target = a
                    break
            if target is None:
                return None
            is_undone = target.undone
            failed = target.status == RollbackStatus.FAILED
            verdict = (
                Verdict.FAILED if failed else Verdict.TRUSTED if is_undone else Verdict.NEEDS_REVIEW
            )
            return ExplanationReport(
                turn_id=target.metadata.get("turn_id", action_id),
                user_id=user_id or target.user_id,
                session_id=session_id,
                response_text=target.description or "",
                rollback_actions=[target],
                verdict=verdict,
                metadata={"scope": "action", "action_id": action_id},
            )

    # -- verdict computation -------------------------------------------

    @staticmethod
    def _compute_verdict(
        *,
        citations: list[Citation],
        rollback_actions: list[RollbackAction],
        audit_events: list[AuditEvent],
        fact_check: FactCheckReport | None,
    ) -> Verdict:
        """Derive a single overall verdict from the trust data.

        Rules (in priority order):
          * FAILED — any audit event failed (success=False)
          * FAILED — any rollback action failed
          * NEEDS_REVIEW — fact-check found unsupported claims
          * NEEDS_REVIEW — response has no citations (ungrounded)
          * TRUSTED — at least one citation AND no failures
          * UNKNOWN — no data at all
        """
        # Failed audit events
        for ev in audit_events:
            if not ev.success:
                return Verdict.FAILED
        # Failed rollback actions
        for a in rollback_actions:
            if a.status == RollbackStatus.FAILED:
                return Verdict.FAILED
        # Fact-check findings
        if fact_check is not None and fact_check.total > 0:
            if fact_check.support_rate < 0.5:
                return Verdict.NEEDS_REVIEW
        # No data at all
        if not citations and not rollback_actions and not audit_events:
            return Verdict.UNKNOWN
        # No citations but has other data
        if not citations:
            return Verdict.NEEDS_REVIEW
        return Verdict.TRUSTED


# -- renderers --------------------------------------------------------------


def format_explanation_markdown(report: ExplanationReport) -> str:
    """Render an :class:`ExplanationReport` as Markdown.

    Suitable for chat UIs that support Markdown (Discord,
    Telegram, GitHub, etc.).  Sections are skipped when
    empty so the report is always compact.
    """
    lines: list[str] = []
    # Header
    lines.append(f"## Explanation — turn `{report.turn_id[:8]}`")
    lines.append("")
    lines.append(f"**Verdict:** `{report.verdict.value}`")
    if report.user_id:
        lines.append(f"**User:** `{report.user_id}`")
    if report.session_id:
        lines.append(f"**Session:** `{report.session_id}`")
    lines.append(f"**Generated:** {report.created_at.isoformat()}")
    lines.append("")
    # Response
    if report.response_text:
        lines.append("### Response")
        lines.append("")
        lines.append("```")
        lines.append(report.response_text)
        lines.append("```")
        lines.append("")
    # Citations
    if report.citations:
        lines.append(f"### Citations ({len(report.citations)})")
        lines.append("")
        lines.append(format_sources_list(report.citations))
        lines.append("")
    # Fact-check
    if report.fact_check is not None and report.fact_check.total > 0:
        lines.append("### Fact-check")
        lines.append("")
        lines.append(
            f"- Claims: **{report.fact_check.total}**  "
            f"- Supported: **{report.fact_check.supported_count}**  "
            f"- Support rate: **{report.fact_check.support_rate:.0%}**"
        )
        lines.append("")
        for r in report.fact_check.results:
            verdict = "supported" if r.has_evidence else "unsupported"
            lines.append(f"- `{verdict}` — {r.claim.text}")
        lines.append("")
    # Rollback actions
    if report.rollback_actions:
        lines.append(f"### Rollback actions ({len(report.rollback_actions)})")
        lines.append("")
        for a in report.rollback_actions:
            status = _enum_value(a.status)
            label = a.description or a.tool_name
            lines.append(f"- `{a.action_id[:8]}` **{a.tool_name}** — {label} — *{status}*")
        lines.append("")
    # Audit events
    if report.audit_events:
        lines.append(f"### Audit events ({len(report.audit_events)})")
        lines.append("")
        for ev in report.audit_events:
            ok = "ok" if ev.success else "FAIL"
            kind = _enum_value(ev.kind)
            action = ev.action or ev.actor
            lines.append(f"- `{ok}` {kind} — {action} ({ev.timestamp.isoformat()})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_explanation_text(report: ExplanationReport) -> str:
    """Render as plain text (no Markdown)."""
    lines: list[str] = []
    lines.append(f"Explanation — turn {report.turn_id[:8]}")
    lines.append(f"Verdict: {report.verdict.value}")
    lines.append(f"Generated: {report.created_at.isoformat()}")
    if report.response_text:
        lines.append("")
        lines.append("Response:")
        lines.append(report.response_text)
    if report.citations:
        lines.append("")
        lines.append(f"Citations ({len(report.citations)}):")
        for i, c in enumerate(report.citations, start=1):
            lines.append(f"  [{i}] {c.short()}")
    if report.fact_check is not None and report.fact_check.total > 0:
        lines.append("")
        lines.append(
            f"Fact-check: {report.fact_check.supported_count}/"
            f"{report.fact_check.total} supported "
            f"({report.fact_check.support_rate:.0%})"
        )
    if report.rollback_actions:
        lines.append("")
        lines.append(f"Rollback actions ({len(report.rollback_actions)}):")
        for a in report.rollback_actions:
            status = _enum_value(a.status)
            label = a.description or a.tool_name
            lines.append(f"  {a.tool_name} — {label} — {status}")
    if report.audit_events:
        lines.append("")
        lines.append(f"Audit events ({len(report.audit_events)}):")
        for ev in report.audit_events:
            ok = "ok" if ev.success else "FAIL"
            kind = _enum_value(ev.kind)
            lines.append(f"  {ok} {kind} — {ev.action or ev.actor}")
    return "\n".join(lines)


__all__ = [
    "ExplanationBuilder",
    "ExplanationReport",
    "Verdict",
    "format_explanation_markdown",
    "format_explanation_text",
]


# Re-exports kept import-visible for type-checkers.
_ = (AuditEvent, CitationContext, FactCheckReport, RollbackAction)
