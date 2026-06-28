# AGENTS.md — Raven Workspace Instructions

> This file is injected into every conversation as workspace-level context.
> Edit it to set project-specific rules, coding standards, and preferences.

---

## Repository: Raven

This is the source code for Raven, a JARVIS-class personal AI agent.

## Architecture Rules

1. **Python 3.12+** — All new code must use modern Python (type hints, dataclasses, async/await)
2. **Async-first** — All I/O operations must be async. Use `asyncio`, not threads, for concurrency
3. **Module organization** — New features go in `app/<domain>/`. Tools go in `app/tools/`
4. **Agent registration** — New agents go in `app/agents/` and must extend `BaseAgent`
5. **Skill manifests** — All skills must have `SKILL.md` + `module.yaml` in their directory
6. **Error handling** — Use the resilience layer (`app/tools/resilience.py`) for external API calls
7. **Logging** — Use `logging.getLogger(__name__)`, never `print()`
8. **Tests** — Every new module needs a corresponding `test_*.py`

## Code Style

- **Formatter**: `ruff format`
- **Linter**: `ruff check`
- **Type checker**: `pyright`
- **Max line length**: 100 characters
- **Import order**: stdlib → third-party → local (ruff handles this)

## Commit Convention

```
<type>(<scope>): <description>

Types: feat, fix, refactor, docs, test, chore, perf
Scope: core, tools, agents, voice, channels, skills, cli, gateway
```

## Environment

- Development machine: Linux
- Python: 3.12
- Package manager: uv
- Virtual environment: `.venv/`

## Key Files

- `main.py` — Application entry point
- `app/core/orchestrator.py` — Central message processing
- `app/core/runtime.py` — Full execution runtime (System 2)
- `app/core/agency.py` — Agent swarm manager
- `app/core/skill_registry.py` — Skill discovery and management
- `app/core/learning_db.py` — Unified SQLite + FTS5 store for all learning signals
- `app/core/rlhf.py` — RLHF preference store, router, and crystallizer
- `app/core/self_improvement.py` — Correction verifier and self-improvement loop
- `app/core/supervisor.py` — Keyword-based agent supervisor (14 agents)
- `app/core/task_scheduler.py` — Turn-based periodic task runner
- `app/tools/calendar.py` — Unified Google + Outlook/CalDAV calendar tool
- `app/voice/voice_bridge.py` — Cross-channel real-time voice session manager
- `SOUL.md` — Agent identity definition
- `MEMORY.md` — Persistent user knowledge
- `Skills.md` — Skills system documentation
- `Agent.md` — Agent architecture documentation
