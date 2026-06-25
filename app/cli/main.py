import argparse
import asyncio
import time
from app.core.task_ledger import TaskLedger


def cmd_daemon(args):
    """Starts the background loops and FastAPI web server."""
    import uvicorn
    from app.settings.config import Config
    import threading
    from main import _main_async
    import asyncio

    def background_thread():
        asyncio.run(_main_async())

    t = threading.Thread(target=background_thread, daemon=True)
    t.start()

    port = int(Config.WEB_DASHBOARD_PORT) if hasattr(Config, "WEB_DASHBOARD_PORT") else 8090
    host = Config.WEB_DASHBOARD_HOST if hasattr(Config, "WEB_DASHBOARD_HOST") else "0.0.0.0"

    print(f"Starting RAVEN daemon... UI on http://{host}:{port}/ui")
    uvicorn.run("app.api.server:app", host=host, port=port)


def cmd_run(args):
    """Start Raven — shows logs by default, --pid for silent daemon."""
    import os
    import signal
    import sys
    from pathlib import Path

    pid_file = Path.home() / ".raven" / "raven.pid"
    log_file = Path.home() / ".raven" / "raven.log"
    pid_file.parent.mkdir(parents=True, exist_ok=True)

    # Check if already running
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 0)  # Check if process exists
            print(f"Raven is already running (PID {old_pid})")
            print(f"  Stop it first: raven stop")
            print(f"  Or check logs: raven log")
            return
        except (ProcessLookupError, ValueError):
            pid_file.unlink(missing_ok=True)

    port = args.port or 8090
    voice_flag = "--no-voice" if args.no_voice else ""

    if args.pid:
        # Silent daemon mode — no logs, just PID file
        with open(log_file, "w") as log_fh:
            pid = os.fork()
            if pid > 0:
                # Parent
                pid_file.write_text(str(pid))
                print(f"Raven started as daemon (PID {pid})")
                print(f"  Dashboard: http://localhost:{port}/ui")
                print(f"  Logs: raven log")
                print(f"  Stop: raven stop")
                return
            else:
                # Child — redirect stdout/stderr to log file
                os.dup2(log_fh.fileno(), 1)
                os.dup2(log_fh.fileno(), 2)
                os.setsid()
                # Start the server
                import uvicorn
                sys.argv = ["raven", "daemon"]
                cmd_daemon(args)
                os._exit(0)
    else:
        # Foreground mode — show logs
        pid_file.write_text(str(os.getpid()))
        print("Starting Raven... (Ctrl+C to stop)")
        print(f"  Dashboard: http://localhost:{port}/ui")
        print(f"  Logs: raven log")
        print()
        try:
            cmd_daemon(args)
        except KeyboardInterrupt:
            print("\nRaven stopped.")
            pid_file.unlink(missing_ok=True)


def cmd_stop(args):
    """Stop the Raven daemon."""
    import os
    from pathlib import Path

    pid_file = Path.home() / ".raven" / "raven.pid"
    if not pid_file.exists():
        print("Raven is not running (no PID file found)")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Raven stopped (PID {pid})")
        pid_file.unlink(missing_ok=True)
    except ProcessLookupError:
        print("Raven was not running (stale PID)")
        pid_file.unlink(missing_ok=True)
    except Exception as e:
        print(f"Error stopping Raven: {e}")


def cmd_log(args):
    """Tail Raven logs."""
    from pathlib import Path

    log_file = Path.home() / ".raven" / "raven.log"
    if not log_file.exists():
        print("No logs found. Start Raven with: raven run")
        return

    lines = args.lines
    with open(log_file) as f:
        all_lines = f.readlines()
        for line in all_lines[-lines:]:
            print(line, end="")


def cmd_chat(args):
    """Starts a terminal chat interface."""
    from app.core.orchestrator import MessageOrchestrator
    from app.core.botsignal import BotSignal
    from app.core.models import IncomingRequest, ReplyTarget
    import builtins

    print("Welcome to RAVEN terminal chat. Type 'quit' to exit.")

    async def chat_loop():
        signal = BotSignal()

        async def console_sender(target, payload):
            if payload.text:
                print(f"RAVEN: {payload.text}")

        signal.register_sender("cli", console_sender)
        orchestrator = MessageOrchestrator(signal, output_directory="workspace")

        while True:
            try:
                user_input = builtins.input("You: ")
                if user_input.lower() in ["quit", "exit"]:
                    break

                req = IncomingRequest(
                    platform="cli",
                    user_id="cli_user",
                    text=user_input,
                    reply_target=ReplyTarget(platform="cli", chat_id="cli"),
                )
                await orchestrator.handle(req)
            except EOFError:
                break
            except KeyboardInterrupt:
                break

    asyncio.run(chat_loop())


