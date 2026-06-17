"""Phase F1 — Trust & Explainability.

Seven modules:

  * :mod:`app.core.trust.citations`         — inline ``[1]`` / ``[2]``
    source markers on every fact the agent states.
  * :mod:`app.core.trust.rollback`          — registry of compensating
    functions so any mutating action can be undone.
  * :mod:`app.core.trust.audit_viewer`      — rich query layer over the
    :class:`AuditLog` with filtering, timelines, turn replay, and
    summary stats.
  * :mod:`app.core.trust.fact_check`        — claim extraction + evidence
    lookup + verdict for flagging unsupported LLM statements.
  * :mod:`app.core.trust.citation_runtime`  — per-turn citation context
    + inline-injection of ``[1]`` markers + sources footer into
    the final response.  Wires citations into the agent runtime.
  * :mod:`app.core.trust.explanation`       — bundles citations +
    rollback + audit + fact-check into a single user-facing
    report ("Why did the agent say that?") with Markdown / text /
    JSON renderers.
  * :mod:`app.core.trust.slash_commands`    — user-facing chat commands
    (``/explain``, ``/explain-action``, ``/trust-status``,
    ``/explain-turns``) that surface the trust module in any
    chat interface.

All expose a process-singleton facade (``get_default_*``)
and a reset hook for tests.
"""

from __future__ import annotations

from app.core.trust.audit_viewer import (
    AuditFilter,
    AuditSummary,
    AuditViewer,
    TimelineBucket,
    get_default_audit_viewer,
    reset_default_audit_viewer,
    set_default_audit_viewer,
)
from app.core.trust.citations import (
    Citation,
    CitationManager,
    CitationSource,
    CitedFact,
    format_sources_list,
    get_default_citation_manager,
    reset_default_citation_manager,
    set_default_citation_manager,
)
from app.core.trust.citation_runtime import (
    CitationContext,
    CitationInjector,
    InjectionMode,
    get_default_citation_injector,
    reset_default_citation_injector,
    set_default_citation_injector,
)
from app.core.trust.explanation import (
    ExplanationBuilder,
    ExplanationReport,
    Verdict,
    format_explanation_markdown,
    format_explanation_text,
)
from app.core.trust.slash_commands import (
    ExplainActionCommand,
    ExplainCommand,
    ExplainTurnsCommand,
    SlashCommand,
    SlashCommandContext,
    SlashCommandRegistry,
    TrustStatusCommand,
    get_default_command_registry,
    reset_default_command_registry,
    run_command,
    set_default_command_registry,
)
from app.core.trust.fact_check import (
    Claim,
    EvidenceProvider,
    FactCheckReport,
    FactCheckResult,
    FactChecker,
    dict_evidence_provider,
    get_default_fact_checker,
    reset_default_fact_checker,
    set_default_fact_checker,
)
from app.core.trust.rollback import (
    RollbackAction,
    RollbackManager,
    RollbackRegistry,
    RollbackResult,
    RollbackStatus,
    get_default_rollback_manager,
    reset_default_rollback_manager,
    set_default_rollback_manager,
)

__all__ = [
    "AuditFilter",
    "AuditSummary",
    "AuditViewer",
    "Citation",
    "CitationContext",
    "CitationInjector",
    "CitationManager",
    "CitationSource",
    "CitedFact",
    "Claim",
    "EvidenceProvider",
    "ExplainActionCommand",
    "ExplainCommand",
    "ExplainTurnsCommand",
    "ExplanationBuilder",
    "ExplanationReport",
    "FactCheckReport",
    "FactCheckResult",
    "FactChecker",
    "InjectionMode",
    "RollbackAction",
    "RollbackManager",
    "RollbackRegistry",
    "RollbackResult",
    "RollbackStatus",
    "SlashCommand",
    "SlashCommandContext",
    "SlashCommandRegistry",
    "TimelineBucket",
    "TrustStatusCommand",
    "Verdict",
    "dict_evidence_provider",
    "format_explanation_markdown",
    "format_explanation_text",
    "format_sources_list",
    "get_default_audit_viewer",
    "get_default_citation_injector",
    "get_default_citation_manager",
    "get_default_command_registry",
    "get_default_fact_checker",
    "get_default_rollback_manager",
    "reset_default_audit_viewer",
    "reset_default_citation_injector",
    "reset_default_citation_manager",
    "reset_default_command_registry",
    "reset_default_fact_checker",
    "reset_default_rollback_manager",
    "run_command",
    "set_default_audit_viewer",
    "set_default_citation_injector",
    "set_default_citation_manager",
    "set_default_command_registry",
    "set_default_fact_checker",
    "set_default_rollback_manager",
]
