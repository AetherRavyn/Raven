---
title: "TUI Reference — Terminal Dashboard"
---

# TUI Reference — Terminal Dashboard

> **Document level**: Hermes  
> **Last updated**: 2026-06-30  
> **Module**: `app/cli/dashboard.py`, `app/cli/cli_ui.py`

---

## Overview

Raven's Terminal User Interface (TUI) provides a live system HUD that refreshes every 5 seconds. It mirrors the web dashboard in the terminal, giving real-time visibility into system health, agent status, services, and recent events — no browser required.

Launch with:

```bash
raven dashboard
```

Or from the daemon welcome screen:

```bash
raven run           # Then follow the "raven dashboard" hint
```

---

## Dashboard Screens

### System Health Panel

```
┌─────────────────────────────────────────────────────────┐
│ ┌── System Health ─────────────────────────────────────┐ │
│ │  ● CPU     [████████░░░░░░░░░░░░░░░░░░░░░░░░]  23%   │ │
│ │  ● Memory  [████████████████░░░░░░░░░░░░░░░░]  45%   │ │
│ │  ● Disk    [████████████████████████░░░░░░░░]  62%   │ │
│ │  Uptime: 72.5h                                        │ │
│ │  ✓ No pending approvals                               │ │
│ └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

| Metric | Color Threshold | Description |
|--------|----------------|-------------|
| CPU | Green < 80%, Yellow ≥ 80% | CPU usage percentage |
| Memory | Green < 80%, Yellow ≥ 80% | RAM usage percentage |
| Disk | Green < 90%, Yellow ≥ 90% | Disk usage percentage |
| Uptime | N/A | System uptime in hours |
| Approvals | Green = 0, Yellow > 0 | Pending approval count |

### Agents Panel

```
┌── Agents ──────────────────────────────────────────────┐
│  ● Orchestrator    ● Assistant        ● Communications  │
│  ● Developer       ● Finance          ● Home_guardian   │
│  ● Moral           ● Negotiation      ● News            │
│  ● Productivity    ● Researcher       ● Reviewer        │
│  ● Scientist       ● Security         ● Sysadmin        │
└────────────────────────────────────────────────────────┘
```

Each agent is shown with a status dot:

| Indicator | Meaning |
|-----------|---------|
| `●` (green) | Agent registered and available |
| `○` (red) | Agent not registered |

Agents are grouped in rows of 4 (auto-adjusts to terminal width).

### Services Panel

```
┌── Services ─────────────────────────────────────────────┐
│  ● Kanban Board       ● Blueprints        ● Event Hooks │
│  ● Themes             ○ Petdex            ● Petdex      │
│  ● Deliverables       ● Subscriptions     ● App Server  │
└────────────────────────────────────────────────────────┘
```

Services status reflects the existence of their backing database files in `workspace/memory/`.

| Indicator | Meaning |
|-----------|---------|
| `●` (green) | Service database exists |
| `○` (red) | Service not initialized |

### Recent Events Table

```
┌─────────────────────────────────────────────────────────┐
│  Timestamp           Kind         Action                 │
│  ─────────────────────────────────────────────────────── │
│  2026-06-30 12:00    message      send                   │
│  2026-06-30 11:59    tool         web_search.execute     │
│  2026-06-30 11:58    learning     consolidate            │
│  2026-06-30 11:55    system       health_check           │
└─────────────────────────────────────────────────────────┘
```

Shows the 5 most recent audit events. Columns auto-truncate to fit terminal width.

---

## Keybindings

The dashboard currently runs in a read-only refresh loop. Keybindings are planned for v1.1:

| Key | Action | Status |
|-----|--------|--------|
| `q` or `Ctrl+C` | Exit dashboard | ✅ Implemented |
| `r` | Force refresh | ⏳ Planned |
| `1`-`5` | Switch screen tab | ⏳ Planned |
| `↑`/`↓` | Scroll event log | ⏳ Planned |
| `Enter` | Select/expand item | ⏳ Planned |
| `t` | Theme cycle | ⏳ Planned |
| `?` | Show keybinding help | ⏳ Planned |

---

## Theme Switching

The TUI supports three built-in themes controlled by the `RAVEN_THEME` environment variable.

### Usage

```bash
# Dark theme (default)
RAVEN_THEME=dark raven dashboard

# Light theme
RAVEN_THEME=light raven dashboard

# Midnight blue theme
RAVEN_THEME=midnight raven dashboard
```

### Theme Comparison

| Aspect | Dark | Light | Midnight |
|--------|------|-------|----------|
| Background | Black | White | Black |
| Primary text | White (37) | Black (30) | Cyan (36) |
| Accent color | Green (92) | Green (32) | Blue (94) |
| Muted text | Dim (2) | Dim (2) | Dim (2) |
| Border style | Gray (90) | Gray (90) | Gray (90) |
| Error color | Red (91) | Red (31) | Red (91) |
| Warning color | Yellow (93) | Yellow (33) | Yellow (93) |
| Info color | Cyan (96) | Blue (34) | Blue (94) |

The theme system is defined in `app/cli/cli_ui.py:TermTheme` dataclass. Themes use ANSI escape codes exclusively (no 256-color or truecolor dependencies).

### Adding a Custom Theme

Create a new `TermTheme` instance and register it in `_THEMES` dict:

```python
SOLARIZED_THEME = TermTheme(
    name="solarized",
    bg_primary="\033[48;5;234m",
    text_primary="37",
    ...
)