def cmd_status(args):
    """Prints edge nodes and pending approvals."""
    from app.settings.config import Config
    import json

    ledger = TaskLedger(Config.MEMORY_ROOT)
    tasks = ledger.list_tasks()
    pending = [t for t in tasks if t.get("status") == "pending_approval"]

    print("=== RAVEN Status ===")
    print(f"Pending Approvals: {len(pending)}")
    for p in pending:
        print(f" - [{p.get('task_id')}] {p.get('title')}")

    print("\nEdge Nodes:")
    from pathlib import Path

    devices_file = Path(Config.MEMORY_ROOT) / "state" / "devices.json"
    if devices_file.exists():
        try:
            with open(devices_file, "r") as f:
                devices = json.load(f)
            if not devices:
                print(" - No edge nodes registered.")
            for device in devices:
                status = device.get("status", "unknown")
                print(f" - {device.get('id', 'unknown')} ({status})")
        except json.JSONDecodeError:
            print(" - Error reading devices.json.")
    else:
        print(" - No edge nodes registered.")


def cmd_approve(args):
    """Approves a task."""
    from app.settings.config import Config

    task_id = args.task_id
    ledger = TaskLedger(Config.MEMORY_ROOT)
    tasks = ledger.list_tasks()
    task = next(
        (t for t in tasks if t.get("task_id") == task_id or t.get("id") == task_id),
        None,
    )
    if not task:
        print(f"Task {task_id} not found.")
        return

    actual_id = task.get("task_id", task_id)
    success = ledger.update_status(actual_id, "approved")
    if success:
        print(f"Task {actual_id} approved successfully.")
    else:
        print(f"Failed to approve task {actual_id}.")


def cmd_edge_node(args):
    """Runs as an edge device connected to RAVEN."""
    from app.cli.edge_node import run_edge_node

    run_edge_node(
        name=args.name,
        server=args.server,
        capabilities=args.capabilities,
        location=args.location,
        sensors=args.sensors,
    )


def cmd_modules(args):
    """List and manage A2A modules."""
    import asyncio
    import json
    from raven_protocol import get_registry

    registry = get_registry()

    if args.action == "list":
        summary = registry.get_registry_summary()
        print(f"\n  RAVEN A2A Modules ({summary['total_modules']} registered)\n")
        for m in summary["modules"]:
            skills = ", ".join(m["skills"][:3])
            if len(m["skills"]) > 3:
                skills += f" (+{len(m['skills'])-3} more)"
            print(f"  {m['name']:15s} {m['description'][:50]:50s} [{skills}]")
        print()

    elif args.action == "discover":
        tags = args.args if args.args else ["all"]
        cards = registry.find_modules_by_skill(tags)
        print(f"\n  Modules matching tags: {', '.join(tags)}\n")
        for c in cards:
            print(f"  {c.name}: {c.description[:60]}")
        if not cards:
            print("  No modules found matching those tags.")
        print()

    elif args.action == "call":
        if len(args.args) < 2:
            print("Usage: raven modules call <module> <method> [json_params]")
            return
        module_name = args.args[0]
        method = args.args[1]
        params = json.loads(args.args[2]) if len(args.args) > 2 else {}

        async def _call():
            from raven_protocol import ModuleClient
            client = ModuleClient()
            return await client.call(module_name, f"{module_name}.{method}", params)

        result = asyncio.run(_call())
        print(json.dumps(result, indent=2, default=str))


def cmd_context(args):
    """Query user context."""
    import asyncio
    import json
    from raven_protocol import ModuleClient

    async def _query():
        client = ModuleClient()
        query = args.query

        if query == "all":
            mood = await client.call("context", "context.get_mood", {"user_id": "default"})
            location = await client.call("context", "context.get_location", {})
            activity = await client.call("context", "context.get_activity", {})
            environment = await client.call("context", "context.get_environment", {})
            return {"mood": mood, "location": location, "activity": activity, "environment": environment}
        else:
            return await client.call("context", f"context.get_{query}", {"user_id": "default"})

    result = asyncio.run(_query())
    print(json.dumps(result, indent=2, default=str))


def cmd_memory(args):
    """Memory operations."""
    import asyncio
    import json
    from raven_protocol import ModuleClient

    async def _run():
        client = ModuleClient()
        action = args.action

        if action == "remember" and args.args:
            content = " ".join(args.args)
            return await client.call("memory", "memory.remember", {"content": content, "category": "FACT"})
        elif action == "recall" and args.args:
            query = " ".join(args.args)
            return await client.call("memory", "memory.recall", {"query": query, "top_k": 5})
        elif action == "stats":
            from app.core.memory import get_memory_store
            store = get_memory_store()
            total, tools = store.count()
            return {"total_memories": total, "tool_guides": tools}
        elif action == "consolidate":
            from app.core.memory_consolidation import MemoryConsolidator
            consolidator = MemoryConsolidator()
            stats = await consolidator.consolidate()
            from dataclasses import asdict
            return asdict(stats)
        return {"error": f"Unknown memory action: {action}"}

    result = asyncio.run(_run())
    print(json.dumps(result, indent=2, default=str))


