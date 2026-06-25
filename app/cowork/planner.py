"""Cowork planner strategies — how a goal becomes a Plan.

The planner is a pure async function that takes the session +
the workspace (for context) and returns a :class:`app.cowork.plan.Plan`.
Two strategies ship in-tree:

* :class:`RulePlanner` — a small, dependency-free mapper that
  recognises a handful of verbs (``list``, ``find <q>``,
  ``read <path>``) and produces a 1-step plan.  Useful as the
  default when no LLM is configured or when the user just wants
  to poke around.

* :class:`LLMPlanner` — calls the configured LLM via
  :func:`app.provider.factory.create_provider` with a structured
  prompt that asks the model to emit JSON of the form::

      {
        "title": "...",
        "summary": "...",
        "steps": [
          {
            "title": "...",
            "description": "...",
            "action": "list|read_file|search|write_file|apply_patch|run_shell",
            "args": {...},
            "target_paths": ["..."],
            "risk": "low|medium|high",
            "depends_on": ["step_id"]
          },
          ...
        ]
      }

  The JSON is parsed by :func:`parse_plan_from_json` which
  validates every step's action against the executor's allow-list
  and clamps risk to the supported set.  Unknown actions are
  rejected so a malicious / sloppy model can't make the worker
  run arbitrary code.

Adding a new strategy is just a matter of writing another
function with the same signature; the manager accepts the
strategy name as a string and dispatches by attribute lookup.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Awaitable, Callable, Protocol

from app.cowork.plan import Plan, PlanStep, StepStatus
from app.cowork.session import CoworkSession
from app.cowork.workspace import Workspace

logger = logging.getLogger(__name__)


# Action allow-list.  Mirrors the cases in
# :func:`app.cowork.worker.default_executor` so an LLM cannot
# generate steps the worker doesn't know how to run.
ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {"list", "read_file", "search", "write_file", "apply_patch", "run_shell"}
)
RISK_LEVELS: frozenset[str] = frozenset({"low", "medium", "high"})


# ── Protocol ────────────────────────────────────────────────────


class PlannerStrategy(Protocol):
    """A planner turns a goal into a :class:`Plan`.

    The worker calls :meth:`CoworkWorker.propose_plan` which
    delegates to whichever strategy the manager picked.  A
    strategy is just an async function:

        async def plan(goal, workspace, session) -> Plan: ...
    """

    async def __call__(
        self,
        goal: str,
        workspace: Workspace,
        session: CoworkSession,
    ) -> Plan: ...


PlannerFn = Callable[[str, Workspace, CoworkSession], Awaitable[Plan]]


# ── Rule-based planner (default) ────────────────────────────────


async def rule_plan(goal: str, workspace: Workspace, session: CoworkSession) -> Plan:
    """Small rule-based mapper.  v1 of the planner.

    Recognised prefixes (case-insensitive):

    * ``list``     → list workspace root
    * ``find <q>`` → grep ``<q>`` across ``**/*``
    * ``search <q>``→ same as find
    * ``read <path>`` → read that path

    Anything else falls through to a 2-step "summarise" plan:
    list + search for README files.
    """
    plan = Plan(id=uuid.uuid4().hex[:12], goal=session.goal)
    goal_lc = goal.strip().lower()

    if goal_lc.startswith("list"):
        plan.steps.append(
            PlanStep(
                id=uuid.uuid4().hex[:10],
                title="List contents of workspace",
                description="Recursively list every entry in the granted workspace.",
                action="list",
                args={"path": "."},
                risk="low",
            )
        )
        return plan

    if goal_lc.startswith(("find ", "search ")):
        query = goal_lc.split(" ", 1)[1] if " " in goal_lc else ""
        plan.steps.append(
            PlanStep(
                id=uuid.uuid4().hex[:10],
                title=f"Search for {query!r}",
                description=f"Grep every file in the workspace for the substring {query!r}.",
                action="search",
                args={"query": query, "glob": "**/*"},
                risk="low",
            )
        )
        return plan

    if goal_lc.startswith("read "):
        path = goal_lc.split(" ", 1)[1] if " " in goal_lc else ""
        plan.steps.append(
            PlanStep(
                id=uuid.uuid4().hex[:10],
                title=f"Read {path}",
                description=f"Read the contents of {path} and return them to the user.",
                action="read_file",
                args={"path": path},
                target_paths=[path],
                risk="low",
            )
        )
        return plan

    plan.steps.append(
        PlanStep(
            id=uuid.uuid4().hex[:10],
            title="List workspace",
            description="List the workspace top-level entries.",
            action="list",
            args={"path": "."},
            risk="low",
        )
    )
    plan.steps.append(
        PlanStep(
            id=uuid.uuid4().hex[:10],
            title="Summarise",
            description=(
                "Walk the workspace and produce a short summary of the project: "
                "what it is, what languages / frameworks it uses, and the "
                "entry points a developer should read first."
            ),
            action="search",
            args={"query": "", "glob": "**/README*"},
            risk="low",
        )
    )
    plan.notes = (
        "Generated by the rule-based default planner.  Use an LLM planner "
        "to decompose complex goals into richer multi-step plans."
    )
    return plan


