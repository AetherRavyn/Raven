#!/usr/bin/env python3
"""
log_panel.py — SARAS Live Log Viewer
──────────────────────────────────────────────────────────────────────────────
Run this in a second terminal while test_saras_agent.py is running.
Watches workspace/saras.log (JSON lines) and renders a live colour-coded panel.

Usage:
  uv run python log_panel.py                     # watch workspace/saras.log
  uv run python log_panel.py --file my.log       # watch a different log file
  uv run python log_panel.py --level INFO        # filter: show INFO and above
  uv run python log_panel.py --filter runtime    # only show lines where name contains "runtime"
  uv run python log_panel.py --tail 200          # keep last N lines visible (default 100)
  uv run python log_panel.py --level DEBUG --filter app.core

Keyboard shortcuts (while panel is running):
  q / Ctrl+C   quit
  c            clear display (does NOT clear the log file)
  d            toggle DEBUG lines on/off
  f            cycle through level filters: ALL → INFO → WARNING → ERROR
"""

from __future__ import annotations

import json
import os
import sys
import time
import threading
from collections import deque
from pathlib import Path
from typing import Deque, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_LOG_FILE = "workspace/saras.log"
POLL_INTERVAL = 0.25  # seconds between file reads
DEFAULT_TAIL = 100  # lines kept in display buffer

LEVEL_ORDER = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LEVEL_CYCLE = ["DEBUG", "INFO", "WARNING", "ERROR"]  # cycled by 'f' key

# ──────────────────────────────────────────────────────────────────────────────
# COLOUR MAP
# ──────────────────────────────────────────────────────────────────────────────

LEVEL_STYLE = {
    "DEBUG": "dim white",
    "INFO": "bright_white",
    "WARNING": "bold yellow",
    "ERROR": "bold red",
    "CRITICAL": "bold red on white",
}

NAME_STYLE = "cyan"
TIME_STYLE = "dim"
MSG_STYLE = {
    "DEBUG": "dim",
    "INFO": "white",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "bold red",
}

# Shorten common logger prefixes for readability
NAME_ALIASES = {
    "app.core.runtime": "runtime",
    "app.core.orchestrator": "orchestrator",
    "app.core.agency": "agency",
    "app.core.botsignal": "botsignal",
    "app.core.session": "session",
    "app.core.security": "security",
    "app.core.bootstrapper": "bootstrapper",
    "app.minichat.minichat": "minichat",
    "app.telegram.bot": "telegram",
    "app.telegram.command": "tg.cmd",
    "app.discord.discordapp": "discord",
    "app.tools": "tools",
    "__main__": "main",
    "test_saras_agent": "test",
}


def _shorten_name(name: str) -> str:
    if name in NAME_ALIASES:
        return NAME_ALIASES[name]
    for prefix, alias in NAME_ALIASES.items():
        if name.startswith(prefix + "."):
            return alias + name[len(prefix) :]
    # Shorten long dotted names: app.tools.filetool → tools.filetool
    parts = name.split(".")
    if len(parts) > 3:
        return ".".join(parts[-2:])
    return name


# ──────────────────────────────────────────────────────────────────────────────
# LOG LINE PARSER
# ──────────────────────────────────────────────────────────────────────────────


