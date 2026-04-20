# app/tools/workflowtool.py
"""WorkflowTool — expose the durable WorkflowEngine to the LLM.

Operations:
  list_workflows   — list all saved workflow definitions
  get_workflow      — get a workflow definition by ID
  create_workflow   — create a new multi-step workflow
  run_workflow      — start executing a workflow
  list_runs         — list execution runs for a workflow
  advance_step      — mark a step as done and advance
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class WorkflowTool(BaseTool):
    group = "automation"

    def __init__(self) -> None:
        from app.core.workflow_engine import WorkflowEngine

        self._engine = WorkflowEngine()

    def get_name(self) -> str:
        return "workflow_ops"

    def get_description(self) -> str:
        return (
            "Durable multi-step workflow management. Create, run, and track "
            "complex automation workflows with dependency chains and standing orders."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Workflow operation to perform",
                    required=True,
                    enum=[
                        "list_workflows",
                        "get_workflow",
                        "create_workflow",
                        "run_workflow",
                        "list_runs",
                        "advance_step",
                    ],
                ),
                ToolParameter(
                    name="workflow_id",
                    type="string",
                    description="Workflow ID (for get/run/list_runs)",
                    required=False,
                ),
                ToolParameter(
                    name="name",
                    type="string",
                    description="Workflow name (for create)",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Workflow description (for create)",
                    required=False,
                ),
                ToolParameter(
                    name="steps",
                    type="array",
                    description=(
                        "List of step objects: [{step_id, title, action, depends_on: []}]. "
                        "Each step defines an action the system should take."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="trigger",
                    type="string",
                    description="Trigger type: manual | schedule | event",
                    required=False,
                    enum=["manual", "schedule", "event"],
                ),
                ToolParameter(
                    name="standing_order",
                    type="string",
                    description="Standing instructions that apply to every step in the workflow",
                    required=False,
                ),
                ToolParameter(
                    name="run_id",
                    type="string",
                    description="Run ID (for advance_step)",
                    required=False,
                ),
                ToolParameter(
                    name="step_id",
                    type="string",
                    description="Step ID to advance (for advance_step)",
                    required=False,
                ),
                ToolParameter(
                    name="status",
                    type="string",
                    description="Status to set (for advance_step): done | failed | skipped",
                    required=False,
                    enum=["done", "failed", "skipped"],
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["automation"],
            risk_level="medium",
            cost_tier="low",
            confirmation_policy="none",
            readonly=False,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation", "list_workflows")

        try:
            if operation == "list_workflows":
                workflows = self._engine.list_workflows()
                return {
                    "success": True,
                    "workflows": workflows,
                    "count": len(workflows),
                }

            elif operation == "get_workflow":
                wf_id = kwargs.get("workflow_id", "")
                if not wf_id:
                    return {"success": False, "error": "workflow_id required"}
                wf = self._engine.load_workflow(wf_id)
                if not wf:
                    return {"success": False, "error": f"Workflow '{wf_id}' not found"}
                from dataclasses import asdict
                return {"success": True, "workflow": asdict(wf)}

            elif operation == "create_workflow":
                name = kwargs.get("name", "")
                desc = kwargs.get("description", "")
                steps = kwargs.get("steps", [])
                if not name:
                    return {"success": False, "error": "name required"}
                if not steps:
                    return {"success": False, "error": "steps required (at least 1)"}

                wf = self._engine.create_workflow(
                    name=name,
                    description=desc,
                    steps=steps,
                    workflow_id=kwargs.get("workflow_id"),
                    trigger=kwargs.get("trigger", "manual"),
                    standing_order=kwargs.get("standing_order", ""),
                )
                return {
                    "success": True,
                    "workflow_id": wf.workflow_id,
                    "message": f"Workflow '{name}' created with {len(steps)} steps",
                }

            elif operation == "run_workflow":
                wf_id = kwargs.get("workflow_id", "")
                if not wf_id:
                    return {"success": False, "error": "workflow_id required"}
                run = self._engine.start_run(wf_id)
                return {
                    "success": True,
                    "run_id": run.run_id,
                    "message": f"Workflow '{wf_id}' started as run '{run.run_id}'",
                }

            elif operation == "list_runs":
                wf_id = kwargs.get("workflow_id")
                runs = self._engine.list_runs(wf_id)
                return {"success": True, "runs": runs, "count": len(runs)}

            elif operation == "advance_step":
                run_id = kwargs.get("run_id", "")
                step_id = kwargs.get("step_id", "")
                status = kwargs.get("status", "done")
                if not run_id or not step_id:
                    return {"success": False, "error": "run_id and step_id required"}
                ok = self._engine.advance_step(run_id, step_id, status)
                return {
                    "success": ok,
                    "message": f"Step '{step_id}' in run '{run_id}' → {status}" if ok else "Run not found",
                }

            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as exc:
            logger.error("WorkflowTool error: %s", exc)
            return {"success": False, "error": str(exc)}
