"""``raven mode`` — inspect and override the operating mode.

The mode CLI is a thin wrapper around :mod:`app.runtime.mode`.  It
exists so the operator (or a script) can:

  * see the current mode and the auto-detector's last probe;
  * see the recent history of mode changes;
  * set an explicit override (e.g. force ``offline`` for a test
    soak run) with a TTL so the override does not pin the system
    forever;
  * clear an override and let the auto-detector resume.

The state is shared across processes via a small JSON file in the
workspace (``workspace/mode_state.json`` by default).  The
:class:`app.runtime.mode.ModeDetector` reads and writes the same
file, so any process that imports the detector sees the operator's
override and any process that uses this CLI sees the detector's
last probe.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


#: Default state file.  Overridden by ``RAVEN_MODE_STATE_FILE`` env var.
DEFAULT_STATE_PATH = os.environ.get("RAVEN_MODE_STATE_FILE", "workspace/mode_state.json")


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _format_history(history: list[dict[str, Any]]) -> str:
    if not history:
        return "  (no transitions recorded)"
    lines: list[str] = []
    for h in history[-10:]:
        at = float(h.get("at", 0.0))
        at_s = time.strftime("%H:%M:%S", time.localtime(at))
        lines.append(
            f"  {at_s}  {h.get('from', '?')} -> {h.get('to', '?')}  ({h.get('reason', '')})"
        )
    return "\n".join(lines)


def cmd_mode_show(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    data = _load_state(state_path)
    if not data:
        print("(no mode state recorded yet — the auto-detector has not run)")
        return 0
    print(f"State file:        {state_path}")
    print(f"Effective mode:    {data.get('mode', 'unknown')}")
    print(f"Auto-detected:     {data.get('auto', 'unknown')}")
    override = data.get("override")
    expires = float(data.get("override_expires_at", 0.0))
    if override:
        remaining = max(0.0, expires - time.time())
        print(f"Operator override: {override}  (expires in {remaining:.0f}s)")
    else:
        print("Operator override: (none)")
    last_at = float(data.get("last_probe_at", 0.0))
    if last_at:
        age = max(0.0, time.time() - last_at)
        ok = data.get("last_probe_ok", True)
        status = "ok" if ok else "FAIL"
        print(f"Last probe:        {status}  ({age:.1f}s ago)")
    print(
        f"Consecutive:       passes={data.get('consecutive_passes', 0)}  "
        f"fails={data.get('consecutive_fails', 0)}"
    )
    err = data.get("last_error") or ""
    if err:
        print(f"Last error:        {err}")
    print("Recent transitions:")
    print(_format_history(data.get("history", [])))
    return 0


def cmd_mode_set(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    data = _load_state(state_path)
    now = time.time()
    data["override"] = args.mode
    data["override_expires_at"] = now + max(0, int(args.ttl))
    data.setdefault("history", []).append(
        {
            "at": now,
            "from": data.get("mode", "unknown"),
            "to": args.mode,
            "reason": f"cli override ttl={int(args.ttl)}s",
        }
    )
    # Trim history.
    data["history"] = data["history"][-32:]
    _save_state(state_path, data)
    print(f"Override set: {args.mode} (ttl={int(args.ttl)}s)")
    return 0


def cmd_mode_clear(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    data = _load_state(state_path)
    data["override"] = None
    data["override_expires_at"] = 0.0
    _save_state(state_path, data)
    print("Override cleared")
    return 0


def cmd_mode_history(args: argparse.Namespace) -> int:
    state_path = Path(args.state_file)
    data = _load_state(state_path)
    history = data.get("history", [])
    if not history:
        print("(no transitions recorded)")
        return 0
    for h in history:
        at = float(h.get("at", 0.0))
        at_s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at))
        print(f"{at_s}  {h.get('from', '?'):>9} -> {h.get('to', '?'):<9}  ({h.get('reason', '')})")
    return 0


def add_mode_subparser(
    subparsers: argparse._SubParsersAction,  # type: ignore[name-defined]
) -> None:
    """Register ``mode show|set|clear|history`` on the given subparsers."""
    parser_mode = subparsers.add_parser("mode", help="Inspect and override the operating mode")
    parser_mode.add_argument(
        "--state-file",
        default=DEFAULT_STATE_PATH,
        help=f"Path to the shared mode state file (default: {DEFAULT_STATE_PATH})",
    )
    mode_subs = parser_mode.add_subparsers(dest="mode_command", required=True)

    def _add_state_file(p: argparse.ArgumentParser) -> None:
        # Allow ``--state-file`` to appear either before or after the
        # subcommand verb.
        p.add_argument(
            "--state-file",
            default=DEFAULT_STATE_PATH,
            help="Path to the shared mode state file",
        )

    p_show = mode_subs.add_parser("show", help="Show current mode + probe state")
    _add_state_file(p_show)
    p_show.set_defaults(func=cmd_mode_show)

    p_set = mode_subs.add_parser("set", help="Set an operator override")
    _add_state_file(p_set)
    p_set.add_argument(
        "mode",
        choices=["online", "degraded", "offline"],
        help="Mode to force",
    )
    p_set.add_argument(
        "--ttl",
        type=int,
        default=300,
        help="Override TTL in seconds (default: 300)",
    )
    p_set.set_defaults(func=cmd_mode_set)

    p_clear = mode_subs.add_parser("clear", help="Clear any operator override")
    _add_state_file(p_clear)
    p_clear.set_defaults(func=cmd_mode_clear)

    p_hist = mode_subs.add_parser("history", help="Show recent mode transitions")
    _add_state_file(p_hist)
    p_hist.set_defaults(func=cmd_mode_history)


__all__ = [
    "DEFAULT_STATE_PATH",
    "add_mode_subparser",
    "cmd_mode_clear",
    "cmd_mode_history",
    "cmd_mode_set",
    "cmd_mode_show",
]