def _parse_line(raw: str) -> Optional[dict]:
    """Parse a JSON log line. Returns None if not parseable."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: treat as plain text at INFO level
        return {"t": "", "ms": 0, "lvl": "INFO", "name": "?", "msg": raw}


# ──────────────────────────────────────────────────────────────────────────────
# SHARED STATE
# ──────────────────────────────────────────────────────────────────────────────


class LogState:
    def __init__(self, tail: int, min_level: str, name_filter: str) -> None:
        self.lines: Deque[dict] = deque(maxlen=tail)
        self.tail = tail
        self.min_level_idx = (
            LEVEL_ORDER.index(min_level) if min_level in LEVEL_ORDER else 0
        )
        self.name_filter = name_filter.lower()
        self.lock = threading.Lock()
        self.cleared_at: int = 0  # lines before this index are hidden after /c
        self._total_read = 0
        self._dirty = True

    @property
    def min_level(self) -> str:
        return LEVEL_ORDER[self.min_level_idx]

    def cycle_level(self) -> None:
        cur = self.min_level
        if cur in LEVEL_CYCLE:
            nxt = LEVEL_CYCLE[(LEVEL_CYCLE.index(cur) + 1) % len(LEVEL_CYCLE)]
        else:
            nxt = "DEBUG"
        self.min_level_idx = LEVEL_ORDER.index(nxt)
        self._dirty = True

    def toggle_debug(self) -> None:
        if self.min_level_idx == 0:
            self.min_level_idx = 1  # hide DEBUG
        else:
            self.min_level_idx = 0  # show DEBUG
        self._dirty = True

    def clear_display(self) -> None:
        with self.lock:
            self.lines.clear()
            self._dirty = True

    def accept(self, entry: dict) -> bool:
        lvl = entry.get("lvl", "INFO")
        if lvl not in LEVEL_ORDER:
            return True
        if LEVEL_ORDER.index(lvl) < self.min_level_idx:
            return False
        if self.name_filter:
            name = entry.get("name", "").lower()
            if self.name_filter not in name:
                return False
        return True

    def push(self, entry: dict) -> None:
        if self.accept(entry):
            with self.lock:
                self.lines.append(entry)
                self._dirty = True


# ──────────────────────────────────────────────────────────────────────────────
# FILE TAILER THREAD
# ──────────────────────────────────────────────────────────────────────────────


def _tail_thread(log_file: str, state: LogState, stop: threading.Event) -> None:
    """Reads new lines from log_file as they are appended."""
    path = Path(log_file)
    pos = 0

    while not stop.is_set():
        # Wait for file to exist
        if not path.exists():
            time.sleep(POLL_INTERVAL)
            continue

        try:
            size = path.stat().st_size
            if size < pos:
                # File was rotated/truncated
                pos = 0
                state.clear_display()

            if size > pos:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos)
                    new_data = fh.read()
                    pos = fh.tell()

                for raw_line in new_data.splitlines():
                    entry = _parse_line(raw_line)
                    if entry:
                        state.push(entry)
        except OSError:
            pass

        time.sleep(POLL_INTERVAL)


# ──────────────────────────────────────────────────────────────────────────────
# RENDER
# ──────────────────────────────────────────────────────────────────────────────


def _render(state: LogState, log_file: str) -> Panel:
    """Build the Rich Panel from current log lines."""
    with state.lock:
        lines = list(state.lines)

    table = Table(
        show_header=False,
        box=None,
        padding=(0, 1, 0, 0),
        expand=True,
    )
    table.add_column("time", style=TIME_STYLE, no_wrap=True, width=8)
    table.add_column("level", no_wrap=True, width=8)
    table.add_column("name", style=NAME_STYLE, no_wrap=True, width=20)
    table.add_column("msg", no_wrap=False)

    for entry in lines:
        lvl = entry.get("lvl", "INFO")
        time_str = entry.get("t", "")[-8:] or "?"  # HH:MM:SS
        name = _shorten_name(entry.get("name", "?"))
        msg = entry.get("msg", "")

        lvl_text = Text(f"[{lvl[:4]}]", style=LEVEL_STYLE.get(lvl, "white"))
        msg_text = Text(msg, style=MSG_STYLE.get(lvl, "white"), overflow="fold")

        table.add_row(time_str, lvl_text, name, msg_text)

    filter_str = f"  filter={state.name_filter}" if state.name_filter else ""
    title = (
        f"[bold cyan]SARAS Live Logs[/bold cyan]  "
        f"[dim]{log_file}[/dim]  "
        f"[yellow]level≥{state.min_level}[/yellow]"
        f"[dim]{filter_str}[/dim]  "
        f"[dim]{len(lines)} lines[/dim]"
    )
    subtitle = "[dim]q=quit  c=clear  d=toggle debug  f=cycle level[/dim]"

    return Panel(
        table,
        title=title,
        subtitle=subtitle,
        border_style="bright_black",
        box=box.ROUNDED,
    )


# ──────────────────────────────────────────────────────────────────────────────
# KEYBOARD INPUT THREAD
# ──────────────────────────────────────────────────────────────────────────────


def _keyboard_thread(state: LogState, stop: threading.Event) -> None:
    """Non-blocking single-char keyboard input (Unix only)."""
    try:
        import tty, termios

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        try:
            while not stop.is_set():
                # Use select for non-blocking check
                import select

                r, _, _ = select.select([sys.stdin], [], [], 0.2)
                if r:
                    ch = sys.stdin.read(1).lower()
                    if ch in ("q", "\x03", "\x04"):  # q, Ctrl+C, Ctrl+D
                        stop.set()
                    elif ch == "c":
                        state.clear_display()
                    elif ch == "d":
                        state.toggle_debug()
                    elif ch == "f":
                        state.cycle_level()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        # Fallback: just wait for stop
        stop.wait()


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]

    # Parse --file
    log_file = DEFAULT_LOG_FILE
    if "--file" in args:
        idx = args.index("--file")
        if idx + 1 < len(args):
            log_file = args[idx + 1]

    # Parse --level
    min_level = "DEBUG"
    if "--level" in args:
        idx = args.index("--level")
        if idx + 1 < len(args):
            min_level = args[idx + 1].upper()

    # Parse --filter
    name_filter = ""
    if "--filter" in args:
        idx = args.index("--filter")
        if idx + 1 < len(args):
            name_filter = args[idx + 1]

    # Parse --tail
    tail = DEFAULT_TAIL
    if "--tail" in args:
        idx = args.index("--tail")
        if idx + 1 < len(args):
            try:
                tail = int(args[idx + 1])
            except ValueError:
                pass

    state = LogState(tail=tail, min_level=min_level, name_filter=name_filter)
    stop = threading.Event()
    console = Console()

    # Announce where we are watching
    console.print(
        f"\n[bold cyan]SARAS Log Panel[/bold cyan]  watching [dim]{log_file}[/dim]\n"
        f"[dim]Waiting for log entries...  (q to quit)[/dim]\n"
    )

    # Start background threads
    tailer = threading.Thread(
        target=_tail_thread, args=(log_file, state, stop), daemon=True
    )
    tailer.start()

    kbd = threading.Thread(target=_keyboard_thread, args=(state, stop), daemon=True)
    kbd.start()

    # Live render loop
    try:
        with Live(
            _render(state, log_file),
            console=console,
            refresh_per_second=4,
            screen=True,
        ) as live:
            while not stop.is_set():
                live.update(_render(state, log_file))
                time.sleep(0.25)
    except KeyboardInterrupt:
        stop.set()

    console.print("[dim]Log panel closed.[/dim]")


if __name__ == "__main__":
    main()
