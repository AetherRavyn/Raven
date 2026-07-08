"""CLI UI — Hermes-class terminal rendering.

Theme system matching the Hermes web dashboard, boxes, panels,
progress bars, spinners, and consistent formatting for all RAVEN
CLI commands.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator

import re as _re


# ── Terminal Theme (mirrors Hermes dashboard CSS variables) ──────


@dataclass
class TermTheme:
    """ANSI-based colour palette for terminal rendering."""

    name: str
    bg_primary: str
    bg_secondary: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_dim: str
    danger: str
    warning: str
    info: str
    success: str
    border: str
    # ANSI colour codes (foreground)
    fg_primary: str = "37"
    fg_secondary: str = "90"
    fg_muted: str = "2"
    fg_accent: str = "92"
    fg_danger: str = "91"
    fg_warning: str = "93"
    fg_info: str = "96"
    fg_success: str = "92"
    fg_border: str = "90"


DARK_THEME = TermTheme(
    name="dark",
    bg_primary="\033[40m",
    bg_secondary="\033[100m",
    text_primary="37",
    text_secondary="90",
    text_muted="2",
    accent="92",
    accent_dim="\033[2;92m",
    danger="91",
    warning="93",
    info="96",
    success="92",
    border="90",
)

LIGHT_THEME = TermTheme(
    name="light",
    bg_primary="\033[47m",
    bg_secondary="\033[107m",
    text_primary="30",
    text_secondary="90",
    text_muted="2",
    accent="32",
    accent_dim="\033[2;32m",
    danger="31",
    warning="33",
    info="34",
    success="32",
    border="90",
)


MIDNIGHT_THEME = TermTheme(
    name="midnight",
    bg_primary="\033[40m",
    bg_secondary="\033[100m",
    text_primary="36",
    text_secondary="90",
    text_muted="2",
    accent="94",
    accent_dim="\033[2;94m",
    danger="91",
    warning="93",
    info="94",
    success="92",
    border="90",
)


_THEMES: dict[str, TermTheme] = {
    "dark": DARK_THEME,
    "light": LIGHT_THEME,
    "midnight": MIDNIGHT_THEME,
}


def _detect_theme() -> TermTheme:
    theme_name = os.environ.get("RAVEN_THEME", "dark").lower()
    return _THEMES.get(theme_name, DARK_THEME)


_ACTIVE_THEME: TermTheme = _detect_theme()


# ── Color support detection ──────────────────────────────────────

_COLOR_ENABLED: bool = True


def supports_color() -> bool:
    """Check whether the terminal supports coloured output.

    Respects the ``NO_COLOR <https://no-color.org/>`` and
    ``FORCE_COLOR`` environment-variable conventions.
    """
    nc = os.environ.get("NO_COLOR")
    if nc is not None and nc != "":
        return False
    fc = os.environ.get("FORCE_COLOR")
    if fc is not None and fc != "":
        return True
    return sys.stdout.isatty()


def set_color_enabled(enabled: bool | None = None) -> None:
    """Override or re-detect colour support globally."""
    global _COLOR_ENABLED
    if enabled is not None:
        _COLOR_ENABLED = enabled
    else:
        _COLOR_ENABLED = supports_color()


set_color_enabled()


def _strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from *text*."""
    return _re.sub(r"\033\[[0-9;]*m", "", text)


# ── Terminal helpers ─────────────────────────────────────────────


def _term_width() -> int:
    return shutil.get_terminal_size((80, 20)).columns


def _colorize(text: str, code: str) -> str:
    if not _COLOR_ENABLED:
        return text
    return f"\033[{code}m{text}\033[0m"


def _256_color(text: str, fg: int, bg: int | None = None) -> str:
    fg = max(0, min(255, int(fg)))
    code = f"38;5;{fg}"
    if bg is not None:
        bg = max(0, min(255, int(bg)))
        code += f";48;5;{bg}"
    return _colorize(text, code)


def rgb(r: int, g: int, b: int, text: str) -> str:
    """Wrap *text* in a truecolour (24-bit) foreground ANSI sequence."""
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))
    return _colorize(text, f"38;2;{r};{g};{b}")


def link(url: str, text: str) -> str:
    """Return an OSC-8 terminal hyperlink."""
    if not _COLOR_ENABLED:
        return text
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


# ── Public colour helpers ────────────────────────────────────────


def bold(text: str) -> str:
    return _colorize(text, "1")


def dim(text: str) -> str:
    return _colorize(text, "2")


def italic(text: str) -> str:
    return _colorize(text, "3")


def underline(text: str) -> str:
    return _colorize(text, "4")


def green(text: str) -> str:
    return _colorize(text, _ACTIVE_THEME.fg_success)


def red(text: str) -> str:
    return _colorize(text, _ACTIVE_THEME.fg_danger)


