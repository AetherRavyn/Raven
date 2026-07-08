"""Terminal Dashboard — Hermes-style TUI with stunning visuals.

Provides a ``render_dashboard()`` function that prints a refreshed
system overview and a ``dashboard_loop()`` that runs it continuously.

Design inspired by JARVIS/Friday HUD displays from Iron Man.
"""

from __future__ import annotations

import os
import select
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any

from app.cli.cli_ui import (
    _term_width,
    blank,
    bold,
    cyan,
    dim,
    divider,
    green,
    info,
    magenta,
    red,
    yellow,
)


# ── Global state ─────────────────────────────────────────────────

_registry_cache: Any = None
_need_resize: bool = False
_start_time = time.monotonic()


def _on_sigwinch(signum: int, frame: Any) -> None:
    global _need_resize
    _need_resize = True


def _check_key(timeout: float = 0.1) -> str | None:
    """Read a single keypress without blocking (Unix)."""
    if not sys.stdin.isatty():
        return None
    r, _, _ = select.select([sys.stdin], [], [], timeout)
    if r:
        return sys.stdin.read(1)
    return None


# ── Visual primitives ────────────────────────────────────────────


def _gradient_bar(value: float, width: int = 30) -> str:
    """Render a gradient progress bar from green to yellow to red."""
    filled = int(value * width)
    empty = width - filled

    if value < 0.5:
        bar_color = green
    elif value < 0.75:
        bar_color = yellow
    else:
        bar_color = red

    filled_char = "█"
    empty_char = "░"
    return bar_color(filled_char * filled) + dim(empty_char * empty)


def _sparkline(values: list[float], width: int = 20) -> str:
    """Render a sparkline from values."""
    if not values:
        return dim("─" * width)
    blocks = " ▁▂▃▄▅▆▇█"
    mn, mx = min(values), max(values)
    rng = mx - mn if mx != mn else 1
    # Truncate or pad to width
    vals = values[-width:]
    return "".join(blocks[min(int((v - mn) / rng * 8), 8)] for v in vals)


def _status_dot(ok: bool) -> str:
    """Colored status dot."""
    return green("●") if ok else red("○")


def _section_header(title: str, width: int) -> str:
    """Render a section header with decorative line."""
    pad = width - len(title) - 6
    if pad < 0:
        pad = 0
    return f"  {cyan('◆')} {bold(title)} {cyan('─' * pad)}"


def _render_logo_hud(width: int) -> str:
    """Render the RAVEN ASCII logo."""
    lines = [
        "",
        f"  {cyan('░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░')}",
        f"  {cyan('░')}                                                              {cyan('░')}",
        f"  {cyan('░')}  {bold(cyan('██████╗  █████╗ ██╗   ██╗███████╗███╗   ██╗'))}                 {cyan('░')}",
        f"  {cyan('░')}  {bold(cyan('██╔══██╗██╔══██╗██║   ██║██╔════╝████╗  ██║'))}                 {cyan('░')}",
        f"  {cyan('░')}  {bold(cyan('██████╔╝███████║██║   ██║█████╗  ██╔██╗ ██║'))}                 {cyan('░')}",
        f"  {cyan('░')}  {bold(cyan('██╔══██╗██╔══██║╚██╗ ██╔╝██╔══╝  ██║╚██╗██║'))}                 {cyan('░')}",
        f"  {cyan('░')}  {bold(cyan('██║  ██║██║  ██║ ╚████╔╝ ███████╗██║ ╚████║'))}                 {cyan('░')}",
        f"  {cyan('░')}  {bold(cyan('╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝╚═╝  ╚═══╝'))}                 {cyan('░')}",
        f"  {cyan('░')}                                                              {cyan('░')}",
        f"  {cyan('░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░')}",
        "",
        f"  {dim('                  Autonomous Reconnaissance System')}",
        "",
    ]
    return "\n".join(lines)


# ── Metrics helpers ──────────────────────────────────────────────

_cpu_history: list[float] = []
_mem_history: list[float] = []


def _get_cpu_usage() -> float:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.1)
    except Exception:
        return _read_proc_stat()


