"""Cowork worker — runs a plan step-by-step, emits events, supports pause/stop.

Design
------
The worker is an async coroutine owned by one session at a time.
It does **not** invent actions or call LLMs directly — that is the
planner's job.  The worker is the executor:

  * resolves the next step to run
  * checks approval state
  * executes the step's action (delegating to existing RAVEN
    tools via :mod:`app.tools.filetool` etc., with the workspace
    grant enforced as a security boundary)
  * computes the file diff
  * emits events on :data:`COWORK_TOPIC`
  * records results in the session
  * waits for the user to approve the next step (if needed)
  * supports pause / resume / stop via :class:`asyncio.Event` flags

The worker is intentionally small.  Step execution for ``read_file``
/ ``write_file`` / ``apply_patch`` is implemented here so the MVP
works without a planner.  ``run_shell`` is delegated to the
existing :class:`app.tools.exectool.ExecTool` (bubblewrap sandbox).
The planner hook is an injection point — the dashboard's "Propose
plan" button calls :func:`CoworkWorker.propose_plan` with a goal
and a strategy that generates a plan; v1 uses a simple rule-based
strategy (grep, list, summarise), v2 will swap in an LLM planner.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.cowork.diff import compute_file_diff
from app.cowork.plan import Plan, PlanStep, StepStatus
from app.cowork.planner import PlannerFn, resolve_planner
from app.cowork.session import (
    COWORK_TOPIC,
    CoworkEvent,
    CoworkSession,
    SessionState,
)

logger = logging.getLogger(__name__)


# Default deny globs for new workspaces.  Conservative — the user
# can override per-workspace.
DEFAULT_DENY_GLOBS: list[str] = [
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    ".git/config",
    "id_rsa",
    "id_rsa.*",
    "**/secrets.*",
]


# ── Step executor ────────────────────────────────────────────────
# A Strategy is a function that takes (session, step) and either
# returns the new step (with status updated) or raises.  The
# default strategy covers read / write / patch / search / shell.
# A planner-LLM strategy can be injected for richer plans.

StepExecutor = Callable[["CoworkWorker", PlanStep], Awaitable[PlanStep]]


async def default_executor(worker: "CoworkWorker", step: PlanStep) -> PlanStep:
    """Built-in executor for the basic action set.

    Returns the step with its ``status`` / ``result`` / ``error``
    fields populated.
    """
    session = worker._session
    assert session is not None, "default_executor called without attached session"
    workspace = worker._store.workspaces.get(session.workspace_id)
    if workspace is None:
        step.status = StepStatus.FAILED
        step.error = "workspace not found"
        return step
    args = step.args
    action = step.action

    try:
        if action == "read_file":
            path = args.get("path", "")
            ok, reason = workspace.authorise(path, write=False)
            if not ok:
                raise PermissionError(reason)
            abs_path = os.path.join(workspace.path, path)
            with open(abs_path, encoding="utf-8") as f:
                text = f.read()
            step.result = {"path": path, "text": text, "size": len(text)}
            return step

        if action == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")
            ok, reason = workspace.authorise(path, write=True)
            if not ok:
                raise PermissionError(reason)
            abs_path = os.path.join(workspace.path, path)
            old = ""
            if os.path.exists(abs_path):
                with open(abs_path, encoding="utf-8") as f:
                    old = f.read()
            os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            d = compute_file_diff(path, old, content)
            step.result = {
                "path": path,
                "diff": d.to_dict(),
                "size": len(content),
            }
            worker._store.append_event(
                CoworkEvent(
                    session_id=session.id,
                    kind="diff_ready",
                    payload={"step_id": step.id, "path": path, "stats": d.stats()},
                )
            )
            return step

        if action == "apply_patch":
            path = args.get("path", "")
            patch = args.get("patch", "")
            ok, reason = workspace.authorise(path, write=True)
            if not ok:
                raise PermissionError(reason)
            abs_path = os.path.join(workspace.path, path)
            old = ""
            if os.path.exists(abs_path):
                with open(abs_path, encoding="utf-8") as f:
                    old = f.read()
            # Minimal unified-diff applier — for the MVP the
            # "patch" is treated as a full new file content.  v2
            # will wire in `pathchtool.ApplyPatchTool`.
            new = patch if patch and not patch.startswith("---") else old
            if not os.path.exists(abs_path):
                os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new)
            d = compute_file_diff(path, old, new)
            step.result = {"path": path, "diff": d.to_dict()}
            worker._store.append_event(
                CoworkEvent(
                    session_id=session.id,
                    kind="diff_ready",
                    payload={"step_id": step.id, "path": path, "stats": d.stats()},
                )
            )
            return step

        if action == "search":
            query = args.get("query", "")
            glob = args.get("glob", "**/*")
            root = Path(workspace.path)
            matches: list[dict[str, Any]] = []
            for p in root.glob(glob):
                if not p.is_file():
                    continue
                if workspace.is_denied(str(p)):
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if query in line:
                        matches.append(
                            {
                                "path": str(p.relative_to(root)),
                                "lineno": lineno,
                                "line": line[:200],
                            }
                        )
                        if len(matches) >= 200:
                            break
                if len(matches) >= 200:
                    break
            step.result = {"query": query, "matches": matches, "count": len(matches)}
            return step

        if action == "list":
            rel = args.get("path", ".")
            abs_path = os.path.join(workspace.path, rel)
            if not workspace.is_within(abs_path):
                raise PermissionError(f"path {rel!r} is outside the granted workspace")
            entries: list[dict[str, Any]] = []
            for entry in sorted(os.scandir(abs_path), key=lambda e: e.name):
                entries.append(
                    {
                        "name": entry.name,
                        "path": os.path.relpath(entry.path, workspace.path),
                        "is_dir": entry.is_dir(),
                        "size": entry.stat().st_size if entry.is_file() else 0,
                    }
                )
            step.result = {"path": rel, "entries": entries, "count": len(entries)}
            return step

        if action == "run_shell":
            try:
                from app.tools.exectool import ExecTool
            except ImportError as exc:
                raise RuntimeError(f"exec tool unavailable: {exc}") from exc
            command = args.get("command", "")
            timeout_s = int(args.get("timeout_s", 60))
            tool = ExecTool(default_workdir=workspace.path)
            result = await tool.execute(
                command=command, workdir=workspace.path, timeout=timeout_s,
            )
            step.result = result
            return step

        raise ValueError(f"unknown action: {action!r}")
    except Exception as exc:  # noqa: BLE001
        step.status = StepStatus.FAILED
        step.error = str(exc)[:300]
        return step


class CoworkWorker:
    """Runs a :class:`CoworkSession` to completion (or pause / stop)."""

    def __init__(
        self,
        store: Any,  # CoworkStore (avoid import cycle in tests)
        bus: Any,  # InProcBus
        executor: StepExecutor = default_executor,
    ) -> None:
        self._store = store
        self._bus = bus
        self._executor = executor
        self._session: CoworkSession | None = None
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # not paused
        self._approval_event = asyncio.Event()  # signals "user approved a step"
        self._current_step_id: str | None = None

    # ── session control ──────────────────────────────────────────

    def attach(self, session: CoworkSession) -> None:
        self._session = session
        self._stop_event.clear()
        if session.state != SessionState.PAUSED:
            self._pause_event.set()

    def request_stop(self) -> None:
        self._stop_event.set()
        self._pause_event.set()  # unblock if paused
        self._approval_event.set()  # unblock if waiting

    def request_pause(self) -> None:
        self._pause_event.clear()

    def request_resume(self) -> None:
        self._pause_event.set()
        self._approval_event.set()

    def approve_step(self, step_id: str) -> None:
        if self._current_step_id == step_id:
            self._approval_event.set()

    def reject_step(self, step_id: str, reason: str = "") -> None:
        if self._current_step_id == step_id:
            self._approval_event.set()
            # The session will pick up the rejection on next loop
            # via the step's status; we just unblock the wait.

    # ── main loop ────────────────────────────────────────────────

    async def run(self) -> None:
        """Execute the attached session until done / failed / stopped.

        The coroutine yields between steps so the dashboard SSE
        endpoint and Tauri shell can interleave events.
        """
        if self._session is None:
            raise RuntimeError("worker has no session; call attach() first")
        session = self._session
        if session.plan is None:
            session.state = SessionState.FAILED
            session.error = "no plan attached"
            self._store.sessions.upsert(session)
            return

        session.state = SessionState.EXECUTING
        self._store.sessions.upsert(session)
        self._emit(session.id, "session_resumed" if session.cursor else "session_started")

        steps = session.plan.steps
        try:
            for idx in range(session.cursor, len(steps)):
                if self._stop_event.is_set():
                    session.state = SessionState.STOPPED
                    break
                await self._wait_if_paused()
                step = steps[idx]
                session.cursor = idx + 1
                self._current_step_id = step.id

                if step.status in {StepStatus.SKIPPED, StepStatus.REJECTED, StepStatus.DONE}:
                    continue

                # Approval gate (unless plan was bulk-approved)
                if not session.plan.approved_all and step.status in {
                    StepStatus.PENDING,
                    StepStatus.AWAITING_APPROVAL,
                }:
                    step.status = StepStatus.AWAITING_APPROVAL
                    self._store.sessions.upsert(session)
                    self._emit(
                        session.id,
                        "approval_needed",
                        {"step_id": step.id, "title": step.title, "risk": step.risk},
                    )
                    self._approval_event.clear()
                    await self._wait_for_approval()
                    if self._stop_event.is_set():
                        session.state = SessionState.STOPPED
                        break
                    if step.status == StepStatus.REJECTED:
                        self._emit(
                            session.id,
                            "step_rejected",
                            {"step_id": step.id},
                        )
                        continue
                    if step.status != StepStatus.APPROVED:
                        step.status = StepStatus.APPROVED

                # Execute
                step.status = StepStatus.RUNNING
                step.started_at = time.time()
                self._store.sessions.upsert(session)
                self._emit(
                    session.id,
                    "step_started",
                    {"step_id": step.id, "title": step.title, "action": step.action},
                )
                await asyncio.sleep(0)  # let UI catch up
                step = await self._executor(self, step)
                step.finished_at = time.time()
                if step.status != StepStatus.FAILED:
                    step.status = StepStatus.DONE
                self._store.sessions.upsert(session)
                self._emit(
                    session.id,
                    "step_done" if step.status == StepStatus.DONE else "step_failed",
                    {
                        "step_id": step.id,
                        "result_summary": _summarise_result(step.result),
                        "error": step.error,
                    },
                )
                await asyncio.sleep(0)
            else:
                # Loop completed without break.
                session.state = SessionState.DONE
                self._emit(session.id, "session_done")
        except Exception as exc:  # noqa: BLE001
            session.state = SessionState.FAILED
            session.error = str(exc)[:300]
            self._emit(session.id, "session_failed", {"error": session.error})
        finally:
            self._store.sessions.upsert(session)

    async def _wait_if_paused(self) -> None:
        while not self._pause_event.is_set():
            if self._stop_event.is_set():
                return
            if self._session is not None and self._session.state != SessionState.PAUSED:
                self._session.state = SessionState.PAUSED
                self._store.sessions.upsert(self._session)
                self._emit(self._session.id, "session_paused")
            await asyncio.sleep(0.1)
        if self._session is not None and self._session.state == SessionState.PAUSED:
            self._session.state = SessionState.EXECUTING
            self._store.sessions.upsert(self._session)
            self._emit(self._session.id, "session_resumed")

    async def _wait_for_approval(self) -> None:
        """Block until the user approves/rejects the current step or stops."""
        await self._approval_event.wait()

    # ── plan proposal ────────────────────────────────────────────

    async def propose_plan(
        self,
        session: CoworkSession,
        *,
        strategy: str = "default",
        planner: PlannerFn | None = None,
    ) -> Plan:
        """Generate a plan for *session* using *strategy*.

        The default strategy is the rule-based planner in
        :mod:`app.cowork.planner`.  Pass ``strategy="llm"`` to
        have the planner call the configured LLM via
        :class:`app.cowork.planner.LLMPlanner`.  Pass a custom
        *planner* to inject your own strategy (used by tests).
        """
        workspace = self._store.workspaces.get(session.workspace_id)
        if workspace is None:
            raise ValueError(f"workspace not found: {session.workspace_id}")

        chosen = planner or resolve_planner(strategy)
        plan = await chosen(session.goal, workspace, session)
        plan.goal = session.goal

        session.plan = plan
        session.state = SessionState.AWAITING_APPROVAL
        self._store.sessions.upsert(session)
        self._emit(
            session.id,
            "plan_proposed",
            {
                "plan_id": plan.id,
                "steps": len(plan.steps),
                "strategy": strategy,
            },
        )
        return plan

    # ── emit helper ─────────────────────────────────────────────

    def _emit(self, session_id: str, kind: str, payload: dict[str, Any] | None = None) -> None:
        event = CoworkEvent(
            session_id=session_id, kind=kind, payload=payload or {},
        )
        self._store.append_event(event)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._bus.publish(COWORK_TOPIC, event.to_dict()))
        except RuntimeError:
            # No running loop (test) — fall back to sync publish.
            asyncio.run(self._bus.publish(COWORK_TOPIC, event.to_dict()))


def _summarise_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, dict):
        if "matches" in result:
            return f"{result.get('count', 0)} matches"
        if "entries" in result:
            return f"{result.get('count', 0)} entries"
        if "diff" in result:
            stats = result["diff"].get("stats", {})
            return f"+{stats.get('added', 0)} -{stats.get('removed', 0)}"
        if "text" in result:
            return f"{result.get('size', 0)} chars"
        return f"{len(result)} keys"
    return str(result)[:80]
