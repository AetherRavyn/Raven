from __future__ import annotations

import logging
import os
import re
import time
from collections import deque
from typing import Any

from app.core.blueprint_models import BlueprintCondition, BlueprintStep
from app.core.blueprint_manager import BlueprintManager

logger = logging.getLogger(__name__)


class BlueprintRunner:
    def __init__(
        self,
        manager: BlueprintManager | None = None,
        orchestrator: Any | None = None,
    ) -> None:
        self._manager = manager or BlueprintManager()
        self._orchestrator = orchestrator

    def run(
        self,
        name: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = dict(context or {})
        blueprint = self._manager.get_blueprint(name)
        if blueprint is None:
            return {"status": "error", "error": f"Blueprint '{name}' not found", "steps_results": [], "duration": 0.0}

        steps_total = len(blueprint.steps)
        run_id = self._manager._record_run_start(name, steps_total)
        steps_results: list[dict[str, Any]] = []
        overall_status = "success"
        error_msg: str | None = None
        start_time = time.monotonic()

        try:
            dag = self._build_dag(blueprint.steps)
            execution_order = self._topological_sort(dag)
            step_map = {s.id: s for s in blueprint.steps}
            completed: set[str] = set()
            step_outputs: dict[str, Any] = {}

            for step_id in execution_order:
                step = step_map[step_id]

                # check condition
                if step.condition is not None:
                    skip = not self._evaluate_expression(step.condition, context, step_outputs)
                    if skip:
                        logger.info("Step '%s' SKIPPED (condition: %s)", step_id, step.condition)
                        steps_results.append({
                            "step_id": step_id,
                            "status": "skipped",
                            "condition": step.condition,
                        })
                        completed.add(step_id)
                        continue

                # resolve templates
                resolved = self._resolve_params(step.params or {}, context, step_outputs)

                # execute
                step_start = time.monotonic()
                try:
                    result = self._execute_step(step, resolved, context)
                    duration = time.monotonic() - step_start
                    step_outputs[step_id] = result
                    steps_results.append({
                        "step_id": step_id,
                        "status": "success",
                        "result": result,
                        "duration": round(duration, 3),
                    })
                    completed.add(step_id)
                except Exception as exc:
                    duration = time.monotonic() - step_start
                    logger.error("Step '%s' failed: %s", step_id, exc)
                    steps_results.append({
                        "step_id": step_id,
                        "status": "error",
                        "error": str(exc),
                        "duration": round(duration, 3),
                    })
                    if overall_status == "success":
                        overall_status = "partial"
                    completed.add(step_id)

            # evaluate conditions after all steps
            if blueprint.conditions:
                for cond in blueprint.conditions:
                    self._evaluate_condition_action(cond, context, step_outputs)

        except Exception as exc:
            logger.exception("Blueprint '%s' run failed: %s", name, exc)
            overall_status = "error"
            error_msg = str(exc)

        duration = time.monotonic() - start_time
        steps_completed = sum(1 for r in steps_results if r["status"] == "success")
        final_status = overall_status if error_msg is None else "error"

        self._manager._record_run_finish(
            run_id, name, final_status, steps_completed, error_msg,
        )

        return {
            "status": final_status,
            "steps_results": steps_results,
            "duration": round(duration, 3),
            "error": error_msg,
        }

    # ── DAG helpers ─────────────────────────────────────────────────────

    def _build_dag(self, steps: list[BlueprintStep]) -> dict[str, list[str]]:
        dag: dict[str, list[str]] = {}
        step_ids = {s.id for s in steps}
        for s in steps:
            deps = []
            if s.depends_on:
                deps = [d for d in s.depends_on if d in step_ids]
            dag[s.id] = deps
        return dag

    def _topological_sort(self, dag: dict[str, list[str]]) -> list[str]:
        in_degree: dict[str, int] = {node: 0 for node in dag}
        for node, deps in dag.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[node] += 1

        queue = deque([n for n, d in in_degree.items() if d == 0])
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for other, deps in dag.items():
                if node in deps:
                    in_degree[other] -= 1
                    if in_degree[other] == 0:
                        queue.append(other)

        if len(order) != len(dag):
            raise ValueError("Circular dependency detected in blueprint steps")

        return order

    # ── template resolution ─────────────────────────────────────────────

    def _resolve_params(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
        step_outputs: dict[str, Any],
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str):
                resolved[key] = self._resolve_template(value, context, step_outputs)
            else:
                resolved[key] = value
        return resolved

    def _resolve_template(
        self,
        template: str,
        context: dict[str, Any],
        step_outputs: dict[str, Any],
    ) -> str:
        result = template

        # resolve {{ var }} from context or step outputs
        def _replace_var(match: re.Match) -> str:
            key = match.group(1).strip()
            if key in step_outputs:
                val = step_outputs[key]
            elif key in context:
                val = context[key]
            else:
                val = os.environ.get(key, match.group(0))
            return str(val) if val is not None else match.group(0)

        result = re.sub(r"\{\{\s*(\w+)\s*\}\}", _replace_var, result)

        # resolve $ENV_VAR
        def _replace_env(match: re.Match) -> str:
            var_name = match.group(1)
            if var_name is None:
                return match.group(0)
            return str(os.environ.get(var_name, match.group(0)))

        result = re.sub(r"\$(\w+)", _replace_env, result)

        return result

    # ── step execution ──────────────────────────────────────────────────

    def _execute_step(
        self,
        step: BlueprintStep,
        resolved_params: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        if self._orchestrator is not None:
            runtime = getattr(self._orchestrator, "_agent_runtime", None)
            if runtime is not None:
                tool = runtime.tools.get(step.tool)
                if tool is not None:
                    return tool.execute(**resolved_params)
            return self._call_orchestrator_tool(step.tool, resolved_params)
        return {"_mock": True, "tool": step.tool, "params": resolved_params}

    def _call_orchestrator_tool(self, tool_name: str, params: dict[str, Any]) -> Any:
        if self._orchestrator is None:
            raise RuntimeError(f"No orchestrator available to execute tool '{tool_name}'")
        handler = getattr(self._orchestrator, "handle_tool_call", None)
        if handler is not None:
            return handler(tool_name, params)
        raise RuntimeError(f"Orchestrator has no 'handle_tool_call' method for tool '{tool_name}'")

    # ── condition evaluation ────────────────────────────────────────────

    def _evaluate_expression(
        self,
        expression: str,
        context: dict[str, Any],
        step_outputs: dict[str, Any],
    ) -> bool:
        resolved = self._resolve_template(expression, context, step_outputs)
        resolved_lower = resolved.strip().lower()
        if resolved_lower in ("true", "yes", "1"):
            return True
        if resolved_lower in ("false", "no", "0", ""):
            return False
        try:
            result: bool = bool(eval(resolved, {"__builtins__": {}}, {**context, **step_outputs}))
            return result
        except Exception:
            logger.warning("Could not evaluate condition '%s', defaulting to False", resolved)
            return False

    def _evaluate_condition_action(
        self,
        condition: BlueprintCondition,
        context: dict[str, Any],
        step_outputs: dict[str, Any],
    ) -> None:
        truthy = self._evaluate_expression(condition.if_expr, context, step_outputs)
        action = condition.then_action if truthy else condition.else_action
        if action is not None:
            logger.info("Condition action: %s (if_expr=%s)", action, condition.if_expr)