class RulePlanner:
    """Wraps :func:`rule_plan` so it can be referenced by class name."""

    name = "default"

    async def __call__(self, goal: str, workspace: Workspace, session: CoworkSession) -> Plan:
        return await rule_plan(goal, workspace, session)


# ── JSON parsing helpers ──────────────────────────────────────────


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_plan_from_json(payload: str) -> Plan:
    """Parse an LLM response into a :class:`Plan`.

    The LLM is asked to emit a fenced JSON block (or just JSON).
    We try, in order:

    1. Match ``\\`\\`\\`json ... \\`\\`\\`\\` fenced block.
    2. First ``{...}`` balanced JSON object in the response.
    3. The whole string as JSON.

    Every step is validated: ``action`` must be in
    :data:`ALLOWED_ACTIONS` and ``risk`` must be in
    :data:`RISK_LEVELS`.  Anything else raises :class:`ValueError`
    — the caller (LLM planner) catches and returns a 1-step
    fallback plan so the session can still run with the rule
    planner's output.
    """
    raw = payload.strip()
    obj: Any = None
    fence = _FENCE_RE.search(raw)
    if fence:
        obj = json.loads(fence.group(1))
    else:
        # First balanced { ... } in the string.
        try:
            start = raw.index("{")
            depth = 0
            for i in range(start, len(raw)):
                ch = raw[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        obj = json.loads(raw[start : i + 1])
                        break
        except (ValueError, json.JSONDecodeError):
            obj = None
    if obj is None:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("planner LLM response contained no parseable JSON object")

    if not isinstance(obj, dict):
        raise ValueError("planner JSON must be an object at the top level")

    steps_in = obj.get("steps")
    if not isinstance(steps_in, list) or not steps_in:
        raise ValueError("planner JSON must contain a non-empty 'steps' array")

    plan = Plan(
        id=uuid.uuid4().hex[:12],
        goal=str(obj.get("summary") or obj.get("title") or ""),
    )
    plan.notes = (
        "Generated by the LLM planner.  Inspect each step's risk + action "
        "before approving."
    )
    if isinstance(obj.get("title"), str):
        plan.title = obj["title"]
    if isinstance(obj.get("rationale"), str):
        plan.notes = obj["rationale"]

    step_ids: list[str] = []
    for raw_step in steps_in:
        if not isinstance(raw_step, dict):
            raise ValueError("every step must be a JSON object")
        action = str(raw_step.get("action") or "").strip()
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"planner emitted disallowed action: {action!r}")
        risk = str(raw_step.get("risk") or "low").strip().lower()
        if risk not in RISK_LEVELS:
            risk = "low"
        args = raw_step.get("args") or {}
        if not isinstance(args, dict):
            args = {"value": args}
        target_paths = raw_step.get("target_paths") or []
        if not isinstance(target_paths, list):
            target_paths = []
        depends_on = raw_step.get("depends_on") or []
        if not isinstance(depends_on, list):
            depends_on = []
        step_id = uuid.uuid4().hex[:10]
        step_ids.append(step_id)
        plan.steps.append(
            PlanStep(
                id=step_id,
                title=str(raw_step.get("title") or f"Step {len(plan.steps) + 1}"),
                description=str(raw_step.get("description") or ""),
                action=action,
                args={k: _jsonable(v) for k, v in args.items()},
                target_paths=[str(p) for p in target_paths if isinstance(p, (str, int))],
                risk=risk,
                depends_on=[str(d) for d in depends_on if isinstance(d, (str, int))],
                status=StepStatus.PENDING,
            )
        )
    return plan


def _jsonable(v: Any) -> Any:
    """Coerce *v* to something the executor's args dict expects."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return str(v)


# ── LLM planner ──────────────────────────────────────────────────


SYSTEM_PROMPT = """You are RAVEN, an autonomous coding assistant.
A user has granted you access to a workspace directory.  Break their
goal into a sequence of small, concrete steps that can be executed
with the limited action set below.

Rules
-----
1. Only emit actions from this allow-list (no others):
       list, read_file, search, write_file, apply_patch, run_shell
2. Every step's ``args`` must be a JSON object.  Use the schema
   below for each action.
3. Set ``risk`` to:
       - "low"    for read-only actions (list / read_file / search)
       - "medium" for writes that are reversible or restricted
       - "high"   for writes outside the project, shell commands,
                  or any action touching .env / secrets / git config
4. Use ``depends_on`` only when a step strictly needs the output
   of a previous step; otherwise omit it.
5. Prefer 1-6 steps.  If the goal is vague, propose a small
   exploratory plan (list + read top-level files) and stop.