_THEMES["solarized"] = SOLARIZED_THEME
```

---

## Terminal Requirements

### ANSI Support

| Feature | Required | Fallback |
|---------|----------|----------|
| ANSI escape codes (SGR) | Yes | Strip formatting, plain text only |
| Cursor positioning | Yes (spinner) | Log-style non-interactive output |
| Box-drawing Unicode | Yes | ASCII `-`, `|`, `+` characters |
| Braille spinner chars | Yes (optional) | "..." text |

### Unicode Requirements

The TUI uses these Unicode characters:

| Codepoint | Char | Usage |
|-----------|------|-------|
| U+25CF | `●` | Green status dot (online/ok) |
| U+25CB | `○` | Red status dot (offline/error) |
| U+2588 | `█` | Progress bar filled block |
| U+2591 | `░` | Progress bar empty block |
| U+2500-U+257F | `─│┌┐└┘` | Box-drawing panel borders |
| U+2800-U+28FF | `⠋⠙⠹...` | Spinner animation frames |

All terminals released after 2015 should render these correctly. If you see garbled characters, ensure your terminal:

- Uses a UTF-8 locale (`locale` should show `en_US.UTF-8` or similar)
- Has a font with Unicode support (Nerd Fonts, Fira Code, JetBrains Mono, etc.)
- Is configured for UTF-8 encoding

### Color Support

The TUI uses **16-color ANSI** exclusively (codes 30-37, 90-97, plus SGR modifiers `1` for bold, `2` for dim). This guarantees compatibility with:

- Linux virtual consoles (tty1-6)
- All modern terminal emulators (GNOME Terminal, Konsole, iTerm2, Windows Terminal)
- tmux and screen sessions
- SSH clients
- CI/CD log viewers

No 256-color or truecolor escape sequences are used.

### Minimum Terminal Size

| Dimension | Minimum | Recommended |
|-----------|---------|-------------|
| Width | 60 columns | 100+ columns |
| Height | 20 rows | 30+ rows |

Below 60 columns, table columns will overlap. Below 20 rows, the dashboard may not display all panels.

### Non-Interactive Fallback

When stdout is not a TTY (piped, redirected, or in CI), the TUI degrades gracefully:

- Spinner shows `Working...` without animation frames
- No ANSI color codes emitted
- No cursor positioning
- Plain text output suitable for logs

---

## Troubleshooting TUI Issues

### Dashboard shows garbled characters

**Cause**: Terminal not configured for UTF-8.

**Fix**:
```bash
# Check locale
locale

# Set UTF-8 locale
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# Verify on Debian/Ubuntu
sudo locale-gen en_US.UTF-8
```

### Dashboard is blank or flickering

**Cause**: Terminal too small or scrollback buffer issue.

**Fix**:
- Resize terminal to at least 80×24
- Run `reset` to clear terminal state
- Try a different terminal emulator

### Colors not displaying

**Cause**: Terminal does not support ANSI color, or `TERM` is set wrong.

**Fix**:
```bash
# Set proper terminal type
export TERM=xterm-256color

# Or for basic terminals
export TERM=linux
```

### Spinner not animating

**Cause**: stdout is piped or redirected.

**Behavior**: Falls back to `Working...` text without spinner frames. This is intentional — log output should not contain animation control characters.

### Dashboard won't start

```
ModuleNotFoundError: No module named 'psutil'
```

The dashboard attempts to use `psutil` for hardware telemetry. If unavailable, it falls back to reading `/proc/stat` and `/proc/meminfo` directly.

**Fix**:
```bash
uv pip install psutil
```

### Box-drawing characters appear as `q`, `x`, or `+`

**Cause**: Terminal font does not include box-drawing glyphs, or the terminal is in ASCII-only mode.

**Fix**:
- Install a font with Unicode box drawing (Nerd Fonts, Noto Mono, etc.)
- Check terminal settings for "Allow bold text" and "Use Unicode"
- On Windows Terminal, enable "Experimental rendering engine"

---

## How the TUI Differs from the Web Dashboard

| Aspect | TUI (raven dashboard) | Web Dashboard (localhost:8090) |
|--------|-----------------------|-------------------------------|
| **Access** | Terminal-only | Browser (HTTP) |
| **Refresh** | Poll-based (5s interval) | WebSocket push (live) |
| **Interactivity** | Read-only (for now) | Full CRUD (kanban, cron, channels, etc.) |
| **Scope** | System health, agents, services, events | Chat, sessions, memory, models, providers, profiles, blueprints, kanban, cron, MCP, plugins, skills, webhooks, audit, learning, personality, modules |
| **Visuals** | ANSI art panels, progress bars | Tailwind CSS, charts, data tables |
| **Data Source** | Live probes (psutil, /proc, registry queries) | FastAPI REST + WebSocket endpoints |
| **Auth** | None (local terminal) | Optional Bearer token |
| **Konami Code** | `raven dashboard` | Point browser to `http://localhost:8090` |
| **Offline** | Works fully offline | Requires running server |
| **Customization** | Theme via `RAVEN_THEME` env var | Config editor in-browser |
| **Portability** | SSH, serial console, tmux | Requires modern browser |
