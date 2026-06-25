"""Tests for ``app.core.trust.slash_commands``.

Covers the four built-in commands, the registry, and the
module-level ``run_command`` helper.
"""

from __future__ import annotations

import pytest

from app.core.audit.log import AuditLog
from app.core.trust.audit_viewer import AuditViewer
from app.core.trust.citation_runtime import CitationInjector
from app.core.trust.citations import CitationManager, CitationSource
from app.core.trust.explanation import ExplanationBuilder
from app.core.trust.rollback import RollbackManager
from app.core.trust.slash_commands import (
    ExplainActionCommand,
    ExplainCommand,
    ExplainTurnsCommand,
    SlashCommandContext,
    SlashCommandRegistry,
    TrustStatusCommand,
    get_default_command_registry,
    reset_default_command_registry,
    run_command,
    set_default_command_registry,
)


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_default_command_registry()
    yield
    reset_default_command_registry()


@pytest.fixture
def citation_injector() -> CitationInjector:
    return CitationInjector(manager=CitationManager())


@pytest.fixture
def context(citation_injector) -> SlashCommandContext:
    """A context with a citation injector, audit viewer, and rollback manager.

    The :class:`ExplanationBuilder` is wired with all four
    modules so commands that delegate to it can pull from
    every source.
    """
    rm = RollbackManager()
    av = AuditViewer(log=AuditLog())
    builder = ExplanationBuilder(
        citation_injector=citation_injector,
        rollback_manager=rm,
        audit_viewer=av,
    )
    return SlashCommandContext(
        builder=builder,
        citation_injector=citation_injector,
        audit_viewer=av,
        rollback_manager=rm,
    )


def _undo():
    return "ok"


# -- SlashCommandContext ---------------------------------------------------


class TestSlashCommandContext:
    def test_default_values(self):
        ctx = SlashCommandContext()
        assert ctx.builder is None
        assert ctx.citation_injector is None
        assert ctx.audit_viewer is None
        assert ctx.rollback_manager is None
        assert ctx.default_format == "markdown"
        assert ctx.metadata == {}

    def test_custom_values(self):
        ci = CitationInjector()
        ctx = SlashCommandContext(
            citation_injector=ci,
            default_format="text",
        )
        assert ctx.citation_injector is ci
        assert ctx.default_format == "text"


# -- SlashCommandRegistry: register / lookup -------------------------------


class TestRegistryBasics:
    def test_default_commands(self):
        reg = SlashCommandRegistry()
        names = reg.names()
        assert "explain" in names
        assert "explain-action" in names
        assert "trust-status" in names
        assert "explain-turns" in names

    def test_no_defaults(self):
        reg = SlashCommandRegistry(include_defaults=False)
        assert reg.names() == []

    def test_get_primary_name(self):
        reg = SlashCommandRegistry()
        cmd = reg.get("explain")
        assert isinstance(cmd, ExplainCommand)

    def test_get_via_alias(self):
        reg = SlashCommandRegistry()
        cmd = reg.get("why")
        assert isinstance(cmd, ExplainCommand)

    def test_get_unknown(self):
        reg = SlashCommandRegistry()
        assert reg.get("nope") is None

    def test_register_custom(self):
        reg = SlashCommandRegistry(include_defaults=False)
        reg.register(ExplainCommand())
        assert "explain" in reg.names()

    def test_register_replaces(self):
        reg = SlashCommandRegistry()
        custom = ExplainCommand()
        reg.register(custom)
        # Same name replaces
        assert reg.get("explain") is custom

    def test_unregister(self):
        reg = SlashCommandRegistry()
        assert reg.unregister("explain") is True
        assert "explain" not in reg.names()

    def test_unregister_unknown(self):
        reg = SlashCommandRegistry()
        assert reg.unregister("nope") is False

    def test_unregister_clears_aliases(self):
        reg = SlashCommandRegistry()
        reg.unregister("explain")
        assert reg.get("why") is None

    def test_all_returns_list(self):
        reg = SlashCommandRegistry()
        all_cmds = reg.all()
        # Phase 5 v13 — added CronCommand to the default registry.
        assert len(all_cmds) == 5
        assert all(hasattr(c, "name") for c in all_cmds)


# -- SlashCommandRegistry: dispatch ---------------------------------------


class TestDispatch:
    def test_dispatch_explain(self, context):
        reg = SlashCommandRegistry()
        result = reg.dispatch("/explain", context)
        # No turns → helpful message
        assert "No turns available" in result

    def test_dispatch_with_args(self, context):
        reg = SlashCommandRegistry()
        result = reg.dispatch("/explain t1", context)
        # Unknown turn → still produces a report
        assert "Explanation" in result

    def test_dispatch_unknown(self, context):
        reg = SlashCommandRegistry()
        result = reg.dispatch("/nope", context)
        assert result is None

    def test_dispatch_no_slash(self, context):
        reg = SlashCommandRegistry()
        result = reg.dispatch("explain", context)
        assert result is None

    def test_dispatch_empty(self, context):
        reg = SlashCommandRegistry()
        result = reg.dispatch("", context)
        assert result is None

    def test_dispatch_only_slash(self, context):
        reg = SlashCommandRegistry()
        result = reg.dispatch("/", context)
        assert result is None


