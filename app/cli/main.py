import argparse
import sys
import asyncio
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

    port = (
        int(Config.WEB_DASHBOARD_PORT)
        if hasattr(Config, "WEB_DASHBOARD_PORT")
        else 8090
    )
    host = (
        Config.WEB_DASHBOARD_HOST
        if hasattr(Config, "WEB_DASHBOARD_HOST")
        else "0.0.0.0"
    )

    print(f"Starting SARAS daemon... UI on http://{host}:{port}/ui")
    uvicorn.run("app.api.server:app", host=host, port=port)


def cmd_chat(args):
    """Starts a terminal chat interface."""
    from app.core.orchestrator import MessageOrchestrator
    from app.core.botsignal import BotSignal
    from app.core.models import IncomingRequest, ReplyTarget
    import builtins

    print("Welcome to SARAS terminal chat. Type 'quit' to exit.")

    async def chat_loop():
        signal = BotSignal()

        async def console_sender(target, payload):
            if payload.text:
                print(f"SARAS: {payload.text}")

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

    print("=== SARAS Status ===")
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
    """Runs as an edge device connected to SARAS."""
    from app.cli.edge_node import run_edge_node
    run_edge_node(
        name=args.name,
        server=args.server,
        capabilities=args.capabilities,
        location=args.location,
        sensors=args.sensors
    )

def main():

    parser = argparse.ArgumentParser(description="SARAS CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_daemon = subparsers.add_parser(
        "daemon", help="Start the SARAS daemon (FastAPI + Background Loops)"
    )
    parser_daemon.set_defaults(func=cmd_daemon)

    parser_chat = subparsers.add_parser(
        "chat", help="Start a simple terminal chat with SARAS"
    )
    parser_chat.set_defaults(func=cmd_chat)

    parser_status = subparsers.add_parser(
        "status", help="Show system status and pending approvals"
    )
    parser_status.set_defaults(func=cmd_status)

    parser_approve = subparsers.add_parser("approve", help="Approve a pending task")
    parser_approve.add_argument("task_id", help="The ID of the task to approve")
    parser_approve.set_defaults(func=cmd_approve)

    parser_edge = subparsers.add_parser("edge-node", help="Run as an edge device connected to SARAS")
    parser_edge.add_argument("--name", required=True, help="Name of the edge node")
    parser_edge.add_argument("--server", default="http://localhost:8090", help="URL of the SARAS server")
    parser_edge.add_argument("--capabilities", default="bash,python", help="Comma separated list of capabilities")
    parser_edge.add_argument("--location", default="unknown", help="Location of the node")
    parser_edge.add_argument("--sensors", default="", help="Comma separated list of sensors")
    parser_edge.set_defaults(func=cmd_edge_node)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