def cmd_evolve(args):
    """Self-evolution operations."""
    from app.core.self_evolution import SelfEvolutionSystem

    system = SelfEvolutionSystem()
    action = args.action

    if action == "goals":
        goals = system.get_active_goals()
        print(f"\n  Active Evolution Goals ({len(goals)})\n")
        for g in goals:
            progress = g.current_value / g.target_value if g.target_value > 0 else 0
            print(f"  {g.title}: {progress:.0%} ({g.category})")
        if not goals:
            print("  No active goals.")
        print()

    elif action == "metrics":
        summary = system.get_metric_summary()
        print(f"\n  Metrics ({len(summary)} tracked)\n")
        for name, data in summary.items():
            print(f"  {name}: avg={data['avg']:.2f}, latest={data['latest']:.2f}, count={data['count']}")
        print()

    elif action == "assess":
        report = system.generate_improvement_report()
        print(report)

    elif action == "report":
        report = system.generate_improvement_report()
        print(report)


RAVEN_LOGO = """
    ╔══════════════════════════════════════════╗
    ║                                          ║
    ║   ██████╗  █████╗ ██████╗ ████████╗      ║
    ║   ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝      ║
    ║   ██████╔╝███████║██║  ██║   ██║          ║
    ║   ██╔══██╗██╔══██║██║  ██║   ██║          ║
    ║   ██║  ██║██║  ██║██████╔╝   ██║          ║
    ║   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝    ╚═╝          ║
    ║                                          ║
    ║   ██████╗  █████╗ ██████╗ ████████╗      ║
    ║   ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝      ║
    ║   ██████╔╝███████║██║  ██║   ██║          ║
    ║   ██╔══██╗██╔══██║██║  ██║   ██║          ║
    ║   ██║  ██║██║  ██║██████╔╝   ██║          ║
    ║   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝    ╚═╝          ║
    ║                                          ║
    ║   Your JARVIS-class AI Agent              ║
    ╚══════════════════════════════════════════╝
"""