def _read_proc_stat() -> float:
    """Fallback CPU reading via /proc/stat."""
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        if len(parts) < 5:
            return 0.0
        total = sum(int(v) for v in parts[1:])
        idle = int(parts[4]) if len(parts) > 4 else 0
        return max(0.0, min(100.0, (1 - idle / max(total, 1)) * 100))
    except Exception:
        return 0.0


def _get_memory_usage() -> tuple[float, float, float]:
    """Returns (percent, used_gb, total_gb)."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return vm.percent, vm.used / (1024**3), vm.total / (1024**3)
    except Exception:
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            mem_total = 0
            mem_avail = 0
            for line in lines:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1])
            if mem_total:
                pct = (1 - mem_avail / mem_total) * 100
                return pct, (mem_total - mem_avail) / (1024**2), mem_total / (1024**2)
        except Exception:
            pass
        return 0.0, 0.0, 0.0


def _get_disk_usage() -> tuple[float, float, float]:
    """Returns (percent, used_gb, total_gb)."""
    try:
        import psutil
        du = psutil.disk_usage("/")
        return du.percent, du.used / (1024**3), du.total / (1024**3)
    except Exception:
        try:
            st = os.statvfs("/")
            total = st.f_blocks * st.f_frsize
            free = st.f_bfree * st.f_frsize
            used = total - free
            if total:
                return (used / total) * 100, used / (1024**3), total / (1024**3)
        except Exception:
            pass
        return 0.0, 0.0, 0.0


def _get_uptime_hours() -> float:
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0]) / 3600
    except Exception:
        return 0.0


def _get_load_average() -> tuple[float, float, float]:
    """Returns (1min, 5min, 15min) load averages."""
    try:
        la = os.getloadavg()
        return la[0], la[1], la[2]
    except Exception:
        return 0.0, 0.0, 0.0


def _get_network_io() -> tuple[int, int]:
    """Returns (bytes_sent, bytes_recv)."""
    try:
        import psutil
        net = psutil.net_io_counters()
        return net.bytes_sent, net.bytes_recv
    except Exception:
        return 0, 0


def _get_process_count() -> int:
    """Get number of running processes."""
    try:
        import psutil
        return len(psutil.pids())
    except Exception:
        try:
            return len(os.listdir("/proc"))
        except Exception:
            return 0


def _get_agent_statuses() -> dict[str, bool]:
    """Check which core agents are available (cached)."""
    global _registry_cache
    statuses: dict[str, bool] = {}
    try:
        if _registry_cache is None:
            from app.core.supervisor import AgentRegistry
            _registry_cache = AgentRegistry()
            _registry_cache.register_all()
        for cap in getattr(_registry_cache, "_capabilities", {}).values():
            statuses[cap.agent_id] = True
    except Exception:
        pass
    if not statuses:
        statuses = {"orchestrator": True}
    return statuses


def _get_pending_approvals() -> int:
    try:
        from app.core.task_ledger import TaskLedger
        ledger = TaskLedger()
        return sum(1 for t in ledger.list_tasks() if t.get("status") == "pending_approval")
    except Exception:
        return 0


def _get_tool_count() -> int:
    try:
        from app.core.runtime import AgentRuntime
        rt = AgentRuntime(workspace_dir="workspace")
        return len(rt.tools)
    except Exception:
        return 0


def _get_recent_events(count: int = 6) -> list[dict[str, Any]]:
    """Fetch recent audit events."""
    events: list[dict[str, Any]] = []
    try:
        from app.core.audit import AuditLog
        log = AuditLog()
        if hasattr(log, "query"):
            all_events = log.query(limit=count)
        elif hasattr(log, "recent"):
            all_events = log.recent(limit=count)
        else:
            all_events = []
        for e in all_events:
            if isinstance(e, dict):
                events.append(e)
            else:
                events.append({
                    "kind": getattr(e, "kind", "?"),
                    "action": getattr(e, "action", "?"),
                    "timestamp": getattr(e, "timestamp", ""),
                    "detail": str(getattr(e, "detail", "") or ""),
                })
    except Exception:
        pass
    return events


def _format_bytes(n: int) -> str:
    """Format bytes to human readable."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def _format_uptime(hours: float) -> str:
    """Format hours to human readable uptime."""
    if hours < 1:
        return f"{int(hours * 60)}m"
    elif hours < 24:
        return f"{hours:.1f}h"
    else:
        days = int(hours // 24)
        h = hours % 24
        return f"{days}d {h:.0f}h"


# ── Render functions ─────────────────────────────────────────────


def render_dashboard(refresh_count: int = 0) -> None:
    """Render a full terminal dashboard with Hermes-style visuals."""
    global _cpu_history, _mem_history

    width = _term_width()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    uptime = _get_uptime_hours()

    # Clear screen
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

    # ── Logo & Header ───────────────────────────────────────────
    print(_render_logo_hud(width))

    # Status bar
    status_parts = [
        f"{green('●')} ONLINE",
        f"  {dim('│')}  {dim('Uptime:')} {bold(_format_uptime(uptime))}",
        f"  {dim('│')}  {dim('Time:')} {ts}",
    ]
    if refresh_count:
        status_parts.append(f"  {dim('│')}  {dim('Refresh:')} #{refresh_count}")
    print(f"  {''.join(status_parts)}")
    print()

    # ── Metrics Row (CPU | Memory | Disk | Load) ────────────────
    cpu = _get_cpu_usage()
    mem_pct, mem_used, mem_total = _get_memory_usage()
    disk_pct, disk_used, disk_total = _get_disk_usage()
    la1, la5, la15 = _get_load_average()

    # Update history
    _cpu_history.append(cpu)
    _mem_history.append(mem_pct)
    if len(_cpu_history) > 30:
        _cpu_history = _cpu_history[-30:]
    if len(_mem_history) > 30:
        _mem_history = _mem_history[-30:]

    # System Health Panel
    print(_section_header("SYSTEM HEALTH", width))
    print()

    # CPU
    cpu_style = green if cpu < 60 else yellow if cpu < 80 else red
    print(f"    {bold('CPU')}    {_gradient_bar(cpu / 100, 30)}  {cpu_style(f'{cpu:5.1f}%')}  {_sparkline(_cpu_history, 15)}")
    print()

    # Memory
    mem_style = green if mem_pct < 60 else yellow if mem_pct < 80 else red
    print(f"    {bold('MEMORY')} {_gradient_bar(mem_pct / 100, 30)}  {mem_style(f'{mem_pct:5.1f}%')}  {dim(f'{mem_used:.1f}/{mem_total:.1f} GB')}")
    print()

    # Disk
    disk_style = green if disk_pct < 70 else yellow if disk_pct < 90 else red
    print(f"    {bold('DISK')}   {_gradient_bar(disk_pct / 100, 30)}  {disk_style(f'{disk_pct:5.1f}%')}  {dim(f'{disk_used:.1f}/{disk_total:.1f} GB')}")
    print()

    # Load & Processes
    la1_style = green if la1 < 2.0 else yellow if la1 < 4.0 else red
    procs = _get_process_count()
    print(f"    {bold('LOAD')}    {la1_style(f'{la1:.2f}')} {dim(f'{la5:.2f}')} {dim(f'{la15:.2f}')}   {bold('Processes:')} {procs}")
    print()

    # Network
    net_sent, net_recv = _get_network_io()
    print(f"    {bold('NETWORK')} {dim('↑')} {_format_bytes(net_sent)}  {dim('↓')} {_format_bytes(net_recv)}")
    print()

    # ── Agents Panel ────────────────────────────────────────────
    print(_section_header("AGENTS", width))
    print()

    agent_statuses = _get_agent_statuses()
    agent_cols = min(4, max(1, width // 22))
    agents_list = list(agent_statuses.items())

    for i in range(0, len(agents_list), agent_cols):
        chunk = agents_list[i: i + agent_cols]
        row_parts = []
        for name, ok in chunk:
            dot = _status_dot(ok)
            label = name.replace("_", " ").title()
            row_parts.append(f"  {dot} {label}")
        # Pad to fill column width
        while len(row_parts) < agent_cols:
            row_parts.append("")
        print(f"    {''.join(f'{p:22s}' for p in row_parts)}")

    print()

    # ── Tools & Approvals ───────────────────────────────────────
    tools = _get_tool_count()
    pending = _get_pending_approvals()

    print(_section_header("CAPABILITIES", width))
    print()

    cap_items = [
        f"  {bold('Tools Registered:')}  {tools}",
        f"  {bold('Pending Approvals:')} {yellow(str(pending)) if pending else green('0')}",
    ]

    # Check services
    services = [
        ("Web Dashboard", os.path.exists("workspace/memory/kanban.db")),
        ("Blueprints", os.path.exists("workspace/memory/blueprints.db")),
        ("Event Hooks", os.path.exists("workspace/memory/hooks.db")),
        ("Themes", os.path.exists("workspace/memory/themes.db")),
    ]
    svc_ok = sum(1 for _, ok in services if ok)
    svc_total = len(services)
    cap_items.append(f"  {bold('Services:')}        {green(f'{svc_ok}/{svc_total} active')}")

    for line in cap_items:
        print(f"    {line}")

    print()

    # ── Recent Events ───────────────────────────────────────────
    events = _get_recent_events()
    if events:
        print(_section_header("RECENT ACTIVITY", width))
        print()

        # Table header
        print(f"    {dim('TIME')}              {dim('TYPE')}        {dim('ACTION')}")
        print(f"    {dim('─' * 18)}  {dim('─' * 12)}  {dim('─' * 24)}")

        for e in events[:5]:
            ts_str = str(e.get("timestamp", ""))[:19]
            kind = str(e.get("kind", "?"))[:12]
            action = str(e.get("action", "?"))[:24]
            # Color code by kind
            kind_color = cyan if "tool" in kind.lower() else (
                green if "success" in kind.lower() else (
                    yellow if "warn" in kind.lower() else dim
                )
            )
            print(f"    {dim(ts_str)}  {kind_color(kind):12s}  {action}")

        print()
    else:
        print(_section_header("RECENT ACTIVITY", width))
        print()
        print(f"    {dim('No recent events')}")
        print()

    # ── Footer ──────────────────────────────────────────────────
    divider()
    print(f"  {dim('Press ')}{bold('q')}{dim(' to exit  │  ')}{bold('r')}{dim(' to refresh  │  ')}{bold('?')}{dim(' for help')}")


def _show_dashboard_help() -> None:
    """Print an overlay help box."""
    from app.cli.cli_ui import box_str

    print(box_str(
        f"  {bold('q')}  — quit dashboard",
        f"  {bold('r')}  — refresh immediately",
        f"  {bold('?')}  — this help",
        title="Dashboard Help",
        style="info",
    ))


def dashboard_loop(*, interval: float = 5.0, no_color: bool = False) -> None:
    """Run the dashboard in a continuous refresh loop.

    Parameters
    ----------
    interval : float
        Refresh interval in seconds.
    no_color : bool
        If True, disable ANSI colour in the dashboard.
    """
    global _registry_cache, _need_resize

    if no_color:
        from app.cli.cli_ui import set_color_enabled as _set_color
        _set_color(False)

    _registry_cache = None

    signal.signal(signal.SIGWINCH, _on_sigwinch)

    import termios
    import tty

    old_settings: Any = None
    if sys.stdin.isatty():
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

    try:
        count = 0
        while True:
            render_dashboard(count)
            count += 1

            step = 0.1
            steps = max(1, int(interval / step))
            for _ in range(steps):
                if _need_resize:
                    _need_resize = False
                    break
                key = _check_key(step)
                if key:
                    key = key.lower()
                    if key == "q":
                        print()
                        print(f"  {green('●')} Dashboard closed.")
                        return
                    elif key == "r":
                        break
                    elif key == "?":
                        _show_dashboard_help()
                        break
    except KeyboardInterrupt:
        print()
        print(f"  {green('●')} Dashboard closed.")
    finally:
        if old_settings is not None and sys.stdin.isatty():
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
