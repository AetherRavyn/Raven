import json
import subprocess
from pathlib import Path

from app.core.models import IncomingRequest
from app.core.task_ledger import TaskLedger
from app.settings.config import Config
from app.core.skill_registry import SkillRegistry


class CommandGateway:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    async def handle_command(self, request: IncomingRequest) -> bool:
        text = request.text.strip()

        if text.startswith("!"):
            text = "/bash " + text[1:]

        if not text.startswith("/"):
            return False

        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        result = ""
        try:
            if command == "/help":
                result = self._cmd_help()
            elif command == "/status":
                result = self._cmd_status()
            elif command == "/tools":
                result = self._cmd_tools()
            elif command == "/approve":
                result = self._cmd_approve(args)
            elif command == "/reject":
                result = self._cmd_reject(args)
            elif command in ["/clear", "/new", "/reset"]:
                result = self._cmd_clear(request)
            elif command == "/model":
                result = self._cmd_model(args)
            elif command == "/tasks":
                result = self._cmd_tasks()
            elif command in ["/whoami", "/id"]:
                result = self._cmd_whoami(request)
            elif command == "/agents":
                result = self._cmd_agents()
            elif command == "/plugins":
                result = self._cmd_plugins()
            elif command == "/bash":
                result = self._cmd_bash(args)
            else:
                result = f"Unknown command: {command}. Type /help for a list of available commands."
        except Exception as e:
            result = f"Error executing command {command}: {str(e)}"

        await self.orchestrator._botsignal.send_text(
            request.reply_target, result, source_kind="command"
        )
        return True

    def _cmd_help(self) -> str:
        return (
            "**Available Commands:**\n\n"
            "**Session**\n"
            "• `/new`, `/clear`, `/whoami`, `/model`\n\n"
            "**System**\n"
            "• `/status`, `/tasks`, `/approve`, `/reject`\n\n"
            "**Capabilities**\n"
            "• `/tools`, `/agents`, `/plugins`\n\n"
            "**Developer**\n"
            "• `/bash` or `!`"
        )

    def _cmd_status(self) -> str:
        ledger = TaskLedger(Config.MEMORY_ROOT)
        tasks = ledger.list_tasks()
        pending = [t for t in tasks if t.get("status") == "pending_approval"]

        lines = ["=== SARAS Status ==="]
        lines.append(f"Pending Approvals: {len(pending)}")
        for p in pending:
            task_id = p.get("task_id", p.get("id", "unknown"))
            lines.append(f" - [{task_id}] {p.get('title', 'Untitled')}")

        lines.append("\nEdge Nodes:")
        devices_file = Path(Config.MEMORY_ROOT) / "state" / "devices.json"
        if devices_file.exists():
            try:
                with open(devices_file, "r") as f:
                    devices = json.load(f)
                if not devices:
                    lines.append(" - No edge nodes registered.")
                else:
                    for device in devices:
                        status = device.get("status", "unknown")
                        lines.append(f" - {device.get('id', 'unknown')} ({status})")
            except json.JSONDecodeError:
                lines.append(" - Error reading devices.json.")
        else:
            lines.append(" - No edge nodes registered.")

        return "\n".join(lines)

    def _cmd_tools(self) -> str:
        if not hasattr(self.orchestrator, "_agent_runtime"):
            return "Agent runtime not initialized."

        tools = self.orchestrator._agent_runtime.tools
        if not tools:
            return "No tools available."

        lines = ["**Available Tools:**"]
        for tool in tools:
            name = getattr(tool, "name", type(tool).__name__)
            desc = getattr(tool, "description", "No description")
            lines.append(f"• `{name}`: {desc}")

        return "\n".join(lines)

    def _cmd_approve(self, args: str) -> str:
        task_id = args.strip()
        if not task_id:
            return "Usage: /approve <task_id>"

        ledger = TaskLedger(Config.MEMORY_ROOT)
        tasks = ledger.list_tasks()
        task = next(
            (t for t in tasks if t.get("task_id") == task_id or t.get("id") == task_id),
            None,
        )
        if not task:
            return f"Task {task_id} not found."

        actual_id = task.get("task_id", task_id)
        success = ledger.update_status(actual_id, "approved")
        if success:
            return f"✅ Task {actual_id} approved successfully."
        else:
            return f"❌ Failed to approve task {actual_id}."

    def _cmd_reject(self, args: str) -> str:
        task_id = args.strip()
        if not task_id:
            return "Usage: /reject <task_id>"

        ledger = TaskLedger(Config.MEMORY_ROOT)
        tasks = ledger.list_tasks()
        task = next(
            (t for t in tasks if t.get("task_id") == task_id or t.get("id") == task_id),
            None,
        )
        if not task:
            return f"Task {task_id} not found."

        actual_id = task.get("task_id", task_id)
        success = ledger.update_status(actual_id, "rejected")
        if success:
            return f"🚫 Task {actual_id} rejected."
        else:
            return f"❌ Failed to reject task {actual_id}."

    def _cmd_clear(self, request: IncomingRequest) -> str:
        if not hasattr(self.orchestrator, "_agent_runtime"):
            return "Agent runtime not initialized."

        session_manager = self.orchestrator._agent_runtime.session_manager
        session_manager.clear_session(request.user_id)
        return "🧹 Session memory cleared."

    def _cmd_model(self, args: str) -> str:
        if not hasattr(self.orchestrator, "_agent_runtime"):
            return "Agent runtime not initialized."

        args = args.strip()
        if args:
            self.orchestrator._agent_runtime.model_name = args
            return f"Model set to {args}"
        else:
            current_model = getattr(
                self.orchestrator._agent_runtime, "model_name", "unknown"
            )
            return f"Current model: {current_model}"

    def _cmd_tasks(self) -> str:
        ledger = TaskLedger(Config.MEMORY_ROOT)
        tasks = ledger.list_tasks()
        active_tasks = [
            t
            for t in tasks
            if t.get("status") in ["open", "in_progress", "pending_approval"]
        ]

        if not active_tasks:
            return "No active tasks."

        lines = ["**Active Tasks:**"]
        for t in active_tasks:
            task_id = t.get("task_id", t.get("id", "unknown"))
            status = t.get("status", "unknown")
            title = t.get("title", "Untitled")
            lines.append(f"• [{task_id}] ({status}) {title}")

        return "\n".join(lines)

    def _cmd_whoami(self, request: IncomingRequest) -> str:
        return f"Platform: {request.platform}\nUser ID: {request.user_id}\nChat ID: {request.reply_target.chat_id}"

    def _cmd_agents(self) -> str:
        if not hasattr(self.orchestrator, "_swarm_manager"):
            return "Swarm manager not initialized."

        agents = self.orchestrator._swarm_manager.agents
        if not agents:
            return "No agents registered."

        lines = ["**Registered Agents:**"]
        for name, agent in agents.items():
            lines.append(f"• `{name}`")

        return "\n".join(lines)

    def _cmd_plugins(self) -> str:
        try:
            registry = SkillRegistry()
            if hasattr(registry, "discover"):
                skills = registry.discover()
                if not skills:
                    return "No plugins loaded."
                lines = ["**Loaded Plugins:**"]
                for s in skills:
                    name = s.get("display_name", s.get("module_id", "Unknown"))
                    lines.append(f"• `{name}`")
                return "\n".join(lines)
            elif hasattr(registry, "summary"):
                skills_info = registry.summary()
                return json.dumps(skills_info, indent=2)
            else:
                return "SkillRegistry does not expose loaded skills."
        except Exception as e:
            return f"Error loading plugins: {str(e)}"

    def _cmd_bash(self, args: str) -> str:
        if not args:
            return "Usage: /bash <command> or !<command>"

        try:
            result = subprocess.run(args, shell=True, capture_output=True, text=True)
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += "\n" + result.stderr

            output = output.strip()
            if not output:
                output = "(Command executed successfully with no output)"

            # Truncate to 2000 chars
            if len(output) > 2000:
                output = output[:1997] + "..."

            return f"```bash\n$ {args}\n{output}\n```"
        except Exception as e:
            return f"Error executing bash command: {str(e)}"