def yellow(text: str) -> str:
    return _colorize(text, _ACTIVE_THEME.fg_warning)


def cyan(text: str) -> str:
    return _colorize(text, _ACTIVE_THEME.fg_info)


def magenta(text: str) -> str:
    return _colorize(text, "35")


def blue(text: str) -> str:
    return _colorize(text, _ACTIVE_THEME.fg_accent)


def white(text: str) -> str:
    return _colorize(text, "37")


def styled(text: str, style: str) -> str:
    """Apply a named style: bold, dim, green, red, yellow, cyan, etc."""
    style_map: dict[str, str] = {
        "bold": "1",
        "dim": "2",
        "italic": "3",
        "underline": "4",
        "green": _ACTIVE_THEME.fg_success,
        "red": _ACTIVE_THEME.fg_danger,
        "yellow": _ACTIVE_THEME.fg_warning,
        "cyan": _ACTIVE_THEME.fg_info,
        "blue": _ACTIVE_THEME.fg_accent,
        "magenta": "35",
        "white": "37",
        "muted": _ACTIVE_THEME.fg_muted,
    }
    code = style_map.get(style.lower(), "0")
    return _colorize(text, code)


# ── Decorators ───────────────────────────────────────────────────


def header(title: str, char: str = "─", style: str = "bold") -> None:
    width = _term_width()
    side = max(2, (width - len(title) - 2) // 2)
    print(f"\n{char * side} {styled(title, style)} {char * side}")


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


# ── Status indicators ────────────────────────────────────────────


def status_dot(ok: bool, label: str = "") -> None:
    dot = green("●") if ok else red("○")
    if label:
        print(f"  {dot} {label}")
    else:
        print(f"  {dot}")


def badge(text: str, style: str = "info") -> str:
    """Render a small inline badge."""
    style_map = {
        "info": cyan,
        "success": green,
        "warning": yellow,
        "danger": red,
        "muted": dim,
    }
    fn = style_map.get(style, dim)
    return f" {fn(f'[{text}]')} "


def status_label(label: str, ok: bool) -> str:
    """Render a status label with coloured dot."""
    dot = green("●") if ok else red("○")
    text = dim(label) if ok else red(label)
    return f"{dot} {text}"


# ── Box / panel rendering ────────────────────────────────────────


def box(
    *lines: str,
    title: str | None = None,
    style: str = "default",
    width: int | None = None,
) -> None:
    """Draw a bordered box around content.

    Args:
        *lines: Content lines to put inside the box.
        title: Optional title displayed in the top border.
        style: 'default', 'success', 'warning', 'error', 'info'.
        width: Box width (auto from terminal if not given).
    """
    w = width or min(_term_width() - 2, 100)
    inner = w - 4

    border_chars = {
        "default": ("─", "│", "┌", "┐", "└", "┘"),
        "success": ("─", "│", "┌", "┐", "└", "┘"),
        "warning": ("─", "│", "┌", "┐", "└", "┘"),
        "error": ("─", "│", "┌", "┐", "└", "┘"),
        "info": ("─", "│", "┌", "┐", "└", "┘"),
    }
    h, v, tl, tr, bl, br = border_chars.get(style, border_chars["default"])

    style_fn = {
        "success": green,
        "warning": yellow,
        "error": red,
        "info": cyan,
        "default": dim,
    }.get(style, dim)

    top = f"  {style_fn(tl)}"
    if title:
        top += f"{style_fn(h)} {bold(title)} {style_fn(h * (inner - len(title) - 2))}"
    else:
        top += f"{style_fn(h * inner)}"
    top += f"{style_fn(tr)}"
    print(top)

    for line in lines:
        content = str(line)[:inner]
        print(f"  {style_fn(v)} {content:{inner}} {style_fn(v)}")

    bottom = f"  {style_fn(bl)}{style_fn(h * inner)}{style_fn(br)}"
    print(bottom)


def panel(title: str, content: list[str], style: str = "default") -> None:
    """Render a titled panel (box with header inside).

    Args:
        title: Panel title.
        content: Lines of content.
        style: 'default', 'success', 'warning', 'error', 'info'.
    """
    w = min(_term_width() - 2, 100)
    inner = w - 4

    border_c = {
        "default": dim,
        "success": green,
        "warning": yellow,
        "error": red,
        "info": cyan,
    }.get(style, dim)

    h_line = border_c("─")
    v_bar = border_c("│")

    print(
        f"  {border_c('┌')}{h_line} {bold(title)} {h_line * (inner - len(title) - 2)}{border_c('┐')}"
    )
    for line in content:
        print(f"  {v_bar} {str(line):{inner}} {v_bar}")
    print(f"  {border_c('└')}{h_line * inner}{border_c('┘')}")


# ── Table ────────────────────────────────────────────────────────


def table(headers: list[str], rows: list[list[str]], max_width: int | None = None) -> None:
    """Render a formatted table with headers."""
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


# ── Progress bar ─────────────────────────────────────────────────


def progress_bar(
    fraction: float,
    width: int = 40,
    label: str = "",
) -> str:
    """Render a progress bar string.

    Args:
        fraction: 0.0 to 1.0.
        width: Character width of the bar.
        label: Optional label suffix.

    Returns:
        Progress bar string like ``[████░░░░░] 50% training``.
    """
    filled = int(fraction * width)
    empty = width - filled
    bar = f"{'█' * filled}{'░' * empty}"
    pct = f"{int(fraction * 100):3d}%"
    if label:
        return f"  [{green(bar)}] {green(pct)} {dim(label)}"
    return f"  [{green(bar)}] {green(pct)}"


def progress_bar_inline(fraction: float, width: int = 20) -> str:
    """Render a compact inline progress bar."""
    filled = int(fraction * width)
    empty = width - filled
    bar = f"{'█' * filled}{'░' * empty}"
    pct = f"{int(fraction * 100):3d}%"
    return f"[{green(bar)}] {pct}"


# ── Key-value list ───────────────────────────────────────────────


def key_value(items: list[tuple[str, str]], indent: int = 2) -> None:
    """Print aligned key-value pairs."""
    if not items:
        return
    key_width = max(len(k) for k, _ in items) + 1
    prefix = " " * indent
    for key, value in items:
        padded_key = f"{key}:".ljust(key_width + 1)
        print(f"{prefix}{bold(padded_key)} {value}")


# ── Tree ─────────────────────────────────────────────────────────


def tree(items: list[tuple[str, list[str]]], indent: int = 2) -> None:
    """Print a tree of items with sub-items."""
    prefix = " " * indent
    for label, children in items:
        print(f"{prefix}{bold(label)}")
        for child in children:
            print(f"{prefix}  {dim('└─')} {child}")


# ── Spinner ──────────────────────────────────────────────────────


_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_SPINNER_DONE = ["●", "✓", "◆", "★"]


@contextmanager
def spinner(text: str = "Working", done_symbol: str = "✓") -> Generator[None, Any, None]:
    """Show an animated spinner while work is happening."""
    if not sys.stdout.isatty():
        print(f"  {text}...")
        yield
        print(f"  {green(done_symbol)} {text}")
        return

    done = False

    def _spin() -> None:
        i = 0
        while not done:
            sys.stdout.write(f"\r  {cyan(_SPINNER_FRAMES[i % len(_SPINNER_FRAMES)])} {text}...")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1
        done_char = green(done_symbol)
        sys.stdout.write(f"\r  {done_char} {text}   \n")
        sys.stdout.flush()

    import threading

    t = threading.Thread(target=_spin, daemon=True)
    t.start()
    try:
        yield
    finally:
        done = True
        t.join(0.5)


# ── Logo ─────────────────────────────────────────────────────────


_LOGO_LINES = [
    "██████╗  █████╗ ██████╗ ███████╗ ███╗   ██╗",
    "██╔══██╗██╔══██╗██╔══██╗██╔════╝ ████╗  ██║",
    "██████╔╝███████║██║  ██║█████╗   ██╔██╗ ██║",
    "██╔══██╗██╔══██║██║  ██║██╔══╝   ██║╚██╗██║",
    "██║  ██║██║  ██║██████╔╝███████╗ ██║ ╚████║",
    "╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝ ╚═╝  ╚═══╝",
]


def _render_logo(width: int) -> str:
    padding = max(0, (width - len(_LOGO_LINES[0])) // 2)
    pad_str = " " * padding
    lines: list[str] = []
    for i, line in enumerate(_LOGO_LINES):
        if i == 2:
            lines.append(f"{pad_str}{cyan(line)}")
        else:
            lines.append(f"{pad_str}{bold(line)}")
    return "\n".join(lines)


def logo(version: str = "") -> None:
    """Print the Raven logo."""
    width = _term_width()
    print()
    print(_render_logo(width))
    if version:
        print(f"{' ' * ((width - len(version)) // 2)}{dim(version)}")
    print()


RAVEN_LOGO = _render_logo(_term_width())


def box_str(
    *lines: str,
    title: str | None = None,
    style: str = "default",
    width: int | None = None,
) -> str:
    """Return a bordered box as a string (for use in f-strings)."""
    w = width or min(_term_width() - 2, 100)
    inner = w - 4

    border_chars = {
        "default": ("─", "│", "┌", "┐", "└", "┘"),
        "success": ("─", "│", "┌", "┐", "└", "┘"),
        "warning": ("─", "│", "┌", "┐", "└", "┘"),
        "error": ("─", "│", "┌", "┐", "└", "┘"),
        "info": ("─", "│", "┌", "┐", "└", "┘"),
    }
    h, v, tl, tr, bl, br = border_chars.get(style, border_chars["default"])

    style_fn = {
        "success": green,
        "warning": yellow,
        "error": red,
        "info": cyan,
        "default": dim,
    }.get(style, dim)

    result: list[str] = []
    top = f"  {style_fn(tl)}"
    if title:
        top += f"{style_fn(h)} {bold(title)} {style_fn(h * (inner - len(title) - 2))}"
    else:
        top += f"{style_fn(h * inner)}"
    top += f"{style_fn(tr)}"
    result.append(top)

    for line in lines:
        content = str(line)[:inner]
        result.append(f"  {style_fn(v)} {content:{inner}} {style_fn(v)}")

    bottom = f"  {style_fn(bl)}{style_fn(h * inner)}{style_fn(br)}"
    result.append(bottom)
    return "\n".join(result)


def panel_str(title: str, content: list[str], style: str = "default") -> str:
    """Return a titled panel as a string (for use in f-strings)."""
    w = min(_term_width() - 2, 100)
    inner = w - 4

    border_c = {
        "default": dim,
        "success": green,
        "warning": yellow,
        "error": red,
        "info": cyan,
    }.get(style, dim)

    h_line = border_c("─")

    result: list[str] = []
    # Top border with title
    title_text = f" {title} "
    pad = inner - len(title) - 2
    if pad < 0:
        pad = 0
    result.append(f"  {border_c('┌')}{h_line}{bold(title_text)}{h_line * pad}{border_c('┐')}")

    # Content lines
    for line in content:
        c = str(line)[:inner]
        result.append(f"  {border_c('│')} {c:{inner}} {border_c('│')}")

    # Bottom border
    result.append(f"  {border_c('└')}{h_line * inner}{border_c('┘')}")
    return "\n".join(result)


WELCOME = f"""
{RAVEN_LOGO}

{box_str(
    dim("RAVEN is running. All systems operational."),
    title="Status",
    style="success",
    width=min(_term_width() - 2, 100),
)}

{panel_str(
    "Endpoints",
    [
        f"  {bold('Web Dashboard')}  {cyan('http://localhost:8090')}",
        f"  {bold('API')}            {cyan('http://localhost:8090/v1/chat/completions')}",
    ],
    style="info",
)}

  {dim("Commands")}
  {badge("raven dashboard", "info")} Terminal system HUD
  {badge("raven status", "info")}   System health and approvals
  {badge("raven chat", "info")}     Interactive chat session
  {badge("raven log", "info")}      View recent logs
  {badge("raven stop", "info")}     Shut down daemon
  {badge("raven doctor", "info")}   Diagnostic checks
  {badge("raven help", "info")}     Full command list
{dim("━" * min(_term_width() - 2, 100))}
"""


# ── Dashboard helpers ────────────────────────────────────────────


def render_system_health(
    cpu: float = 0.0,
    memory: float = 0.0,
    disk: float = 0.0,
    uptime_hours: float = 0.0,
    agents_active: int = 0,
    tools_registered: int = 0,
    pending_approvals: int = 0,
) -> str:
    """Render a system health panel."""
    lines: list[str] = []
    lines.append(f"  {status_label('CPU', cpu < 80)} {progress_bar_inline(cpu / 100)}")
    lines.append(f"  {status_label('Memory', memory < 80)} {progress_bar_inline(memory / 100)}")
    lines.append(f"  {status_label('Disk', disk < 90)} {progress_bar_inline(disk / 100)}")
    lines.append(f"  {bold('Uptime')}: {uptime_hours:.1f}h")
    lines.append(
        f"  {bold('Agents')}: {agents_active} active  {bold('Tools')}: {tools_registered} registered"
    )
    if pending_approvals:
        lines.append(f"  {yellow('⚠')} {pending_approvals} pending approval(s)")
    return "\n".join(lines)


def render_metric_card(
    title: str,
    value: str,
    subtitle: str = "",
    style: str = "default",
) -> None:
    """Render a single metric card (compact box)."""
    w = min(_term_width() - 2, 100)
    inner = w - 4
    s_fn = {"success": green, "warning": yellow, "error": red, "info": cyan, "default": dim}.get(
        style, dim
    )
    print(f"  {s_fn('┌')}{s_fn('─' * inner)}{s_fn('┐')}")
    print(f"  {s_fn('│')} {bold(title):{inner}} {s_fn('│')}")
    val_style = {
        "success": green,
        "warning": yellow,
        "error": red,
        "info": cyan,
        "default": bold,
    }.get(style, bold)
    print(f"  {s_fn('│')} {val_style(value):{inner}} {s_fn('│')}")
    if subtitle:
        print(f"  {s_fn('│')} {dim(subtitle):{inner}} {s_fn('│')}")
    print(f"  {s_fn('└')}{s_fn('─' * inner)}{s_fn('┘')}")