def main():

    parser = argparse.ArgumentParser(
        description="RAVEN — Your JARVIS-class AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=RAVEN_LOGO,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_daemon = subparsers.add_parser(
        "daemon", help="Start the RAVEN daemon (FastAPI + Background Loops)"
    )
    parser_daemon.set_defaults(func=cmd_daemon)

    parser_chat = subparsers.add_parser("chat", help="Start a simple terminal chat with RAVEN")
    parser_chat.set_defaults(func=cmd_chat)

    parser_status = subparsers.add_parser("status", help="Show system status and pending approvals")
    parser_status.set_defaults(func=cmd_status)

    parser_approve = subparsers.add_parser("approve", help="Approve a pending task")
    parser_approve.add_argument("task_id", help="The ID of the task to approve")
    parser_approve.set_defaults(func=cmd_approve)

    parser_edge = subparsers.add_parser(
        "edge-node", help="Run as an edge device connected to RAVEN"
    )
    parser_edge.add_argument("--name", required=True, help="Name of the edge node")
    parser_edge.add_argument(
        "--server", default="http://localhost:8090", help="URL of the RAVEN server"
    )
    parser_edge.add_argument(
        "--capabilities", default="bash,python", help="Comma separated list of capabilities"
    )
    parser_edge.add_argument("--location", default="unknown", help="Location of the node")
    parser_edge.add_argument("--sensors", default="", help="Comma separated list of sensors")
    parser_edge.set_defaults(func=cmd_edge_node)

    # Phase 10 — `raven mode` (registered via a sub-module so tests
    # can import the handlers without pulling in the whole CLI).
    try:
        from app.cli.mode_cmd import add_mode_subparser  # type: ignore

        add_mode_subparser(subparsers)
    except Exception as exc:  # noqa: BLE001
        import logging as _logging

        _logging.getLogger(__name__).debug("mode subparser not registered: %s", exc)

    # ── `raven helix` ─────────────────────────────────────────────
    parser_helix = subparsers.add_parser("helix", help="Manage HelixDB sidecar (up/down/status)")
    parser_helix.add_argument(
        "action", choices=["up", "down", "status", "logs"], help="Action to perform"
    )
    parser_helix.set_defaults(func=cmd_helix)

    # ── `raven kg` ───────────────────────────────────────────────
    parser_kg = subparsers.add_parser("kg", help="Knowledge graph operations (query/stats)")
    parser_kg.add_argument(
        "action", choices=["query", "stats", "entities"], help="Action to perform"
    )
    parser_kg.add_argument("query", nargs="?", default="", help="Search query or entity name")
    parser_kg.set_defaults(func=cmd_kg)

    # ── `raven providers` (v35 — 9router-style card system) ───────
    parser_providers = subparsers.add_parser(
        "providers",
        help="Provider / model / combo management (CLI ↔ UI parity)",
    )
    parser_providers.add_argument(
        "action",
        choices=[
            "list",
            "select",
            "combo",
            "health",
            "stats",
            "probe",
        ],
        help="Action to perform",
    )
    parser_providers.add_argument(
        "args", nargs="*", help="Action-specific arguments (provider_id, model_id, combo name, ...)"
    )
    parser_providers.set_defaults(func=cmd_providers)

    # ── `raven modules` — A2A module management ──────────────────
    parser_modules = subparsers.add_parser(
        "modules", help="List and manage A2A modules"
    )
    parser_modules.add_argument(
        "action", choices=["list", "discover", "call"],
        help="Action to perform"
    )
    parser_modules.add_argument("args", nargs="*", help="Module name, method, or tags")
    parser_modules.set_defaults(func=cmd_modules)

    # ── `raven context` — user context queries ──────────────────
    parser_context = subparsers.add_parser(
        "context", help="Query user context (mood, location, activity)"
    )
    parser_context.add_argument(
        "query", nargs="?", default="all",
        help="Context to query: mood, location, activity, environment, all"
    )
    parser_context.set_defaults(func=cmd_context)

    # ── `raven memory` — memory operations ──────────────────────
    parser_memory = subparsers.add_parser(
        "memory", help="Memory operations (remember, recall, stats)"
    )
    parser_memory.add_argument(
        "action", choices=["remember", "recall", "stats", "consolidate"],
        help="Action to perform"
    )
    parser_memory.add_argument("args", nargs="*", help="Memory content or query")
    parser_memory.set_defaults(func=cmd_memory)

    # ── `raven evolve` — self-evolution ─────────────────────────
    parser_evolve = subparsers.add_parser(
        "evolve", help="Self-evolution: goals, metrics, assessment"
    )
    parser_evolve.add_argument(
        "action", choices=["goals", "metrics", "assess", "report"],
        help="Action to perform"
    )
    parser_evolve.set_defaults(func=cmd_evolve)

    # ── `raven cowork` (v36 — Kimi/Claude-style folder sessions) ─
    parser_cowork = subparsers.add_parser(
        "cowork",
        help="Cowork sessions: pick a folder, propose a plan, approve steps",
    )
    parser_cowork.add_argument(
        "action",
        choices=[
            "list-ws",
            "add-ws",
            "rm-ws",
            "list",
            "start",
            "pause",
            "resume",
            "stop",
            "approve-all",
            "approve",
            "reject",
            "events",
            "active",
        ],
        help="Action to perform",
    )
    parser_cowork.add_argument("args", nargs="*", help="Action-specific arguments")
    parser_cowork.add_argument(
        "--strategy",
        choices=["default", "llm", "rule"],
        default="default",
        help="Planner strategy (default: rule-based, llm: use the configured LLM)",
    )
    parser_cowork.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve low-risk steps (applies to 'start')",
    )
    parser_cowork.set_defaults(func=cmd_cowork)

    # ── `raven train-data` — training data export ─────────────────
    parser_train = subparsers.add_parser(
        "train-data",
        help="Export conversation training data (JSONL)",
    )
    parser_train.add_argument(
        "action",
        choices=["export", "stats"],
        help="Action to perform",
    )
    parser_train.add_argument(
        "--session", "-s",
        help="Session ID to export (all sessions if omitted)",
    )
    parser_train.add_argument(
        "--output", "-o",
        help="Output file path (auto-named if omitted)",
    )
    parser_train.set_defaults(func=cmd_train_data)

    # ── `raven world-model` — world model operations ────────────
    parser_wm = subparsers.add_parser(
        "world-model", help="World model: people, projects, habits, timeline"
    )
    parser_wm.add_argument(
        "action",
        choices=["people", "projects", "habits", "events", "context"],
        help="Action to perform",
    )
    parser_wm.add_argument("args", nargs="*", help="Filter arguments")
    parser_wm.set_defaults(func=cmd_world_model)

    # ── `raven personality` — adaptive personality ──────────────
    parser_pers = subparsers.add_parser(
        "personality", help="Adaptive personality: traits, vocabulary, styles"
    )
    parser_pers.add_argument(
        "action", choices=["traits", "vocabulary", "styles", "prompt"],
        help="Action to perform",
    )
    parser_pers.set_defaults(func=cmd_personality)

    # ── `raven companion` — companion AI management ─────────────
    parser_comp = subparsers.add_parser(
        "companion", help="Companion AI: list, delegate, status"
    )
    parser_comp.add_argument(
        "action", choices=["list", "status", "summary"],
        help="Action to perform",
    )
    parser_comp.set_defaults(func=cmd_companion)

    # ── `raven run` — start Raven (background or foreground) ─────
    parser_run = subparsers.add_parser(
        "run", help="Start Raven (background by default, with logs)"
    )
    parser_run.add_argument(
        "--pid", action="store_true",
        help="Run as daemon PID file (background, no logs)",
    )
    parser_run.add_argument(
        "--port", "-p", type=int, default=None,
        help="Dashboard port (default: 8090)",
    )
    parser_run.add_argument(
        "--no-voice", action="store_true",
        help="Disable voice pipeline",
    )
    parser_run.set_defaults(func=cmd_run)

    # ── `raven stop` — stop Raven daemon ─────────────────────────
    parser_stop = subparsers.add_parser("stop", help="Stop Raven daemon")
    parser_stop.set_defaults(func=cmd_stop)

    # ── `raven status` — show system status ──────────────────────
    parser_status2 = subparsers.add_parser("status", help="Show Raven status and health")
    parser_status2.set_defaults(func=cmd_status)

    # ── `raven log` — tail live logs ─────────────────────────────
    parser_log = subparsers.add_parser("log", help="Tail Raven logs")
    parser_log.add_argument(
        "--lines", "-n", type=int, default=50,
        help="Number of log lines to show",
    )
    parser_log.set_defaults(func=cmd_log)

    args = parser.parse_args()
    args.func(args)


