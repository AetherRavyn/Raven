"""Phase F1 — Trust & Explainability.

Four modules:

  * :mod:`app.core.trust.citations`     — inline ``[1]`` / ``[2]``
    source markers on every fact the agent states.
  * :mod:`app.core.trust.rollback`      — registry of compensating
    functions so any mutating action can be undone.
  * :mod:`app.core.trust.audit_viewer`  — rich query layer over the
    :class:`AuditLog` with filtering, timelines, turn replay, and
    summary stats.
  * :mod:`app.core.trust.fact_check`    — claim extraction + evidence
    lookup + verdict for flagging unsupported LLM statements.

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
    "CitationManager",
    "CitationSource",
    "CitedFact",
    "Claim",
    "EvidenceProvider",
    "FactCheckReport",
    "FactCheckResult",
    "FactChecker",
    "RollbackAction",
    "RollbackManager",
    "RollbackRegistry",
    "RollbackResult",
    "RollbackStatus",
    "TimelineBucket",
    "dict_evidence_provider",
    "format_sources_list",
    "get_default_audit_viewer",
    "get_default_citation_manager",
    "get_default_fact_checker",
    "get_default_rollback_manager",
    "reset_default_audit_viewer",
    "reset_default_citation_manager",
    "reset_default_fact_checker",
    "reset_default_rollback_manager",
    "set_default_audit_viewer",
    "set_default_citation_manager",
    "set_default_fact_checker",
    "set_default_rollback_manager",
]
