import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.core.botsignal import get_botsignal
from app.core.models import IncomingRequest
from app.core.runtime import AgentRuntime
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class WorkerAgent:
    """A specialized sub-agent that executes a specific task asynchronously (System 2)."""

    def __init__(
        self,
        name: str,
        role_prompt: str,
        tools: List[BaseTool],
        workspace_dir: str | None = None,
        provider_name: str = "opencode_zen",
        model_name: str = "big-pickle",
        system_prompt: Optional[str] = None,
    ):
        self.name = name
        self.runtime = AgentRuntime(
            workspace_dir=workspace_dir,
            provider_name=provider_name,
            model_name=model_name,
        )

        # If an enhanced system prompt is supplied (from BaseAgent.get_enhanced_prompt),
        # use it directly.  Otherwise fall back to the legacy template.
        if system_prompt:
            _prompt = system_prompt
        else:
            _prompt = (
                f"You are {name}, an elite specialist in a Fortune 500 AI Agency.\n"
                f"Your Role: {role_prompt}\n"
                "You do not talk to the user directly. You are completing a sub-task for the Manager Agent. "
                "Execute your tools, analyze the data, and provide a comprehensive final report of your findings."
            )

        self.runtime.bootstrapper.build_system_prompt = lambda: _prompt

        for tool in tools:
            self.runtime.register_tool(tool)

        # FRIDAY: shared scratchpad for agent-to-agent communication
        self.scratchpad: Dict[str, Any] = {}

    async def execute_task(self, task_description: str, request: IncomingRequest) -> str:
        """Executes a task autonomously and captures the output to return to the Manager."""
        messages = [
            {
                "role": "system",
                "content": self.runtime.bootstrapper.build_system_prompt(),
            }
        ]
        messages.append({"role": "user", "content": f"TASK: {task_description}"})

        openai_tools = self.runtime._build_openai_tools()
        max_turns = 10
        turn_count = 0
        final_answer = ""

        while turn_count < max_turns:
            turn_count += 1
            try:
                kwargs = {}
                if openai_tools:
                    kwargs["tools"] = openai_tools

                # Using the resilient provider loop
                if hasattr(self.runtime.provider, "chat_completion_resilient"):
                    res = await self.runtime.provider.chat_completion_resilient(
                        messages=messages,
                        preferred_models=[self.runtime.model_name],
                        free_only_guard=True,
                        **kwargs,
                    )
                else:
                    res = await self.runtime.provider.chat_completion(
                        model=self.runtime.model_name, messages=messages, **kwargs
                    )

                if not res.get("success"):
                    logger.warning(
                        "Worker %s primary provider failed, trying fallbacks",
                        self.name,
                    )
                    fallback_ok = False
                    try:
                        from app.core.model_router import AutoModelRouter
                        from app.provider.factory import create_provider

                        fallbacks = AutoModelRouter.get_available_models("agent")
                        for f_prov_name, f_model_name in fallbacks:
                            if (
                                f_prov_name == self.runtime._provider_name()
                                and f_model_name == self.runtime.model_name
                            ):
                                continue
                            try:
                                f_prov = create_provider(f_prov_name)
                                f_res = await f_prov.chat_completion(
                                    model=f_model_name, messages=messages, **kwargs
                                )
                                if f_res.get("success"):
                                    res = f_res
                                    self.runtime.provider = f_prov
                                    self.runtime.model_name = f_model_name
                                    fallback_ok = True
                                    break
                            except Exception:
                                continue
                    except Exception:
                        pass
                    if not fallback_ok:
                        return f"[Worker {self.name} Error]: {res.get('error')}"

                content, tool_calls = self.runtime._extract_provider_message(res)

                asst_msg = {"role": "assistant", "content": content}
                if tool_calls:
                    asst_msg["tool_calls"] = tool_calls
                messages.append(asst_msg)

                if not tool_calls:
                    final_answer = content
                    break

                for tc in tool_calls:
                    function_name = tc.get("function", {}).get("name")
                    try:
                        args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                    except Exception:
                        args = {}

                    if function_name in self.runtime.tools:
                        tool = self.runtime.tools[function_name]
                        try:
                            result = await tool.execute(**args)
                            result_str = json.dumps(result, default=str)
                        except Exception as e:
                            result_str = json.dumps({"error": str(e)})
                    else:
                        result_str = json.dumps({"error": f"Tool {function_name} not found"})

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id"),
                            "name": function_name,
                            "content": result_str,
                        }
                    )
            except Exception as e:
                logger.error(f"Worker {self.name} crash: {e}", exc_info=True)
                return f"[Worker {self.name} System Crash]: {str(e)}"

        return final_answer or "[Worker terminated without conclusive output]"