def cmd_train_data(args: argparse.Namespace) -> None:
    """Export conversation data as JSONL for model training."""
    import json as _json
    from pathlib import Path

    from app.core.session import SessionManager

    sm = SessionManager()
    sessions = sm.list_sessions()

    if not sessions:
        print("No sessions found.")
        return

    all_examples: list[dict] = []

    if args.session:
        target = [s for s in sessions if s.session_id == args.session]
        if not target:
            print(f"Session {args.session} not found.")
            return
        sessions = target

    for sess in sessions:
        messages = [
            {"role": "user", "content": sess.get("user_text", "")},
            {"role": "assistant", "content": sess.get("response_text", "")},
        ]
        for i, msg in enumerate(messages):
            if msg["role"] == "user" and i + 1 < len(messages) and messages[i + 1]["role"] == "assistant":
                resp = messages[i + 1].get("content", "")
                if resp and len(resp) > 10:
                    all_examples.append({
                        "instruction": msg.get("content", ""),
                        "input": "",
                        "output": resp[:500],
                        "metadata": {"session_id": sess.session_id},
                    })

    if args.action == "stats":
        print(f"Sessions: {len(sessions)}")
        print(f"Training examples: {len(all_examples)}")
        return

    if not all_examples:
        print("No training examples generated.")
        return

    out_path = args.output or f"workspace/training_data/training_{int(time.time())}.jsonl"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for ex in all_examples:
            f.write(_json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"Exported {len(all_examples)} training examples to {out_path}")


def cmd_world_model(args: argparse.Namespace) -> None:
    """World model CLI commands."""
    from app.core.world_model import WorldModel

    wm = WorldModel()
    if args.action == "people":
        people = wm.find_entities("person")
        print(f"=== People ({len(people)}) ===")
        for p in people[:30]:
            rels = [r.get("type", "") for r in p.relationships[:3]]
            print(f"  {p.name}: {', '.join(rels) if rels else 'no relationships'}")
    elif args.action == "projects":
        projects = wm.find_entities("project")
        print(f"=== Projects ({len(projects)}) ===")
        for p in projects[:30]:
            print(f"  {p.name}: {p.properties.get('status', 'unknown')}")
    elif args.action == "habits":
        habits = wm._load_habits()
        print(f"=== Habits ({len(habits)}) ===")
        for name, timestamps in habits.items():
            freq = wm.get_habit_frequency(name)
            print(f"  {name}: {len(timestamps)} records, ~{freq:.1f}x/day")
    elif args.action == "events":
        events = wm.get_recent_events(20)
        print(f"=== Recent Events ({len(events)}) ===")
        for e in events:
            print(f"  [{e.event_type}] {e.title}")
    elif args.action == "context":
        ctx = wm.build_world_context()
        print(ctx if ctx else "No world model data yet.")