6. Output ONLY a JSON object — no prose before or after.  Wrap it
   in a single ```json fenced block.

Action schemas
--------------
list:       {"path": "relative/under/workspace"}
read_file:  {"path": "relative/under/workspace"}
search:     {"query": "substring", "glob": "**/*"}
write_file: {"path": "rel/file", "content": "full file contents"}
apply_patch:{"path": "rel/file", "patch": "unified diff or full new content"}
run_shell:  {"command": "shell command", "timeout_s": 30}
"""

USER_TEMPLATE = """Goal: {goal}

Workspace root: {workspace_path}
Access mode: {access_mode}
Denied globs: {deny_globs}

{files_hint}

Return the JSON plan now."""


class LLMPlanner:
    """Calls the configured LLM to generate a :class:`Plan`.

    The provider is resolved via :func:`app.core.model_router.AutoModelRouter`
    so the 9router-style combos are honoured.  If the LLM call
    fails or returns unparseable JSON we fall back to
    :class:`RulePlanner` so the session can still run.
    """

    name = "llm"

    def __init__(
        self,
        *,
        planner: PlannerFn | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        max_files_hint: int = 25,
    ) -> None:
        self._override_planner = planner
        self._provider_name = provider_name
        self._model_name = model_name
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_files_hint = max_files_hint

    async def __call__(
        self,
        goal: str,
        workspace: Workspace,
        session: CoworkSession,
    ) -> Plan:
        if self._override_planner is not None:
            try:
                return await self._override_planner(goal, workspace, session)
            except Exception as exc:  # noqa: BLE001
                logger.warning("override planner raised: %s", exc)
                return await RulePlanner()(goal, workspace, session)

        files_hint = self._build_files_hint(workspace)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_TEMPLATE.format(
                    goal=goal.strip(),
                    workspace_path=workspace.path,
                    access_mode=workspace.access.value,
                    deny_globs=", ".join(workspace.deny_globs) or "(none)",
                    files_hint=files_hint,
                ),
            },
        ]

        provider, model = await self._resolve_provider()
        try:
            result = await provider.chat_completion(
                model=model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM planner call failed: %s", exc)
            return await RulePlanner()(goal, workspace, session)

        if not isinstance(result, dict) or not result.get("success"):
            logger.warning(
                "LLM planner returned unsuccessful result: %s",
                result.get("error") if isinstance(result, dict) else result,
            )
            return await RulePlanner()(goal, workspace, session)

        content = result.get("content") or result.get("output") or ""
        if not isinstance(content, str) or not content.strip():
            logger.warning("LLM planner returned empty content")
            return await RulePlanner()(goal, workspace, session)

        try:
            return parse_plan_from_json(content)
        except ValueError as exc:
            logger.warning("LLM planner JSON parse failed: %s", exc)
            return await RulePlanner()(goal, workspace, session)

    async def _resolve_provider(self) -> tuple[Any, str]:
        """Pick a (provider instance, model name) tuple."""
        from app.core.model_router import AutoModelRouter
        from app.provider.factory import create_provider

        if self._provider_name and self._model_name:
            return create_provider(self._provider_name), self._model_name

        provider_name, model_name = AutoModelRouter.get_best_model("planner")
        return create_provider(provider_name), model_name

    def _build_files_hint(self, workspace: Workspace) -> str:
        """Show the LLM the top-level layout so it doesn't waste tokens
        exploring an empty directory.
        """
        import os

        try:
            entries = sorted(os.scandir(workspace.path), key=lambda e: e.name)
        except OSError as exc:
            return f"(could not list workspace: {exc})"

        lines: list[str] = []
        for i, entry in enumerate(entries):
            if i >= self._max_files_hint:
                lines.append(f"... ({len(entries) - i} more)")
                break
            if workspace.is_denied(entry.name):
                lines.append(f"- {entry.name}/  (denied)")
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                lines.append(f"- {entry.name}/")
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                lines.append(f"- {entry.name}  ({size} bytes)")
        return "Top-level entries:\n" + "\n".join(lines) if lines else "(empty workspace)"


# ── Registry ─────────────────────────────────────────────────────


_REGISTRY: dict[str, PlannerFn] = {}


def register_planner(name: str, fn: PlannerFn) -> None:
    """Register *fn* under *name*.  Overwrites if present."""
    _REGISTRY[name] = fn


def resolve_planner(name: str) -> PlannerFn:
    """Return the planner registered as *name*, or fall back to
    :class:`RulePlanner` if *name* is unknown.
    """
    if name in _REGISTRY:
        return _REGISTRY[name]
    if name == "llm":
        return LLMPlanner()
    return RulePlanner()


# Register built-ins at import time so callers don't have to.
register_planner("default", RulePlanner())
register_planner("rule", RulePlanner())
register_planner("llm", LLMPlanner())