class SwarmManager:
    """
    The orchestrator of the Asynchronous Corporate Swarm.
    Breaks down Case Studies and delegates to specialized BaseAgents via asyncio.gather.
    """

    def __init__(self, workspace_dir: str | None = None):
        from app.settings.config import Config

        self.workspace_dir = workspace_dir if workspace_dir else Config.MEMORY_ROOT
        self.botsignal = get_botsignal()
        self.available_agents: Dict[str, BaseAgent] = {}
        # FRIDAY: shared context for agent-to-agent communication
        self.shared_context: Dict[str, Any] = {}
        # FRIDAY: agent message bus for inter-agent messaging
        self._message_bus: Dict[str, list[Dict[str, Any]]] = {}

    def register_agent(self, agent: BaseAgent):
        """Registers a specialized agent into the swarm."""
        self.available_agents[agent.name] = agent

    def deregister_agent(self, name: str) -> bool:
        """Remove an agent from the swarm by name.

        Returns True if the agent was removed, False if not found.
        """
        if name in self.available_agents:
            del self.available_agents[name]
            return True
        return False

    # ── Dynamic Agent Spawning (FRIDAY) ───────────────────────────

    def spawn_agent(
        self,
        name: str,
        role_description: str,
        tools: list | None = None,
        provider_name: str = "auto",
        model_name: str = "",
    ) -> WorkerAgent:
        """Dynamically spawn a new agent from a natural language description.

        FRIDAY-style: creates specialist agents on-the-fly for
        ad-hoc tasks without pre-registration.
        """

        # Default tools: basic set for any agent
        if tools is None:
            tools = []

        worker = WorkerAgent(
            name=name,
            role_prompt=role_description,
            tools=tools,
            workspace_dir=self.workspace_dir,
            provider_name=provider_name,
            model_name=model_name,
        )

        logger.info("Dynamically spawned agent: %s — %s", name, role_description[:60])
        return worker

    async def spawn_and_execute(
        self,
        name: str,
        role_description: str,
        task: str,
        request: IncomingRequest,
        tools: list | None = None,
    ) -> str:
        """Spawn a dynamic agent, execute a task, and return the result.

        Convenience method for one-off agent creation + execution.
        """
        worker = self.spawn_agent(name, role_description, tools)
        return await worker.execute_task(task, request)

    # ── Agent-to-Agent Messaging ────────────────────────────────────

    def send_message(self, from_agent: str, to_agent: str, message: str, **kwargs: Any) -> None:
        """Send a message from one agent to another.

        Messages are queued and delivered when the target agent
        next checks its inbox.
        """
        if to_agent not in self._message_bus:
            self._message_bus[to_agent] = []
        self._message_bus[to_agent].append(
            {
                "from": from_agent,
                "message": message,
                "timestamp": __import__("datetime")
                .datetime.now(__import__("datetime").timezone.utc)
                .isoformat(),
                **kwargs,
            }
        )

    def check_inbox(self, agent_name: str) -> list[Dict[str, Any]]:
        """Check and clear an agent's message inbox."""
        messages = self._message_bus.pop(agent_name, [])
        return messages

    def broadcast(self, from_agent: str, message: str, **kwargs: Any) -> None:
        """Broadcast a message to all registered agents."""
        for name in self.available_agents:
            if name != from_agent:
                self.send_message(from_agent, name, message, **kwargs)

    def get_shared_context(self, key: str | None = None) -> Any:
        """Get shared context. If key is provided, return that value."""
        if key:
            return self.shared_context.get(key)
        return dict(self.shared_context)

    def set_shared_context(self, key: str, value: Any) -> None:
        """Set a value in shared context for all agents to access."""
        self.shared_context[key] = value

    async def execute_case_study(
        self, request: IncomingRequest, tasks: List[Dict[str, Any]]
    ) -> None:
        """
        Executes a complex case study asynchronously.
        Expected format of `tasks`:
        [
            {
                "agent_name": "FinanceAnalyst",
                "task": "Pull the latest market report for TSLA and analyze the MACD."
            },
            ...
        ]
        """
        source_kind = "system2_swarm"

        # Ping the user that System 2 (Deep Research) has engaged
        await self.botsignal.send_text(
            request.reply_target,
            f"🕵️‍♂️ **Case Study Initiated.** Spawning {len(tasks)} parallel sub-agents to investigate. I will ping you when the analysis is complete.",
            source_kind=source_kind,
        )

        workers = []
        coroutines = []

        for t in tasks:
            agent_name = t.get("agent_name")
            if agent_name in self.available_agents:
                agent_def = self.available_agents[agent_name]

                # Build enhanced prompt if available, otherwise fall back
                enhanced = agent_def.get_enhanced_prompt()

                # Wrap the BaseAgent in a WorkerAgent for execution.
                # An explicit task-level override wins; otherwise the
                # agent's own provider_name is used.  If the agent
                # didn't pick a specific provider (default = "auto",
                # or legacy default), call AutoModelRouter so the
                # swarm re-picks every turn based on whatever API keys
                # are loaded — including keys the operator pasted on
                # the /page/providers dashboard.
                worker_provider = t.get("provider_name") or agent_def.provider_name
                worker_model = t.get("model") or agent_def.model_name

                from app.core.model_router import AutoModelRouter
                from app.provider.manager import ProviderManager

                if (worker_provider or "").lower() in {"", "auto", "opencode_zen"}:
                    pm = ProviderManager(self.workspace_dir)
                    slot_pid, slot_mid = pm.resolve_model_slot(f"agent:{agent_name}")
                    if slot_pid and slot_mid:
                        worker_provider, worker_model = slot_pid, slot_mid
                    else:
                        agent_override = pm.get_agent_model(agent_name)
                        if agent_override:
                            worker_provider, worker_model = agent_override
                        else:
                            pm_provider, pm_model = pm.select_model()
                            if pm_provider != "opencode_zen" or pm_model != "big-pickle":
                                worker_provider, worker_model = pm_provider, pm_model
                            else:
                                worker_provider, worker_model = AutoModelRouter.get_best_model(
                                    agent_name
                                )

                worker = WorkerAgent(
                    name=agent_def.name,
                    role_prompt=agent_def.role_prompt,
                    tools=agent_def.tools,
                    workspace_dir=self.workspace_dir,
                    provider_name=worker_provider,
                    model_name=worker_model,
                    system_prompt=enhanced,
                )
                workers.append(worker)
                coroutines.append(worker.execute_task(t["task"], request))
            else:
                logger.warning(f"Agent '{agent_name}' not found in swarm registry.")

        if not coroutines:
            await self.botsignal.send_text(
                request.reply_target,
                "Case study failed: No valid agents found to execute the tasks.",
                source_kind=source_kind,
            )
            return

        # Execute all agents in parallel (The Swarm)
        results = await asyncio.gather(*coroutines, return_exceptions=True)

        # FRIDAY: Agent feedback loop — cross-check outputs
        try:
            from app.core.agent_feedback import FeedbackCollector

            collector = FeedbackCollector()

            # Each worker's output is reviewed by 1-2 other workers
            for i, worker in enumerate(workers):
                res = results[i]
                if isinstance(res, Exception):
                    continue
                output = str(res)[:500]
                # Assign reviewers (circular: worker i reviews worker i+1)
                reviewer_idx = (i + 1) % len(workers)
                if reviewer_idx != i and not isinstance(results[reviewer_idx], Exception):
                    reviewer_name = workers[reviewer_idx].name
                    # Simple quality check: flag if output is too short or empty
                    if len(output.strip()) < 50:
                        collector.submit(
                            source_agent=reviewer_name,
                            target_agent=worker.name,
                            original_output=output,
                            critique="Output appears incomplete or too short for a thorough analysis.",
                            suggestions=[
                                "Provide more detailed findings with specific data points."
                            ],
                            severity="warning",
                        )
                    elif "error" in output.lower() or "failed" in output.lower():
                        collector.submit(
                            source_agent=reviewer_name,
                            target_agent=worker.name,
                            original_output=output,
                            critique="Output contains error indicators — may need retry with different approach.",
                            suggestions=["Retry with alternative tool or simplified query."],
                            severity="critical",
                        )

            # Log feedback summary
            feedback_count = sum(len(fbs) for fbs in collector._feedbacks.values())
            if feedback_count > 0:
                logger.info(
                    "Agent feedback: %d pieces of cross-check feedback collected", feedback_count
                )
        except Exception as exc:
            logger.debug("Agent feedback loop skipped: %s", exc)

        # Compile the final Evidence Board
        compiled_report = "### 📂 Case Study: Investigative Report\n\n"
        for i, worker in enumerate(workers):
            res = results[i]
            compiled_report += f"#### 🤖 Agent: {worker.name}\n"
            if isinstance(res, Exception):
                compiled_report += f"⚠️ Fatal Sub-Agent Exception: {str(res)}\n\n"
            else:
                compiled_report += f"{res}\n\n"

        # Send the final compiled thesis to the user's platform or pass to Reviewer
        if "ReviewerQA" in self.available_agents:
            await self.botsignal.send_text(
                request.reply_target,
                "🧠 **Swarm workers finished.** Passing Evidence Board to ReviewerQA for final synthesis and memory extraction...",
                source_kind=source_kind,
            )
            reviewer_def = self.available_agents["ReviewerQA"]
            reviewer_enhanced = reviewer_def.get_enhanced_prompt()

            from app.core.model_router import AutoModelRouter
            from app.provider.manager import ProviderManager

            rev_provider = reviewer_def.provider_name
            rev_model = reviewer_def.model_name
            if (rev_provider or "").lower() in {"", "auto", "opencode_zen"}:
                pm = ProviderManager(self.workspace_dir)
                agent_override = pm.get_agent_model(reviewer_def.name)
                if agent_override:
                    rev_provider, rev_model = agent_override
                else:
                    pm_provider, pm_model = pm.select_model()
                    if pm_provider != "opencode_zen" or pm_model != "big-pickle":
                        rev_provider, rev_model = pm_provider, pm_model
                    else:
                        rev_provider, rev_model = AutoModelRouter.get_best_model(reviewer_def.name)

            reviewer_worker = WorkerAgent(
                name=reviewer_def.name,
                role_prompt=reviewer_def.role_prompt,
                tools=reviewer_def.tools,
                workspace_dir=self.workspace_dir,
                provider_name=rev_provider,
                model_name=rev_model,
                system_prompt=reviewer_enhanced,
            )
            final_qa_report = await reviewer_worker.execute_task(
                f"Here is the raw Evidence Board from the workers:\n\n{compiled_report}\n\nPlease synthesize this into a final, highly readable report for the user. Also, if you notice any permanent facts or network topologies, use your memory tool to save them.",
                request,
            )
            await self.botsignal.send_text(
                request.reply_target, final_qa_report, source_kind=source_kind
            )
        else:
            await self.botsignal.send_text(
                request.reply_target, compiled_report, source_kind=source_kind
            )
