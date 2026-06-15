"""Main verifier.

The verifier is the post-execution judge.  It is called once per step
(by the executor) and once per plan (by the runtime).  It returns a
structured :class:`VerificationReport` rather than a boolean so callers
can act on the specifics — e.g. replan only the blocking failures, or
warn the user about non-blocking ones.

Two execution paths:

1. **Automatic** — the verifier inspects the step's ``action`` and
   ``tool_name`` and runs the relevant built-in checks.  This is the
   default and works without any LLM involvement.
2. **LLM-as-judge** — for soft criteria ("the response addresses the
   user's question") the verifier optionally calls a small model.
   This is opt-in via the ``llm_judge`` callback.

The verifier is intentionally pluggable: pass ``extra_checks`` to add
custom rules for a specific tool or domain.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Mapping

from app.core.verifier.checks import (
    check_exit_code,
    check_file_written,
    check_json_valid,
    check_markdown_well_formed,
    check_non_empty,
    check_regex,
    check_substring,
    check_url_well_formed,
)
from app.core.verifier.types import (
    CheckKind,
    CheckResult,
    Severity,
    VerificationReport,
)

logger = logging.getLogger(__name__)


# A custom check is a callable that takes the step output and returns
# a CheckResult.  Sync or async.
CustomCheck = Callable[["StepContext"], "CheckResult | Awaitable[CheckResult]"]


# Lightweight description of what was executed, passed in by the caller.
# The verifier does not know the full plan structure; it only needs the
# fields it can act on.
class StepContext:
    """A bag of fields the verifier inspects.

    ``output`` is whatever the executor produced (text, dict, or
    structured data depending on the tool).  ``metadata`` is an
    open-ended dict for tool-specific extras (e.g. ``{"exit_code": 0}``).
    """

    __slots__ = (
        "plan_id",
        "step_id",
        "action",
        "tool_name",
        "prompt",
        "output",
        "metadata",
    )

    def __init__(
        self,
        *,
        plan_id: str,
        step_id: str,
        action: str,
        tool_name: str | None,
        prompt: str | None,
        output: Any,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.plan_id = plan_id
        self.step_id = step_id
        self.action = action
        self.tool_name = tool_name
        self.prompt = prompt
        self.output = output
        self.metadata = dict(metadata or {})

    def __repr__(self) -> str:
        return f"StepContext(plan_id={self.plan_id!r}, step_id={self.step_id!r}, action={self.action!r})"


# A "judge" is a callback that takes the step context and returns
# a passed/failed CheckResult with a confidence score.
JudgeFn = Callable[[StepContext], Awaitable[CheckResult]]


class Verifier:
    """Run checks against a step's output and produce a report."""

    def __init__(
        self,
        *,
        extra_checks: list[CustomCheck] | None = None,
        llm_judge: JudgeFn | None = None,
        # Per-action overrides.  Maps action name → list of check fns.
        action_checks: Mapping[str, list[CustomCheck]] | None = None,
        # If True, run the LLM judge after deterministic checks pass.
        # If False, only deterministic checks run.
        use_llm_judge: bool = False,
    ) -> None:
        self._extra = list(extra_checks or [])
        self._judge = llm_judge
        self._action_checks = dict(action_checks or {})
        self._use_llm_judge = use_llm_judge

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def verify(self, ctx: StepContext) -> VerificationReport:
        """Run all applicable checks and return a structured report."""
        checks: list[CheckResult] = []

        # 1. Always: non-empty
        if ctx.output is not None:
            checks.append(
                check_non_empty(
                    ctx.output,
                    name="output_non_empty",
                )
            )

        # 2. Auto-dispatch by action / tool
        checks.extend(self._auto_checks(ctx))

        # 3. Action-specific extras
        for chk in self._action_checks.get(ctx.action, []):
            try:
                result = chk(ctx)
                if hasattr(result, "__await__"):
                    result = await result  # type: ignore[func-returns-value]
                checks.append(result)
            except Exception as e:  # noqa: BLE001
                checks.append(
                    CheckResult(
                        name=getattr(chk, "__name__", "extra"),
                        kind=CheckKind.CUSTOM,
                        passed=False,
                        severity=Severity.WARNING,
                        message=f"check raised: {e}",
                    )
                )

        # 4. Global extras
        for chk in self._extra:
            try:
                result = chk(ctx)
                if hasattr(result, "__await__"):
                    result = await result  # type: ignore[func-returns-value]
                checks.append(result)
            except Exception as e:  # noqa: BLE001
                checks.append(
                    CheckResult(
                        name=getattr(chk, "__name__", "extra"),
                        kind=CheckKind.CUSTOM,
                        passed=False,
                        severity=Severity.WARNING,
                        message=f"check raised: {e}",
                    )
                )

        # 5. LLM-as-judge (only if deterministic checks all pass)
        if self._use_llm_judge and self._judge is not None:
            blocking_failed = any(
                not c.passed and c.severity == Severity.BLOCKING for c in checks
            )
            if not blocking_failed:
                try:
                    judge_result = await self._judge(ctx)
                    checks.append(judge_result)
                except Exception as e:  # noqa: BLE001
                    checks.append(
                        CheckResult(
                            name="llm_judge",
                            kind=CheckKind.LLM_JUDGE,
                            passed=True,
                            severity=Severity.WARNING,
                            message=f"judge failed: {e}",
                        )
                    )

        report = VerificationReport.from_checks(ctx.plan_id, ctx.step_id, checks)
        if not report.passed:
            logger.debug(
                "verification failed for step %s: %d blocking failures",
                ctx.step_id,
                report.blocking_failures,
            )
        return report

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _auto_checks(self, ctx: StepContext) -> list[CheckResult]:
        """Decide which built-in checks to run based on action / tool."""
        out: list[CheckResult] = []
        output = ctx.output
        meta = ctx.metadata

        # Common: success_criteria substring match
        criteria = meta.get("success_criteria")
        if isinstance(criteria, str) and criteria:
            # Treat the criteria as a regex with a fallback substring.
            if _looks_like_regex(criteria):
                out.append(
                    check_regex(
                        str(output) if output is not None else "",
                        criteria,
                        name="success_criteria",
                    )
                )
            else:
                out.append(
                    check_substring(
                        str(output) if output is not None else "",
                        criteria,
                        case_sensitive=False,
                        name="success_criteria",
                    )
                )

        # Tool-specific
        if ctx.action == "tool":
            if ctx.tool_name in {"file_write", "write_file", "save_file"}:
                path = meta.get("path") or (
                    output.get("path") if isinstance(output, Mapping) else None
                )
                if path:
                    out.append(
                        check_file_written(
                            path, min_bytes=1, name=f"file_written({path})"
                        )
                    )
            elif ctx.tool_name in {"file_read", "read_file"}:
                out.append(check_non_empty(output, name="file_read_non_empty"))
            elif ctx.tool_name in {"exec", "shell", "bash", "command"}:
                code = meta.get("exit_code", 0)
                out.append(check_exit_code(int(code), 0, name="exec_exit_code"))
            elif ctx.tool_name in {"web_search", "search", "tavily"}:
                out.append(check_non_empty(output, name="search_non_empty"))
            elif ctx.tool_name in {"web_fetch", "fetch", "http_get"}:
                out.append(check_non_empty(output, name="fetch_non_empty"))
                url = meta.get("url")
                if isinstance(url, str):
                    out.append(
                        check_url_well_formed(url, name=f"url_well_formed({url})")
                    )

        elif ctx.action == "llm":
            out.append(check_non_empty(output, name="llm_non_empty"))
            if meta.get("expect_json"):
                out.append(
                    check_json_valid(
                        str(output) if output is not None else "",
                        name="llm_json_valid",
                    )
                )
            if meta.get("expect_markdown"):
                out.append(
                    check_markdown_well_formed(
                        str(output) if output is not None else "",
                        name="llm_markdown_well_formed",
                    )
                )

        elif ctx.action == "ask_user":
            # No output expected — the check is that we got an answer.
            out.append(
                CheckResult(
                    name="ask_user_answered",
                    kind=CheckKind.STRUCTURE,
                    passed=output is not None and str(output).strip() != "",
                    message="user did not answer" if output is None else "",
                )
            )

        elif ctx.action == "wait":
            # Waiting is a success if no exception bubbled up.
            out.append(
                CheckResult(
                    name="wait_completed",
                    kind=CheckKind.NON_EMPTY,
                    passed=meta.get("completed", True),
                    message="wait did not complete"
                    if not meta.get("completed", True)
                    else "",
                )
            )

        return out


def _looks_like_regex(s: str) -> bool:
    """Heuristic: does the criteria look like a regex rather than prose?"""
    if not s:
        return False
    if len(s) > 200:
        return False
    # Common regex tokens
    if any(
        tok in s
        for tok in (".*", ".+", "\\d", "\\w", "\\s", "(?:", "[a-z", "[0-9", "^", "$")
    ):
        return True
    return False


__all__ = ["Verifier", "StepContext", "CustomCheck", "JudgeFn"]
