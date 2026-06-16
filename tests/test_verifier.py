"""Tests for the verifier (A3 in the foundation plan)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.verifier import (
    CheckKind,
    CheckResult,
    Severity,
    StepContext,
    Verifier,
    VerificationReport,
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
from app.core.verifier.verifier import _looks_like_regex


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


class TestIndividualChecks:
    def test_non_empty_passes(self) -> None:
        r = check_non_empty("hello")
        assert r.passed
        assert r.kind == CheckKind.NON_EMPTY

    def test_non_empty_fails_on_empty(self) -> None:
        assert not check_non_empty("").passed
        assert not check_non_empty("   ").passed
        assert not check_non_empty(None).passed

    def test_substring_match(self) -> None:
        r = check_substring("hello world", "world")
        assert r.passed
        assert check_substring("hello", "world") is not None
        assert not check_substring("hello", "world").passed

    def test_substring_case_insensitive(self) -> None:
        r = check_substring("Hello WORLD", "world", case_sensitive=False)
        assert r.passed

    def test_substring_wrong_type(self) -> None:
        r = check_substring(123, "world")  # type: ignore[arg-type]
        assert not r.passed

    def test_regex_match(self) -> None:
        r = check_regex("foo 123 bar", r"\d+")
        assert r.passed
        assert r.actual == "123"

    def test_regex_no_match(self) -> None:
        r = check_regex("foo bar", r"\d+")
        assert not r.passed

    def test_regex_invalid(self) -> None:
        r = check_regex("foo", r"[invalid")
        assert not r.passed
        assert "invalid regex" in r.message

    def test_json_valid(self) -> None:
        assert check_json_valid('{"a": 1}').passed
        assert check_json_valid("[1, 2, 3]").passed
        assert not check_json_valid("not json").passed
        assert not check_json_valid(123).passed  # type: ignore[arg-type]

    def test_markdown_balanced(self) -> None:
        assert check_markdown_well_formed("# heading\n\ntext").passed
        assert check_markdown_well_formed("```\ncode\n```").passed

    def test_markdown_unbalanced_fences(self) -> None:
        r = check_markdown_well_formed("```\ncode")
        assert not r.passed
        assert r.severity == Severity.WARNING

    def test_markdown_unbalanced_links(self) -> None:
        r = check_markdown_well_formed("[broken link")
        assert not r.passed
        assert r.severity == Severity.WARNING

    def test_file_exists(self, tmp_path: Path) -> None:
        p = tmp_path / "x.txt"
        p.write_text("hi")
        assert check_file_exists(str(p)).passed
        assert not check_file_exists(str(p / "missing")).passed

    def test_file_written_min_bytes(self, tmp_path: Path) -> None:
        p = tmp_path / "x.txt"
        p.write_text("hi")
        assert check_file_written(str(p), min_bytes=1).passed
        assert not check_file_written(str(p), min_bytes=100).passed

    def test_file_written_missing(self, tmp_path: Path) -> None:
        assert not check_file_written(str(tmp_path / "missing")).passed

    def test_exit_code(self) -> None:
        assert check_exit_code(0).passed
        assert not check_exit_code(1).passed
        assert check_exit_code(0, expected=0).passed
        assert check_exit_code(2, expected=2).passed

    def test_url_well_formed(self) -> None:
        assert check_url_well_formed("https://example.com").passed
        assert not check_url_well_formed("not a url").passed
        assert not check_url_well_formed("").passed

    def test_url_requires_https(self) -> None:
        r = check_url_well_formed("http://example.com", require_https=True)
        assert not r.passed
        assert r.severity == Severity.WARNING

    def test_structure_missing_keys(self) -> None:
        r = check_structure({"a": 1, "b": 2}, ["a", "c"])
        assert not r.passed
        assert "c" in r.message

    def test_structure_passes(self) -> None:
        r = check_structure({"a": 1}, ["a"])
        assert r.passed

    def test_structure_wrong_type(self) -> None:
        r = check_structure("not a dict", ["a"])  # type: ignore[arg-type]
        assert not r.passed

    def test_all_checks_set_duration(self) -> None:
        # The duration_ms field is set even for very fast checks.
        r = check_non_empty("x")
        assert r.duration_ms >= 1


class TestLooksLikeRegex:
    def test_prose_is_not_regex(self) -> None:
        assert not _looks_like_regex("the response should greet the user")

    def test_real_regex_detected(self) -> None:
        assert _looks_like_regex(r"\d+")
        assert _looks_like_regex(r"^https?://")
        assert _looks_like_regex(r"[a-z]+")
        assert _looks_like_regex(".*")

    def test_long_string_is_not_treated_as_regex(self) -> None:
        assert not _looks_like_regex("a" * 300)


# ---------------------------------------------------------------------------
# StepContext
# ---------------------------------------------------------------------------


class TestStepContext:
    def test_basic_construction(self) -> None:
        ctx = StepContext(
            plan_id="p1",
            step_id="s1",
            action="tool",
            tool_name="file_write",
            prompt="write hello",
            output={"path": "/tmp/x"},
            metadata={"path": "/tmp/x"},
        )
        assert ctx.plan_id == "p1"
        assert ctx.output == {"path": "/tmp/x"}
        assert ctx.metadata["path"] == "/tmp/x"

    def test_metadata_defaults_to_empty_dict(self) -> None:
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt=None,
            output="hi",
        )
        assert ctx.metadata == {}


# ---------------------------------------------------------------------------
# Verifier — automatic checks
# ---------------------------------------------------------------------------


class TestVerifierAuto:
    @pytest.mark.asyncio
    async def test_empty_output_fails_non_empty(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt=None,
            output="",
        )
        report = await v.verify(ctx)
        assert not report.passed
        assert report.blocking_failures >= 1

    @pytest.mark.asyncio
    async def test_llm_step_runs_non_empty(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="say hi",
            output="hello!",
        )
        report = await v.verify(ctx)
        assert report.passed
        assert any(c.name == "llm_non_empty" for c in report.checks)

    @pytest.mark.asyncio
    async def test_llm_step_with_expect_json(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="output json",
            output='{"a": 1}',
            metadata={"expect_json": True},
        )
        report = await v.verify(ctx)
        assert report.passed
        assert any(c.name == "llm_json_valid" for c in report.checks)

    @pytest.mark.asyncio
    async def test_llm_step_with_invalid_json_fails(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="output json",
            output="not json",
            metadata={"expect_json": True},
        )
        report = await v.verify(ctx)
        assert not report.passed

    @pytest.mark.asyncio
    async def test_file_write_step(self, tmp_path: Path) -> None:
        v = Verifier()
        p = tmp_path / "out.txt"
        p.write_text("hello")
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="tool",
            tool_name="file_write",
            prompt="write",
            output={"path": str(p)},
            metadata={"path": str(p)},
        )
        report = await v.verify(ctx)
        assert report.passed
        assert any(c.name.startswith("file_written(") for c in report.checks)

    @pytest.mark.asyncio
    async def test_file_write_step_missing_file_fails(self, tmp_path: Path) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="tool",
            tool_name="file_write",
            prompt="write",
            output={"path": str(tmp_path / "missing.txt")},
            metadata={"path": str(tmp_path / "missing.txt")},
        )
        report = await v.verify(ctx)
        assert not report.passed

    @pytest.mark.asyncio
    async def test_exec_step_exit_code_zero(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="tool",
            tool_name="exec",
            prompt="ls",
            output="file1\nfile2",
            metadata={"exit_code": 0},
        )
        report = await v.verify(ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_exec_step_nonzero_exit_fails(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="tool",
            tool_name="exec",
            prompt="bad",
            output="error",
            metadata={"exit_code": 1},
        )
        report = await v.verify(ctx)
        assert not report.passed

    @pytest.mark.asyncio
    async def test_web_search_non_empty(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="tool",
            tool_name="web_search",
            prompt="x",
            output=["result1", "result2"],
        )
        report = await v.verify(ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_web_fetch_with_url(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="tool",
            tool_name="web_fetch",
            prompt="x",
            output="page content",
            metadata={"url": "https://example.com"},
        )
        report = await v.verify(ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_ask_user_answered(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="ask_user",
            tool_name=None,
            prompt="color?",
            output="blue",
        )
        report = await v.verify(ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_ask_user_not_answered(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="ask_user",
            tool_name=None,
            prompt="color?",
            output=None,
        )
        report = await v.verify(ctx)
        assert not report.passed

    @pytest.mark.asyncio
    async def test_wait_completed(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="wait",
            tool_name=None,
            prompt=None,
            output=None,
            metadata={"completed": True},
        )
        report = await v.verify(ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_wait_not_completed_fails(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="wait",
            tool_name=None,
            prompt=None,
            output=None,
            metadata={"completed": False},
        )
        report = await v.verify(ctx)
        assert not report.passed


# ---------------------------------------------------------------------------
# Verifier — criteria + extras
# ---------------------------------------------------------------------------


class TestVerifierCriteria:
    @pytest.mark.asyncio
    async def test_success_criteria_substring(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="q",
            output="the answer is 42",
            metadata={"success_criteria": "answer is 42"},
        )
        report = await v.verify(ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_success_criteria_regex(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="q",
            output="order #12345",
            metadata={"success_criteria": r"order #\d+"},
        )
        report = await v.verify(ctx)
        assert report.passed
        assert any(c.name == "success_criteria" for c in report.checks)

    @pytest.mark.asyncio
    async def test_success_criteria_miss_fails(self) -> None:
        v = Verifier()
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="q",
            output="nope",
            metadata={"success_criteria": "expected phrase"},
        )
        report = await v.verify(ctx)
        assert not report.passed

    @pytest.mark.asyncio
    async def test_extra_check_appends(self) -> None:
        def must_contain_yes(ctx: StepContext) -> CheckResult:
            return CheckResult(
                name="must_contain_yes",
                kind=CheckKind.SUBSTRING,
                passed="yes" in str(ctx.output),
            )

        v = Verifier(extra_checks=[must_contain_yes])
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="q",
            output="yes please",
        )
        report = await v.verify(ctx)
        assert report.passed
        assert any(c.name == "must_contain_yes" for c in report.checks)

    @pytest.mark.asyncio
    async def test_extra_check_exception_becomes_warning(self) -> None:
        def bad_check(ctx: StepContext) -> CheckResult:
            raise RuntimeError("boom")

        v = Verifier(extra_checks=[bad_check])
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="q",
            output="hi",
        )
        report = await v.verify(ctx)
        # The exception is captured as a warning, not a blocking failure.
        assert report.passed
        assert any(c.severity == Severity.WARNING and "boom" in c.message for c in report.checks)

    @pytest.mark.asyncio
    async def test_action_specific_check(self) -> None:
        def code_step_check(ctx: StepContext) -> CheckResult:
            return CheckResult(
                name="code_compiles",
                kind=CheckKind.CUSTOM,
                passed=isinstance(ctx.output, str) and "def " in ctx.output,
            )

        v = Verifier(action_checks={"llm": [code_step_check]})
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="write a function",
            output="def f(): pass",
        )
        report = await v.verify(ctx)
        assert any(c.name == "code_compiles" for c in report.checks)


# ---------------------------------------------------------------------------
# Verifier — LLM-as-judge
# ---------------------------------------------------------------------------


class TestLLMJudge:
    @pytest.mark.asyncio
    async def test_judge_runs_after_deterministic_pass(self) -> None:
        async def judge(ctx: StepContext) -> CheckResult:
            return CheckResult(
                name="llm_judge",
                kind=CheckKind.LLM_JUDGE,
                passed=True,
                confidence=0.9,
                message="looks good",
            )

        v = Verifier(llm_judge=judge, use_llm_judge=True)
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="q",
            output="answer",
        )
        report = await v.verify(ctx)
        assert any(c.name == "llm_judge" for c in report.checks)

    @pytest.mark.asyncio
    async def test_judge_skipped_when_deterministic_fails(self) -> None:
        async def judge(ctx: StepContext) -> CheckResult:
            return CheckResult(
                name="llm_judge",
                kind=CheckKind.LLM_JUDGE,
                passed=True,
                confidence=0.9,
            )

        v = Verifier(llm_judge=judge, use_llm_judge=True)
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="q",
            output="",  # fails non-empty
        )
        report = await v.verify(ctx)
        assert not report.passed
        # judge was skipped because deterministic failed
        assert not any(c.name == "llm_judge" for c in report.checks)

    @pytest.mark.asyncio
    async def test_judge_disabled_by_default(self) -> None:
        async def judge(ctx: StepContext) -> CheckResult:
            return CheckResult(
                name="llm_judge",
                kind=CheckKind.LLM_JUDGE,
                passed=True,
            )

        v = Verifier(llm_judge=judge)  # use_llm_judge defaults to False
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="q",
            output="answer",
        )
        report = await v.verify(ctx)
        assert not any(c.name == "llm_judge" for c in report.checks)

    @pytest.mark.asyncio
    async def test_judge_exception_is_warning(self) -> None:
        async def judge(ctx: StepContext) -> CheckResult:
            raise RuntimeError("model down")

        v = Verifier(llm_judge=judge, use_llm_judge=True)
        ctx = StepContext(
            plan_id="p",
            step_id="s",
            action="llm",
            tool_name=None,
            prompt="q",
            output="answer",
        )
        report = await v.verify(ctx)
        # Should still pass (warning, not blocking)
        assert report.passed
        assert any(c.severity == Severity.WARNING for c in report.checks)


# ---------------------------------------------------------------------------
# VerifierReport
# ---------------------------------------------------------------------------


class TestVerificationReport:
    def test_to_dict_serializable(self) -> None:
        checks = [
            CheckResult(name="a", kind=CheckKind.NON_EMPTY, passed=True),
            CheckResult(name="b", kind=CheckKind.SUBSTRING, passed=False),
        ]
        report = VerificationReport.from_checks("p", "s", checks)
        d = report.to_dict()
        assert d["plan_id"] == "p"
        assert d["step_id"] == "s"
        assert d["passed"] is False
        assert d["blocking_failures"] == 1
        json.dumps(d)  # must be JSON-serializable

    def test_from_checks_passing(self) -> None:
        checks = [CheckResult(name="a", kind=CheckKind.NON_EMPTY, passed=True)]
        r = VerificationReport.from_checks("p", "s", checks)
        assert r.passed
        assert r.blocking_failures == 0

    def test_from_checks_warning_does_not_block(self) -> None:
        checks = [
            CheckResult(
                name="a",
                kind=CheckKind.SUBSTRING,
                passed=False,
                severity=Severity.WARNING,
            )
        ]
        r = VerificationReport.from_checks("p", "s", checks)
        assert r.passed
        assert r.warnings == 1