def cmd_personality(args: argparse.Namespace) -> None:
    """Adaptive personality CLI commands."""
    from app.core.adaptive_personality import AdaptivePersonality

    ap = AdaptivePersonality()
    profile = ap.get_profile()
    if args.action == "traits":
        print("=== Personality Traits ===")
        for name, trait in profile.traits.items():
            bar = "█" * int(trait.value * 20) + "░" * (20 - int(trait.value * 20))
            print(f"  {name:15s} [{bar}] {trait.value:.2f} ({trait.trend})")
    elif args.action == "vocabulary":
        top = sorted(profile.vocabulary.items(), key=lambda x: x[1], reverse=True)[:20]
        print(f"=== Top Vocabulary ({len(profile.vocabulary)} words) ===")
        for word, count in top:
            print(f"  {word}: {count}")
    elif args.action == "styles":
        top = sorted(profile.response_styles.items(), key=lambda x: x[1], reverse=True)
        print("=== Response Styles ===")
        for style, count in top:
            print(f"  {style}: {count}")
    elif args.action == "prompt":
        print(ap.get_personality_prompt())


def cmd_companion(args: argparse.Namespace) -> None:
    """Companion AI CLI commands."""
    from app.core.companion_ai import get_companion_manager

    mgr = get_companion_manager()
    if args.action == "list":
        companions = mgr.list_companions()
        print(f"=== Companion AIs ({len(companions)}) ===")
        for c in companions:
            print(f"  {c.name}: {c.status} — {c.description[:60]}")
    elif args.action == "status":
        summary = mgr.get_collaboration_summary()
        print("=== Companion Status ===")
        for k, v in summary.items():
            print(f"  {k}: {v}")
    elif args.action == "summary":
        import json as _json
        print(_json.dumps(mgr.get_collaboration_summary(), indent=2))


def cmd_helix(args: argparse.Namespace) -> None:
    """Run ./scripts/start_helix.sh {up|down|status|logs}."""
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "start_helix.sh"
    if not script.exists():
        print(f"Error: HelixDB script not found at {script}")
        raise SystemExit(1)

    result = subprocess.run(
        [str(script), args.action],
        capture_output=False,
        timeout=120 if args.action == "up" else 30,
    )
    raise SystemExit(result.returncode)


def cmd_kg(args: argparse.Namespace) -> None:
    """Knowledge graph CLI commands."""
    from app.core.knowledge_manager import get_knowledge_manager
    import json

    km = get_knowledge_manager()

    if args.action == "stats":
        try:
            from app.tools.kgtool import KnowledgeGraphTool

            tool = KnowledgeGraphTool()
            stats = tool.get_stats() if hasattr(tool, "get_stats") else {}
            print("=== Knowledge Graph Stats ===")
            print(json.dumps(stats, indent=2))
        except Exception as e:
            print(f"Error: {e}")
        return

    if args.action == "entities":
        entities = km.query("") if hasattr(km, "query") else []
        print(f"=== Entities ({len(entities)}) ===")
        for ent in entities[:50]:
            print(f"  {ent}")
        return

    if args.action == "query":
        q = args.query or input("Enter query: ").strip()
        results = km.query(q) if hasattr(km, "query") else []
        print(f"=== Results for '{q}' ({len(results)}) ===")
        for r in results[:20]:
            print(json.dumps(r, indent=2, default=str))
        return


