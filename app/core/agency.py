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
        provider_name: str = "killo",
        model_name: str = "qwen/qwen3-coder:free",
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

    async def execute_task(
        self, task_description: str, request: IncomingRequest
    ) -> str:
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
                        result_str = json.dumps(
                            {"error": f"Tool {function_name} not found"}
                        )

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

    def register_agent(self, agent: BaseAgent):
        """Registers a specialized agent into the swarm."""
        self.available_agents[agent.name] = agent

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

                # Wrap the BaseAgent in a WorkerAgent for execution
                worker_provider = t.get("provider_name") or agent_def.provider_name
                worker_model = t.get("model") or agent_def.model_name

                from app.core.model_router import AutoModelRouter

                if worker_provider == "killo":
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

            rev_provider = reviewer_def.provider_name
            rev_model = reviewer_def.model_name
            if rev_provider == "killo":
                rev_provider, rev_model = AutoModelRouter.get_best_model(
                    reviewer_def.name
                )

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
