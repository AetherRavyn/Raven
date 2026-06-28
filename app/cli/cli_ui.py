"""CLI UI — Rich terminal rendering for a Hermes-like experience.

Provides colored output, spinners, tables, and consistent formatting
for all RAVEN CLI commands.
"""

from __future__ import annotations

import shutil
import sys
import time
from contextlib import contextmanager
from typing import Any, Generator


def _term_width() -> int:
    return shutil.get_terminal_size((80, 20)).columns


def _colorize(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    return _colorize(text, "1")


def dim(text: str) -> str:
    return _colorize(text, "2")


def green(text: str) -> str:
    return _colorize(text, "32")


def red(text: str) -> str:
    return _colorize(text, "31")


def yellow(text: str) -> str:
    return _colorize(text, "33")


def cyan(text: str) -> str:
    return _colorize(text, "36")


def magenta(text: str) -> str:
    return _colorize(text, "35")


def blue(text: str) -> str:
    return _colorize(text, "34")


def white(text: str) -> str:
    return _colorize(text, "37")


# ── decorators ───────────────────────────────────────────────────────


def header(title: str, char: str = "─") -> None:
    width = _term_width()
    side = (width - len(title) - 2) // 2
    print(f"\n{char * side} {bold(title)} {char * side}")


def success(text: str) -> None:
    print(f"  {green('✓')} {text}")


def error(text: str) -> None:
    print(f"  {red('✗')} {text}", file=sys.stderr)


def warning(text: str) -> None:
    print(f"  {yellow('⚠')} {text}")


def info(text: str) -> None:
    print(f"  {cyan('ℹ')} {text}")


def item(key: str, value: str, sep: str = ":") -> None:
    print(f"  {bold(key)}{sep} {value}")


def divider(char: str = "─") -> None:
    print(f"  {dim(char * (_term_width() - 4))}")


def blank() -> None:
    print()


def status_dot(ok: bool, label: str = "") -> None:
    dot = green("●") if ok else red("○")
    if label:
        print(f"  {dot} {label}")
    else:
        print(f"  {dot}")


def table(headers: list[str], rows: list[list[str]], max_width: int | None = None) -> None:
    if not rows:
        print("  (empty)")
        return
    available = max_width or (_term_width() - 4)
    ncols = len(headers)
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    total = sum(widths) + 3 * (ncols - 1)
    if total > available and ncols > 1:
        overflow = total - available
        widths[-1] = max(10, widths[-1] - overflow)
    fmt = "  " + "   ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*[bold(h) for h in headers]))
    print(fmt.format(*[dim("─" * w) for w in widths]))
    for row in rows:
        truncated = [str(c)[:w] for c, w in zip(row, widths)]
        print(fmt.format(*truncated))


# ── spinner ──────────────────────────────────────────────────────────


@contextmanager
def spinner(text: str = "Working") -> Generator[None, Any, None]:
    """Show an animated spinner while work is happening."""
    if not sys.stdout.isatty():
        print(f"  {text}...")
        yield
        print(f"  {green('✓')} {text}")
        return

    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    done = False

    def _spin() -> None:
        i = 0
        while not done:
            sys.stdout.write(f"\r  {cyan(frames[i % len(frames)])} {text}...")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1
        sys.stdout.write(f"\r  {green('✓')} {text}   \n")
        sys.stdout.flush()

    import threading

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    try:
        yield
    finally:
        done = True
        t.join(0.5)


# ── logo ─────────────────────────────────────────────────────────────


RAVEN_LOGO = f"""
  {bold("╔══════════════════════════════════════════╗")}
  {bold("║")}                                          {bold("║")}
  {bold("║")}   ██████╗  █████╗ ██████╗ ████████╗      {bold("║")}
  {bold("║")}   ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝      {bold("║")}
  {bold("║")}   {cyan("██████╔╝███████║██║  ██║   ██║")}          {bold("║")}
  {bold("║")}   ██╔══██╗██╔══██║██║  ██║   ██║          {bold("║")}
  {bold("║")}   ██║  ██║██║  ██║██████╔╝   ██║          {bold("║")}
  {bold("║")}   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝    ╚═╝          {bold("║")}
  {bold("║")}                                          {bold("║")}
  {bold("║")}   {dim("Your JARVIS-class AI Agent")}           {bold("║")}
  {bold("╚══════════════════════════════════════════╝")}
"""

WELCOME = f"""
{RAVEN_LOGO}
  {dim("━" * (_term_width() - 4))}
  {bold("RAVEN")} is running. {green("●")} All systems operational.

  {bold("Web Dashboard")}  → {cyan("http://localhost:8090")}
  {bold("API")}            → {cyan("http://localhost:8090/v1/chat/completions")}
  {bold("Chat Modes")}     → {yellow("raven chat")}  |  {yellow("/chat")} on any platform

  {bold("Commands")}
    • {yellow("raven status")}     — system health and pending approvals
    • {bold("/help")}              — full command list in conversation
    • {yellow("raven log")}        — view recent logs
    • {yellow("raven stop")}       — shut down the daemon
  {dim("━" * (_term_width() - 4))}
"""