def cmd_providers(args: argparse.Namespace) -> None:
    """CLI parity for the provider / combo / health UI.

    Subcommands
    -----------
    list                              — show every provider + health + tier
    select <provider_id> [model_id]   — activate a provider/model
    combo list                        — show all combos + active
    combo use <name>                  — activate a combo
    combo create <name> <p1,p2,...>   — create or update a combo
    combo delete <name>               — delete a combo
    health                            — probe every provider, show status
    stats                             — show per-model call stats
    probe <provider_id>               — probe a single provider
    """
    from app.provider.manager import ProviderManager
    from app.provider.registry import PROVIDER_REGISTRY, get_provider
    from app.provider.health import (
        all_health,
        all_stats,
        probe_provider,
    )

    manager = ProviderManager()
    action = args.action
    cli_args = args.args or []

    if action == "list":
        print("=== Providers ===")
        print(f"{'ID':<14} {'NAME':<32} {'TIER':<14} {'GROUP':<12} {'HEALTH':<10} {'LATENCY':<10}")
        print("-" * 100)
        for p in PROVIDER_REGISTRY:
            h = all_health().get(p.id)
            health_label = h.status_label if h else "unchecked"
            latency = f"{h.avg_latency_ms:.0f}ms" if h and h.ok else "—"
            tier = f"{p.tier.value}/{p.group}"
            print(
                f"{p.id:<14} {p.name[:32]:<32} {tier:<14} {p.group:<12} {health_label:<10} {latency:<10}"
            )
        active = manager.get_active_combo()
        if active:
            print(f"\nActive combo: {active}")
        return

    if action == "select":
        if len(cli_args) < 1:
            print("Usage: raven providers select <provider_id> [model_id]")
            return
        pid = cli_args[0]
        info = get_provider(pid)
        if not info:
            print(f"Unknown provider: {pid}")
            return
        mid = cli_args[1] if len(cli_args) > 1 else info.default_model
        manager.active_provider = pid
        manager.active_model = mid
        print(f"✓ Activated: {pid}/{mid}")
        return

    if action == "combo":
        if not cli_args or cli_args[0] == "list":
            combos = manager.get_combos()
            active = manager.get_active_combo()
            print("=== Combos ===")
            for name, providers in combos.items():
                marker = "● " if name == active else "  "
                print(f"{marker}{name:<20} → {' → '.join(providers)}")
            if not active:
                print("\n(no active combo — falls back to ranking / auto)")
            return
        if cli_args[0] == "use":
            if len(cli_args) < 2:
                print("Usage: raven providers combo use <name>")
                return
            manager.set_active_combo(cli_args[1])
            print(f"✓ Activated combo: {cli_args[1]}")
            return
        if cli_args[0] == "create":
            if len(cli_args) < 3:
                print("Usage: raven providers combo create <name> <p1,p2,...>")
                return
            name = cli_args[1]
            providers = [p.strip() for p in cli_args[2].split(",") if p.strip()]
            manager.upsert_combo(name, providers)
            print(f"✓ Combo '{name}' saved: {providers}")
            return
        if cli_args[0] == "delete":
            if len(cli_args) < 2:
                print("Usage: raven providers combo delete <name>")
                return
            ok = manager.delete_combo(cli_args[1])
            print(f"{'✓' if ok else '✗'} Combo '{cli_args[1]}': {'deleted' if ok else 'not found'}")
            return
        print(f"Unknown combo subcommand: {cli_args[0]}")
        return

    if action == "health":

        async def _health():
            return await manager.refresh_health()

        results = asyncio.run(_health())
        print("=== Provider Health ===")
        print(f"{'ID':<14} {'STATUS':<12} {'LATENCY':<12} {'ERROR'}")
        print("-" * 80)
        for pid, h in sorted(results.items()):
            err = h.get("error", "")[:30] if h.get("error") else ""
            lat = f"{h.get('avg_latency_ms', 0):.0f}ms" if h.get("ok") else "—"
            print(f"{pid:<14} {h.get('status', '?'):<12} {lat:<12} {err}")
        return

    if action == "stats":
        rows = all_stats()
        if not rows:
            print("No stats yet — no LLM calls have been recorded.")
            return
        print("=== Call Stats ===")
        print(f"{'PROVIDER':<14} {'MODEL':<32} {'CALLS':<8} {'OK%':<8} {'AVG MS':<10} {'TOKENS'}")
        print("-" * 90)
        for s in sorted(rows, key=lambda r: (r.provider_id, r.model_id)):
            ok_pct = f"{s.success_rate * 100:.0f}%" if s.calls else "—"
            avg_ms = f"{s.avg_latency_ms:.0f}" if s.avg_latency_ms else "—"
            tokens = s.tokens_in + s.tokens_out
            mid = (s.model_id or "*")[:32]
            print(f"{s.provider_id:<14} {mid:<32} {s.calls:<8} {ok_pct:<8} {avg_ms:<10} {tokens}")
        return

    if action == "probe":
        if not cli_args:
            print("Usage: raven providers probe <provider_id>")
            return
        pid = cli_args[0]
        info = get_provider(pid)
        if not info:
            print(f"Unknown provider: {pid}")
            return

        async def _probe_one():
            return await probe_provider(pid, info.base_url)

        h = asyncio.run(_probe_one())
        status = "✓ healthy" if h.ok else "✗ down"
        print(
            f"{pid}: {status} ({h.latency_ms:.0f}ms avg {h.avg_latency_ms:.0f}ms) {h.error or ''}"
        )
        return

    print(f"Unknown action: {action}")