# -- /explain ---------------------------------------------------------------


class TestExplainCommand:
    def test_no_turns(self, context):
        cmd = ExplainCommand()
        result = cmd.handle("", context)
        assert "No turns available" in result

    def test_specific_turn(self, context):
        ci = context.citation_injector
        ctx = ci.begin_turn(user_id="u1", session_id="s1")
        ci.attach_source(
            ctx.turn_id,
            CitationSource.MEMORY,
            ref="m1",
            title="M1",
        )
        cmd = ExplainCommand()
        result = cmd.handle(ctx.turn_id, context)
        assert "Explanation" in result
        assert "trusted" in result
        assert "Citations (1)" in result

    def test_most_recent_turn(self, context):
        ci = context.citation_injector
        ctx = ci.begin_turn(user_id="u1", session_id="s1")
        ci.attach_source(
            ctx.turn_id,
            CitationSource.MEMORY,
            ref="m1",
            title="M1",
        )
        cmd = ExplainCommand()
        result = cmd.handle("", context)
        assert "Explanation" in result
        assert ctx.turn_id[:8] in result

    def test_unknown_turn_still_renders(self, context):
        cmd = ExplainCommand()
        result = cmd.handle("nonexistent", context)
        # The builder still produces a (mostly empty) report
        assert "Explanation" in result

    def test_no_builder_configured(self, citation_injector):
        ctx = SlashCommandContext(citation_injector=citation_injector)
        cmd = ExplainCommand()
        result = cmd.handle("any", ctx)
        assert "Explanation not configured" in result

    def test_text_format(self, citation_injector):
        builder = ExplanationBuilder(citation_injector=citation_injector)
        ctx = SlashCommandContext(
            builder=builder,
            citation_injector=citation_injector,
            default_format="text",
        )
        ci = citation_injector
        c = ci.begin_turn(user_id="u1", session_id="s1")
        ci.attach_source(
            c.turn_id,
            CitationSource.MEMORY,
            ref="m1",
            title="M1",
        )
        cmd = ExplainCommand()
        result = cmd.handle(c.turn_id, ctx)
        # Text format — no Markdown header
        assert "Explanation — turn" in result
        assert "##" not in result

    def test_alias_why(self, context):
        reg = SlashCommandRegistry()
        result = reg.dispatch("/why", context)
        # /why is an alias for /explain — context has no turns
        assert "No turns available" in result

    def test_alias_why_with_turn(self, context):
        ci = context.citation_injector
        c = ci.begin_turn(user_id="u1", session_id="s1")
        ci.attach_source(
            c.turn_id,
            CitationSource.MEMORY,
            ref="m1",
            title="M1",
        )
        reg = SlashCommandRegistry()
        result = reg.dispatch("/why", context)
        # /why should explain the most recent turn
        assert "Explanation" in result
        assert c.turn_id[:8] in result


# -- /explain-action --------------------------------------------------------


class TestExplainActionCommand:
    def test_no_args(self, context):
        cmd = ExplainActionCommand()
        result = cmd.handle("", context)
        assert "Usage:" in result

    def test_unknown_action(self, context):
        cmd = ExplainActionCommand()
        result = cmd.handle("nope", context)
        assert "not found" in result

    def test_no_builder(self, context):
        ctx = SlashCommandContext(
            rollback_manager=context.rollback_manager,
        )
        cmd = ExplainActionCommand()
        result = cmd.handle("a1", ctx)
        assert "Explanation not configured" in result

    def test_known_action(self, context):
        rm = context.rollback_manager
        rm.record(
            tool_name="file_write",
            user_id="u1",
            undo=_undo,
            description="wrote file",
        )
        action_id = rm.history()[0].action_id
        cmd = ExplainActionCommand()
        result = cmd.handle(action_id, context)
        assert "Explanation" in result
        assert "file_write" in result

    def test_alias(self, context):
        cmd = ExplainActionCommand()
        assert "why-action" in cmd.aliases


# -- /trust-status ----------------------------------------------------------


