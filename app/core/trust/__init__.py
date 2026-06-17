"""Phase F1 — Trust & Explainability.

Two modules:

  * :mod:`app.core.trust.citations` — inline ``[1]`` / ``[2]``
    source markers on every fact the agent states.
  * :mod:`app.core.trust.rollback` — registry of compensating
    functions so any mutating action can be undone.

Both expose a process-singleton facade (``get_default_*``)
and a reset hook for tests.
"""

from __future__ import annotations

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
    "Citation",
    "CitationManager",
    "CitationSource",
    "CitedFact",
    "RollbackAction",
    "RollbackManager",
    "RollbackRegistry",
    "RollbackResult",
    "RollbackStatus",
    "format_sources_list",
    "get_default_citation_manager",
    "get_default_rollback_manager",
    "reset_default_citation_manager",
    "reset_default_rollback_manager",
    "set_default_citation_manager",
    "set_default_rollback_manager",
]