def cmd_cowork(args: argparse.Namespace) -> None:
    """CLI parity for the cowork dashboard.

    Subcommands
    -----------
    list-ws                       — show every workspace
    add-ws <name> <path> [ro|rw]  — add a workspace
    rm-ws <workspace_id>          — remove a workspace
    list                          — show all sessions
    active                        — show the in-flight session
    start <workspace_id> <goal>   — start a new session
    pause <session_id>            — pause a session
    resume <session_id>           — resume a paused session
    stop <session_id>             — stop a session
    approve-all <session_id>      — bulk-approve the active plan
    approve <session_id> <step>   — approve a step
    reject <session_id> <step>    — reject a step
    events <session_id>           — print the event log
    """
    from app.cowork import get_cowork_manager

    mgr = get_cowork_manager()
    action = args.action
    cli_args = args.args or []

    if action == "list-ws":
        ws = mgr.list_workspaces()
        if not ws:
            print("No workspaces. Add one: raven cowork add-ws <name> <path>")
            return
        print("=== Workspaces ===")
        for w in ws:
            print(
                f"  [{w['id']}] {w['name']:<20} {w['access']:<2}  {w['path']}"
            )
        return

    if action == "add-ws":
        if len(cli_args) < 2:
            print("Usage: raven cowork add-ws <name> <path> [ro|rw]")
            return
        name, path = cli_args[0], cli_args[1]
        access = cli_args[2] if len(cli_args) > 2 else "rw"
        try:
            ws = mgr.add_workspace(name=name, path=path, access=access)
            print(f"✓ Added workspace [{ws['id']}]: {ws['name']} ({ws['path']})")
        except (ValueError, OSError) as exc:
            print(f"✗ {exc}")
        return

    if action == "rm-ws":
        if not cli_args:
            print("Usage: raven cowork rm-ws <workspace_id>")
            return
        ok = mgr.remove_workspace(cli_args[0])
        print(f"{'✓' if ok else '✗'} Workspace {cli_args[0]}: {'removed' if ok else 'not found'}")
        return

    if action == "list":
        sessions = mgr.list_sessions()
        if not sessions:
            print("No sessions yet.")
            return
        print("=== Sessions ===")
        for s in sessions:
            print(f"  [{s['id'][:8]}] {s['state']:<20}  {s['goal']}")
        return

    if action == "active":
        active = mgr.get_active_session()
        if not active:
            print("No active session.")
            return
        print("=== Active session ===")
        print(f"  id    : {active['id']}")
        print(f"  state : {active['state']}")
        print(f"  goal  : {active['goal']}")
        if active.get("plan"):
            plan = active["plan"]
            print(f"  plan  : {plan['progress'][0]}/{plan['progress'][1]} steps done")
            for s in plan["steps"]:
                print(
                    f"    [{s['id'][:6]}] {s['status']:<20} {s['risk']:<6}  {s['title']}"
                )
        return

    if action == "start":
        if len(cli_args) < 2:
            print("Usage: raven cowork start <workspace_id> <goal> [--strategy default|llm] [--auto-approve]")
            return
        ws_id, goal = cli_args[0], " ".join(cli_args[1:])
        strategy = getattr(args, "strategy", None) or "default"
        auto_approve = bool(getattr(args, "auto_approve", False))

        async def _start():
            return await mgr.start_session(
                workspace_id=ws_id,
                goal=goal,
                auto_approve_low_risk=auto_approve,
                strategy=strategy,
            )

        sess = asyncio.run(_start())
        print(f"✓ Started session [{sess['id']}]: {sess['goal']}")
        plan = sess.get("plan") or {}
        print(
            f"  planner : {strategy:<6}  "
            f"steps: {len(plan.get('steps', []))}"
        )
        for s in plan.get("steps", []):
            print(
                f"    [{s['id'][:6]}] {s['status']:<20} {s['risk']:<6}  {s['title']}"
            )
        return

    if action in {"pause", "resume", "stop", "approve-all"}:
        if not cli_args:
            print(f"Usage: raven cowork {action} <session_id>")
            return
        sid = cli_args[0]
        method = {
            "pause": mgr.pause_session,
            "resume": mgr.resume_session,
            "stop": mgr.stop_session,
            "approve-all": mgr.approve_all,
        }[action]
        ok = method(sid)
        print(f"{'✓' if ok else '✗'} {action} {sid}: {'ok' if ok else 'failed'}")
        return

    if action in {"approve", "reject"}:
        if len(cli_args) < 2:
            print(f"Usage: raven cowork {action} <session_id> <step_id>")
            return
        sid, step_id = cli_args[0], cli_args[1]
        method = mgr.approve_step if action == "approve" else mgr.reject_step
        ok = method(sid, step_id)
        print(f"{'✓' if ok else '✗'} {action} {step_id}: {'ok' if ok else 'failed'}")
        return

    if action == "events":
        if not cli_args:
            print("Usage: raven cowork events <session_id>")
            return
        events = mgr.read_events(cli_args[0])
        if not events:
            print("No events.")
            return
        for e in events:
            ts = time.strftime("%H:%M:%S", time.localtime(e["ts"]))
            print(f"  {ts}  {e['kind']:<22}  {e.get('payload', {})}")
        return

    print(f"Unknown action: {action}")


if __name__ == "__main__":
    main()