class TestTrustStatusCommand:
    def test_full_status(self, context):
        ci = context.citation_injector
        c = ci.begin_turn(user_id="u1", session_id="s1")
        ci.attach_source(
            c.turn_id,
            CitationSource.MEMORY,
            ref="m1",
            title="M1",
        )
        cmd = TrustStatusCommand()
        result = cmd.handle("", context)
        assert "Trust subsystem status" in result
        assert "Citations:" in result
        assert "Rollback actions:" in result
        assert "Audit events:" in result

    def test_no_modules(self):
        ctx = SlashCommandContext()
        cmd = TrustStatusCommand()
        result = cmd.handle("", ctx)
        assert "not configured" in result

    def test_with_rollbacks(self, context):
        rm = context.rollback_manager
        rm.record(tool_name="t", user_id="u1", undo=_undo)
        cmd = TrustStatusCommand()
        result = cmd.handle("", context)
        assert "Rollback actions:" in result
        assert "1" in result


# -- /explain-turns ---------------------------------------------------------


class TestExplainTurnsCommand:
    def test_no_turns(self, context):
        cmd = ExplainTurnsCommand()
        result = cmd.handle("", context)
        assert "No turns yet" in result

    def test_with_turns(self, context):
        ci = context.citation_injector
        c1 = ci.begin_turn(user_id="u1", session_id="s1")
        c2 = ci.begin_turn(user_id="u2", session_id="s1")
        cmd = ExplainTurnsCommand()
        result = cmd.handle("", context)
        assert "Recent turns" in result
        assert c1.turn_id[:8] in result
        assert c2.turn_id[:8] in result

    def test_no_injector(self):
        ctx = SlashCommandContext()
        cmd = ExplainTurnsCommand()
        result = cmd.handle("", ctx)
        assert "not configured" in result

    def test_limit(self, context):
        ci = context.citation_injector
        for i in range(5):
            ci.begin_turn(user_id=f"u{i}", session_id="s1")
        cmd = ExplainTurnsCommand(limit=3)
        result = cmd.handle("", context)
        lines = [line for line in result.split("\n") if line.startswith("- ")]
        assert len(lines) == 3


# -- run_command -----------------------------------------------------------


class TestRunCommand:
    def test_explain(self, context):
        ci = context.citation_injector
        c = ci.begin_turn(user_id="u1", session_id="s1")
        ci.attach_source(
            c.turn_id,
            CitationSource.MEMORY,
            ref="m1",
            title="M1",
        )
        result = run_command("/explain", context=context)
        assert "Explanation" in result

    def test_unknown(self, context):
        result = run_command("/nope", context=context)
        assert "Unknown command" in result
        assert "Available:" in result

    def test_default_context(self):
        # No context passed — uses default
        result = run_command("/trust-status")
        # All modules not configured → "not configured" messages
        assert "not configured" in result

    def test_custom_registry(self, context):
        reg = SlashCommandRegistry(include_defaults=False)
        reg.register(ExplainCommand())
        result = run_command("/explain", context=context, registry=reg)
        # No turns in the citation_injector
        assert "No turns available" in result


# -- singletons -------------------------------------------------------------


class TestSingletons:
    def test_get_default(self):
        reg = get_default_command_registry()
        assert isinstance(reg, SlashCommandRegistry)

    def test_set_default(self):
        custom = SlashCommandRegistry(include_defaults=False)
        set_default_command_registry(custom)
        assert get_default_command_registry() is custom

    def test_reset(self):
        reg1 = get_default_command_registry()
        reset_default_command_registry()
        reg2 = get_default_command_registry()
        assert reg2 is not reg1

    def test_set_none_clears(self):
        set_default_command_registry(None)
        # After clear, next get creates a fresh one
        assert get_default_command_registry() is not None


# -- integration: explain + builder + injector ----------------------------


class TestIntegration:
    def test_full_flow(self, context):
        """End-to-end: attach a citation, run /explain, verify the report."""
        ci = context.citation_injector
        c = ci.begin_turn(user_id="u1", session_id="s1")
        ci.attach_source(
            c.turn_id,
            CitationSource.MEMORY,
            ref="m1",
            title="User's Q2 OKR",
        )
        ci.attach_source(
            c.turn_id,
            CitationSource.WEB,
            ref="https://acme.com",
            title="Acme Q2",
        )
        # End the turn
        ci.end_turn(c.turn_id)
        # Run /explain
        result = run_command("/explain", context=context)
        # Verify the report includes both citations
        assert "User's Q2 OKR" in result
        assert "Acme Q2" in result
        assert "trusted" in result

    def test_explain_specific_turn_id(self, context):
        ci = context.citation_injector
        c1 = ci.begin_turn(user_id="u1", session_id="s1")
        ci.attach_source(
            c1.turn_id,
            CitationSource.MEMORY,
            ref="m1",
            title="First",
        )
        c2 = ci.begin_turn(user_id="u1", session_id="s1")
        ci.attach_source(
            c2.turn_id,
            CitationSource.MEMORY,
            ref="m2",
            title="Second",
        )
        # Explain c1 specifically
        result = run_command(f"/explain {c1.turn_id}", context=context)
        assert "First" in result
        assert "Second" not in result
