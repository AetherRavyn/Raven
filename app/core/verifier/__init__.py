"""Post-execution verification (A3 in the foundation plan).

Public API:
- :class:`Verifier` — the main entry point.  Call :meth:`verify` with
  a :class:`StepContext` and get a :class:`VerificationReport`.
- :class:`StepContext` — input bag describing what was executed.
- :class:`VerificationReport`, :class:`CheckResult`, :class:`Severity`,
  :class:`CheckKind` — structured result types.
- :class:`VerificationFailed` — exception raised by the executor when
  a step's report has blocking failures.
- :mod:`app.core.verifier.checks` — individual rule functions that
  can be composed in custom :class:`StepContext` handlers.
"""

from app.core.verifier.checks import (
    check_exit_code,
    check_file_exists,
    check_file_written,
    check_json_valid,
    check_markdown_well_formed,
    check_non_empty,
    check_regex,
    check_structure,
    check_substring,
    check_url_well_formed,
)
from app.core.verifier.types import (
    CheckKind,
    CheckResult,
    Severity,
    VerificationFailed,
    VerificationReport,
)
from app.core.verifier.verifier import (
    CustomCheck,
    JudgeFn,
    StepContext,
    Verifier,
)

__all__ = [
    "Verifier",
    "StepContext",
    "CustomCheck",
    "JudgeFn",
    "Severity",
    "CheckKind",
    "CheckResult",
    "VerificationReport",
    "VerificationFailed",
    # Built-in checks
    "check_non_empty",
    "check_substring",
    "check_regex",
    "check_json_valid",
    "check_markdown_well_formed",
    "check_file_exists",
    "check_file_written",
    "check_exit_code",
    "check_url_well_formed",
    "check_structure",
]
