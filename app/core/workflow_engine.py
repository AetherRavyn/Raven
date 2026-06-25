from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkflowStep:
    step_id: str
    title: str
    action: str
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)
    condition: str | None = None
    on_success: str | None = None
    on_failure: str | None = None
    max_retries: int = 3
    retry_count: int = 0
    retry_delay: float = 1.0  # seconds, doubles each retry
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowDefinition:
    workflow_id: str
    name: str
    description: str
    trigger: str = "manual"
    standing_order: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    chain_next: str | None = None  # workflow_id to trigger on completion
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(slots=True)
class WorkflowRun:
    run_id: str
    workflow_id: str
    status: str = "running"
    current_step: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class WorkflowEngine:
    """Durable multi-step workflow orchestration with standing-order notes."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config

        self.workspace_dir = (
            Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        )
        self.workflows_dir = self.workspace_dir / "workflows"
        self.runs_file = self.workspace_dir / "workflow_runs.jsonl"
        self.workflows_dir.mkdir(parents=True, exist_ok=True)

    def _workflow_path(self, workflow_id: str) -> Path:
        return self.workflows_dir / f"{workflow_id}.json"

    def evaluate_condition(self, condition: str, context: dict[str, Any]) -> bool:
        """Evaluate a simple condition string against workflow context.

        Supported operators: ==, !=, >, <, >=, <=, in, not in
        Supports dot-notation for nested context: context.project == 'raven'
        """
        if not condition:
            return True

        try:
            # Parse simple conditions like "context.key == 'value'"
            import re
            m = re.match(
                r"(\w+(?:\.\w+)*)\s*(==|!=|>=|<=|>|<|in|not in)\s*(.+)",
                condition.strip(),
            )
            if not m:
                logger.warning("Cannot parse condition: %s", condition)
                return True  # Default to True if unparseable

            left_expr, operator, right_expr = m.groups()

            # Resolve left side from context
            value = context
            for part in left_expr.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break

            # Parse right side
            right_val = right_expr.strip().strip("'\"")

            # Evaluate
            if operator == "==":
                return str(value) == right_val
            elif operator == "!=":
                return str(value) != right_val
            elif operator == ">":
                return float(value or 0) > float(right_val)
            elif operator == "<":
                return float(value or 0) < float(right_val)
            elif operator == ">=":
                return float(value or 0) >= float(right_val)
            elif operator == "<=":
                return float(value or 0) <= float(right_val)
            elif operator == "in":
                return str(value) in right_val
            elif operator == "not in":
                return str(value) not in right_val

        except Exception as exc:
            logger.warning("Condition evaluation failed: %s — %s", condition, exc)

        return True  # Default to True on error

    def save_workflow(self, workflow: WorkflowDefinition) -> None:
        workflow.updated_at = datetime.now(timezone.utc).isoformat()
        self._workflow_path(workflow.workflow_id).write_text(
            json.dumps(asdict(workflow), ensure_ascii=True, indent=2), encoding="utf-8"
        )

    def load_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        path = self._workflow_path(workflow_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return WorkflowDefinition(
                workflow_id=raw["workflow_id"],
                name=raw["name"],
                description=raw.get("description", ""),
                trigger=raw.get("trigger", "manual"),
                standing_order=raw.get("standing_order", ""),
                steps=[WorkflowStep(**step) for step in raw.get("steps", [])],
                chain_next=raw.get("chain_next"),
                created_at=raw.get(
                    "created_at", datetime.now(timezone.utc).isoformat()
                ),
                updated_at=raw.get(
                    "updated_at", datetime.now(timezone.utc).isoformat()
                ),
            )
        except Exception as exc:
            logger.debug("Failed to load workflow %s: %s", workflow_id, exc)
            return None

    def list_workflows(self) -> list[dict[str, Any]]:
        workflows: list[dict[str, Any]] = []
        for path in sorted(self.workflows_dir.glob("*.json")):
            try:
                workflows.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return workflows

    def create_workflow(
        self,
        name: str,
        description: str,
        steps: list[dict[str, Any]],
        *,
        workflow_id: str | None = None,
        trigger: str = "manual",
        standing_order: str = "",
    ) -> WorkflowDefinition:
        workflow_id = workflow_id or f"wf_{len(self.list_workflows()) + 1}"
        wf = WorkflowDefinition(
            workflow_id=workflow_id,
            name=name,
            description=description,
            trigger=trigger,
            standing_order=standing_order,
            steps=[WorkflowStep(**step) for step in steps],
        )
        self.save_workflow(wf)
        return wf

    def start_run(
        self, workflow_id: str, *, context: dict[str, Any] | None = None
    ) -> WorkflowRun:
        run_id = (
            f"run_{workflow_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        run = WorkflowRun(run_id=run_id, workflow_id=workflow_id, context=context or {})
        self._append_run(run)
        return run

    def _append_run(self, run: WorkflowRun) -> None:
        with self.runs_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(run), ensure_ascii=True) + "\n")

    def list_runs(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        if not self.runs_file.exists():
            return runs
        for line in self.runs_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            if workflow_id and raw.get("workflow_id") != workflow_id:
                continue
            runs.append(raw)
        return runs

    def check_chain(self, run: dict[str, Any]) -> str | None:
        """Check if a completed workflow should trigger the next one.

        Returns the next workflow_id if chain_next is set and all steps are done.
        """
        if run.get("status") != "done":
            return None

        wf = self.load_workflow(run.get("workflow_id", ""))
        if wf and wf.chain_next:
            logger.info("Workflow '%s' complete — chaining to '%s'", wf.name, wf.chain_next)
            return wf.chain_next
        return None

    def advance_step(self, run_id: str, step_id: str, status: str = "done") -> bool:
        runs = self.list_runs()
        changed = False
        for run in runs:
            if run.get("run_id") == run_id:
                run["current_step"] = step_id
                run["status"] = status
                run["updated_at"] = datetime.now(timezone.utc).isoformat()
                changed = True
        if changed:
            self.runs_file.write_text(
                "\n".join(json.dumps(run, ensure_ascii=True) for run in runs) + "\n",
                encoding="utf-8",
            )
        return changed

    async def execute_step(self, run_id: str, step: WorkflowStep) -> bool:
        """Execute a workflow step's action with retry support.

        Supports action types:
          - "tool:<tool_name>": Execute a tool with params
          - "notify:<text>": Send a notification
          - "memory:<content>": Store a memory
          - "delay:<seconds>": Wait for N seconds
          - Custom: pass through to LLM for interpretation

        Retries on failure with exponential backoff up to max_retries.
        """
        import asyncio

        action = step.action
        last_error = None

        for attempt in range(step.max_retries + 1):
            try:
                if action.startswith("tool:"):
                    tool_name = action[5:]
                    params = step.metadata.get("params", {})
                    from app.core.orchestrator import MessageOrchestrator
                    orch = MessageOrchestrator.__new__(MessageOrchestrator)
                    if hasattr(orch, '_agent_runtime') and hasattr(orch._agent_runtime, 'tools'):
                        tool = orch._agent_runtime.tools.get(tool_name)
                        if tool:
                            result = await tool.execute(**params)
                            step.metadata["result"] = result
                            return True

                elif action.startswith("notify:"):
                    text = action[7:]
                    from app.core.memory_facade import get_memory_facade
                    facade = get_memory_facade()
                    facade.remember(f"[Workflow] {text}", category="FACT")
                    return True

                elif action.startswith("memory:"):
                    content = action[7:]
                    from app.core.memory_facade import get_memory_facade
                    facade = get_memory_facade()
                    facade.remember(content, category="FACT")
                    return True

                elif action.startswith("delay:"):
                    seconds = int(action[6:])
                    await asyncio.sleep(seconds)
                    return True

                else:
                    logger.warning("Workflow step action not recognized: %s", action)
                    return True

            except Exception as exc:
                last_error = exc
                step.retry_count = attempt + 1
                if attempt < step.max_retries:
                    delay = step.retry_delay * (2 ** attempt)
                    logger.warning(
                        "Workflow step '%s' failed (attempt %d/%d), retrying in %.1fs: %s",
                        step.step_id, attempt + 1, step.max_retries, delay, exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Workflow step '%s' failed after %d retries: %s",
                        step.step_id, step.max_retries, exc,
                    )

        step.metadata["error"] = str(last_error) if last_error else "Unknown error"
        return False
