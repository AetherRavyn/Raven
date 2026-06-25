"""Phase F1 — Trust & Explainability: Slash commands.

Exposes the trust module's explanation export (D30) as user-facing
chat commands.  The current command set:

  * ``/explain [turn_id]``  — render the explanation report for
    a specific turn (defaults to the most recent turn).
  * ``/explain-action <action_id>``  — render the explanation
    report for a single rollback action.
  * ``/trust-status``  — show a one-line summary of the trust
    subsystem (citation count, rollback count, audit count).

All commands return :class:`str` so they can be sent verbatim
to the user.  The runtime is not required — the command
module is self-contained and can be invoked from any context.

Typical usage::

    from app.core.trust.slash_commands import run_command, SlashCommandContext

    context = SlashCommandContext(
        builder=builder,
        citation_injector=injector,
        audit_viewer=viewer,
        rollback_manager=rollback_manager,
    )
    response = run_command("/explain", context=context)
    # response: "## Explanation — turn `b34737ce`\n..."
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.trust.audit_viewer import AuditViewer
from app.core.trust.citation_runtime import CitationContext, CitationInjector
from app.core.trust.explanation import (
    ExplanationBuilder,
    ExplanationReport,
    format_explanation_markdown,
    format_explanation_text,
)
from app.core.trust.rollback import RollbackManager


# -- context ----------------------------------------------------------------


@dataclass(slots=True)
class SlashCommandContext:
    """Everything a slash command needs to do its work.

    Held in a single object so commands can be invoked with
    one parameter.  All fields are optional — commands that
    need a missing module return a friendly "not configured"
    message instead of crashing.
    """

    builder: ExplanationBuilder | None = None
    citation_injector: CitationInjector | None = None
    audit_viewer: AuditViewer | None = None
    rollback_manager: RollbackManager | None = None
    # Default format for the response: "markdown" or "text"
    default_format: str = "markdown"
    metadata: dict[str, Any] = field(default_factory=dict)


# -- command protocol -------------------------------------------------------


class SlashCommand(Protocol):
    """Interface every slash command implements.

    ``name`` is the command name without the leading slash.
    ``aliases`` are alternative names (e.g. ``"/why"`` for
    ``"/explain"``).  ``handle`` is the entry point — it
    receives the parsed argument string (empty for no args)
    and the :class:`SlashCommandContext`.
    """

    name: str
    description: str
    aliases: list[str]

    def handle(self, args: str, context: SlashCommandContext) -> str: ...


# -- helpers -----------------------------------------------------------------


def _parse_args(raw: str) -> list[str]:
    """Split a raw argument string into tokens (shell-like)."""
    return [tok for tok in raw.split() if tok]


def _resolve_turn_id(
    args: list[str],
    context: SlashCommandContext,
) -> tuple[str, str, str] | None:
    """Resolve (turn_id, user_id, session_id) from args or active context.

    If ``args`` is non-empty, the first token is treated as a
    turn_id.  Otherwise the most recent active or closed
    context is used (newest first).

    Returns ``None`` if no turn can be resolved.
    """
    if args:
        turn_id = args[0]
        # Look up the context for user_id / session_id
        if context.citation_injector is not None:
            ctx = context.citation_injector.get_context(turn_id)
            if ctx is not None:
                return turn_id, ctx.user_id, ctx.session_id
        # Unknown turn — return with empty user/session
        return turn_id, "", ""
    # No args — find the most recent context
    if context.citation_injector is None:
        return None
    all_turns = context.citation_injector.all_turns()
    if not all_turns:
        return None
    # Newest first
    latest = max(all_turns, key=lambda c: c.started_at)
    return latest.turn_id, latest.user_id, latest.session_id


def _format_report(report: ExplanationReport, fmt: str) -> str:
    """Render a report in the requested format."""
    if fmt == "text":
        return format_explanation_text(report)
    return format_explanation_markdown(report)


# -- /explain ---------------------------------------------------------------


@dataclass(slots=True)
class ExplainCommand:
    """``/explain [turn_id]`` — render the trust explanation report."""

    name: str = "explain"
    description: str = "Render the trust explanation for a turn (default: most recent)."
    aliases: list[str] = field(default_factory=lambda: ["why"])

    def handle(self, args: str, context: SlashCommandContext) -> str:
        tokens = _parse_args(args)
        resolved = _resolve_turn_id(tokens, context)
        if resolved is None:
            return (
                "No turns available.  Start a conversation first, then use "
                "`/explain` to see the trust breakdown."
            )
        turn_id, user_id, session_id = resolved
        if context.builder is None:
            return (
                "Explanation not configured: no `ExplanationBuilder` "
                "in the slash-command context.  Pass `builder=...` to "
                "`run_command`."
            )
        report = context.builder.explain_turn(
            turn_id=turn_id,
            user_id=user_id,
            session_id=session_id,
        )
        fmt = context.default_format
        return _format_report(report, fmt)


# -- /explain-action --------------------------------------------------------


@dataclass(slots=True)
class ExplainActionCommand:
    """``/explain-action <action_id>`` — explain a single rollback action."""

    name: str = "explain-action"
    description: str = "Render the explanation for a single rollback action."
    aliases: list[str] = field(default_factory=lambda: ["why-action"])

    def handle(self, args: str, context: SlashCommandContext) -> str:
        tokens = _parse_args(args)
        if not tokens:
            return "Usage: `/explain-action <action_id>`"
        action_id = tokens[0]
        if context.builder is None:
            return (
                "Explanation not configured: no `ExplanationBuilder` in the slash-command context."
            )
        report = context.builder.explain_action(action_id)
        if report is None:
            return f"Action `{action_id}` not found."
        return _format_report(report, context.default_format)


# -- /trust-status ----------------------------------------------------------


@dataclass(slots=True)
class TrustStatusCommand:
    """``/trust-status`` — one-line summary of the trust subsystem."""

    name: str = "trust-status"
    description: str = "Show citation / rollback / audit counts."
    aliases: list[str] = field(default_factory=lambda: ["trust"])

    def handle(self, args: str, context: SlashCommandContext) -> str:
        lines: list[str] = ["**Trust subsystem status**", ""]
        # Citations
        if context.citation_injector is not None:
            all_turns = context.citation_injector.all_turns()
            active = context.citation_injector.active_turns()
            total_citations = sum(len(c.citations) for c in all_turns)
            lines.append(
                f"- Citations: **{total_citations}** "
                f"across {len(all_turns)} turn(s) "
                f"({len(active)} active)"
            )
        else:
            lines.append("- Citations: _(not configured)_")
        # Rollbacks
        if context.rollback_manager is not None:
            actions = context.rollback_manager.history()
            undone = sum(1 for a in actions if a.undone)
            lines.append(f"- Rollback actions: **{len(actions)}** ({undone} undone)")
        else:
            lines.append("- Rollback actions: _(not configured)_")
        # Audits
        if context.audit_viewer is not None:
            try:
                count = context.audit_viewer.count()
            except Exception:  # noqa: BLE001
                count = "?"
            lines.append(f"- Audit events: **{count}**")
        else:
            lines.append("- Audit events: _(not configured)_")
        return "\n".join(lines)


# -- /explain-turns ---------------------------------------------------------


@dataclass(slots=True)
class ExplainTurnsCommand:
    """``/explain-turns`` — list recent turns (so users can pick one)."""

    name: str = "explain-turns"
    description: str = "List recent turns the user can /explain."
    aliases: list[str] = field(default_factory=lambda: ["turns"])
    limit: int = 10

    def handle(self, args: str, context: SlashCommandContext) -> str:
        if context.citation_injector is None:
            return "Citation injector not configured."
        all_turns = context.citation_injector.all_turns()
        if not all_turns:
            return "No turns yet."
        # Newest first
        sorted_turns = sorted(
            all_turns,
            key=lambda c: c.started_at,
            reverse=True,
        )
        lines: list[str] = ["**Recent turns**", ""]
        for c in sorted_turns[: self.limit]:
            n = len(c.citations)
            status = "active" if not c.is_closed() else "closed"
            lines.append(
                f"- `{c.turn_id[:8]}` ({c.started_at.isoformat()}) — {n} citation(s) — *{status}*"
            )
        return "\n".join(lines)


# -- /cron (Phase 5 v13) --------------------------------------------------


@dataclass(slots=True)
class CronCommand:
    """``/cron [list|add|remove|toggle] [...]`` — manage the dynamic
    :class:`CronEngine` schedule.

    Sub-commands:

    * ``/cron`` or ``/cron list`` — render the current schedule.
    * ``/cron add <id> <HH:MM> <name>`` — register a new
      ``daily_at`` job.  The action description defaults to
      the job name.
    * ``/cron remove <id>`` — remove a job by id.
    * ``/cron toggle <id>`` — flip the enabled flag on a job.

    The command is self-contained: it instantiates
    :class:`CronEngine` on demand and does not depend on the
    context (the engine reads ``MEMORY_ROOT`` from
    :class:`Config`).  Tests that need a private
    ``MEMORY_ROOT`` should monkeypatch ``Config.MEMORY_ROOT``
    before invoking the command.
    """

    name: str = "cron"
    description: str = "List, add, remove, or toggle dynamic cron jobs."
    aliases: list[str] = field(default_factory=lambda: ["schedule"])

    def handle(self, args: str, context: SlashCommandContext) -> str:
        try:
            from app.core.cron_engine import CronEngine
        except Exception as exc:  # noqa: BLE001 - optional
            return f"CronEngine not available: {exc}"

        tokens = _parse_args(args)
        sub = tokens[0] if tokens else "list"
        rest = tokens[1:]

        try:
            engine = CronEngine()
        except Exception as exc:  # noqa: BLE001 - init failure
            return f"CronEngine init failed: {exc}"

        if sub in {"list", "ls", ""}:
            return self._list(engine)
        if sub == "add":
            return self._add(engine, rest)
        if sub in {"remove", "rm", "delete"}:
            return self._remove(engine, rest)
        if sub in {"toggle", "on", "off"}:
            return self._toggle(engine, rest)
        return (
            f"Unknown cron sub-command `{sub}`. "
            "Try: list, add, remove, toggle."
        )

    @staticmethod
    def _list(engine: Any) -> str:
        jobs = engine.get_jobs()
        if not jobs:
            return "No cron jobs registered."
        lines: list[str] = ["**Cron schedule**", ""]
        for j in jobs:
            jid = j.get("job_id", "?")
            name = j.get("name", "?")
            schedule = j.get("schedule_type", "?")
            enabled = "ON" if j.get("enabled", False) else "OFF"
            if schedule == "daily_at":
                when = j.get("time", "??:??")
                sched_str = f"daily @ {when}"
            elif schedule == "interval_minutes":
                when = j.get("interval", "?")
                sched_str = f"every {when}m"
            else:
                sched_str = f"({schedule})"
            lines.append(f"- `{jid}` **{name}** — {sched_str} — *{enabled}*")
        return "\n".join(lines)

    @staticmethod
    def _add(engine: Any, args: list[str]) -> str:
        if len(args) < 3:
            return (
                "Usage: `/cron add <id> <HH:MM> <name>` "
                "(or `/cron add <id> every <minutes> <name>`)"
            )
        job_id, when, name = args[0], args[1], " ".join(args[2:])
        if when.lower() == "every" and len(args) >= 4:
            try:
                interval = int(args[2])
            except ValueError:
                return f"Invalid interval: {args[2]}"
            name = " ".join(args[3:])
            result = engine.add_job(
                job_id=job_id,
                name=name,
                description=name,
                schedule_type="interval_minutes",
                action_description=name,
                interval=interval,
            )
        elif ":" in when:
            result = engine.add_job(
                job_id=job_id,
                name=name,
                description=name,
                schedule_type="daily_at",
                action_description=name,
                time_str=when,
            )
        else:
            return f"Unrecognised schedule `{when}` — use HH:MM or `every <minutes>`."
        if not result.get("success"):
            return f"Cron add failed: {result.get('error', 'unknown error')}"
        return f"Added cron job `{job_id}` (`{name}`)."

    @staticmethod
    def _remove(engine: Any, args: list[str]) -> str:
        if not args:
            return "Usage: `/cron remove <id>`"
        ok = engine.remove_job(args[0])
        if not ok:
            return f"No cron job with id `{args[0]}`."
        return f"Removed cron job `{args[0]}`."

    @staticmethod
    def _toggle(engine: Any, args: list[str]) -> str:
        if not args:
            return "Usage: `/cron toggle <id>`"
        ok = engine.toggle_job(args[0])
        if not ok:
            return f"No cron job with id `{args[0]}`."
        return f"Toggled cron job `{args[0]}`."


# -- registry ---------------------------------------------------------------


_DEFAULT_COMMANDS: list[SlashCommand] = [
    ExplainCommand(),
    ExplainActionCommand(),
    TrustStatusCommand(),
    ExplainTurnsCommand(),
    CronCommand(),
]


class SlashCommandRegistry:
    """Holds the registered slash commands and dispatches by name.

    Thread-safe.  Built-in commands are registered on first
    access; user commands can be added with :meth:`register`.
    """

    def __init__(self, *, include_defaults: bool = True) -> None:
        self._lock = threading.RLock()
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}
        if include_defaults:
            for cmd in _DEFAULT_COMMANDS:
                self.register(cmd)

    def register(self, command: SlashCommand) -> None:
        """Register a command.  Replaces any existing command with the same name."""
        with self._lock:
            self._commands[command.name] = command
            for alias in command.aliases:
                self._aliases[alias] = command.name

    def unregister(self, name: str) -> bool:
        """Remove a command by name.  Returns True if removed."""
        with self._lock:
            cmd = self._commands.pop(name, None)
            if cmd is None:
                return False
            # Drop aliases
            for alias in list(self._aliases):
                if self._aliases[alias] == name:
                    del self._aliases[alias]
            return True

    def get(self, name: str) -> SlashCommand | None:
        """Look up a command by name or alias."""
        with self._lock:
            if name in self._commands:
                return self._commands[name]
            canonical = self._aliases.get(name)
            if canonical is not None:
                return self._commands.get(canonical)
            return None

    def all(self) -> list[SlashCommand]:
        """Return every registered command."""
        with self._lock:
            return list(self._commands.values())

    def names(self) -> list[str]:
        """Return every registered name (primary only, not aliases)."""
        with self._lock:
            return list(self._commands.keys())

    def dispatch(self, raw: str, context: SlashCommandContext) -> str | None:
        """Dispatch a raw command string to its handler.

        ``raw`` is the full command (e.g. ``"/explain t1"``).
        Returns the handler's response, or ``None`` if the
        command is not recognised.
        """
        if not raw.startswith("/"):
            return None
        parts = raw[1:].split(maxsplit=1)
        if not parts:
            return None
        name = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        cmd = self.get(name)
        if cmd is None:
            return None
        return cmd.handle(args, context)


# -- module-level singleton -------------------------------------------------


_DEFAULT_REGISTRY: SlashCommandRegistry | None = None
_LOCK = threading.RLock()


def get_default_command_registry() -> SlashCommandRegistry:
    """Return the process-singleton :class:`SlashCommandRegistry`."""
    global _DEFAULT_REGISTRY
    with _LOCK:
        if _DEFAULT_REGISTRY is None:
            _DEFAULT_REGISTRY = SlashCommandRegistry()
        return _DEFAULT_REGISTRY


def set_default_command_registry(registry: SlashCommandRegistry | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_REGISTRY
    with _LOCK:
        _DEFAULT_REGISTRY = registry


def reset_default_command_registry() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_REGISTRY
    with _LOCK:
        _DEFAULT_REGISTRY = None


def run_command(
    raw: str,
    *,
    context: SlashCommandContext | None = None,
    registry: SlashCommandRegistry | None = None,
) -> str:
    """Run a slash command and return its response.

    Convenience wrapper around
    :meth:`SlashCommandRegistry.dispatch` with the
    process-singleton registry as default.

    Returns a user-friendly "unknown command" message
    if the command is not registered.
    """
    ctx = context or SlashCommandContext()
    reg = registry or get_default_command_registry()
    result = reg.dispatch(raw, ctx)
    if result is None:
        # Friendly unknown-command message with a hint of what's available
        names = ", ".join(f"`/{n}`" for n in sorted(reg.names()))
        return f"Unknown command `{raw.split(maxsplit=1)[0]}`.  Available: {names}."
    return result


__all__ = [
    "CronCommand",
    "ExplainActionCommand",
    "ExplainCommand",
    "ExplainTurnsCommand",
    "SlashCommand",
    "SlashCommandContext",
    "SlashCommandRegistry",
    "TrustStatusCommand",
    "get_default_command_registry",
    "reset_default_command_registry",
    "run_command",
    "set_default_command_registry",
]


# Re-exports kept import-visible for type-checkers.
_ = (CitationContext,)
