"""Channel-truth audit — Phase 0.6.

Walks `app/*/` and asserts the following invariants so the project
doesn't claim features it has not actually shipped:

  1. Every channel connector directory under `app/` must either
     - contain real, non-stub Python code (an actual implementation), OR
     - have a `STATUS.md` next to it that honestly says "stub" / "planned"
     so CI / docs can never lie.
  2. `MEMORY.md` (if present) must not be empty.
  3. `skills/learned/` is allowed to be empty *initially*, but every time
     the audit runs in CI the `SkillLearner.observe()` call site in
     `app/core/orchestrator.py` must exist (string check). Otherwise we
     know the wiring has been removed and learned-skill claim is a lie.
  4. The plan claim "all tools ship" — the 60+ tools in `app/tools/`
     are checked for basic syntactic validity (each file parses as
     Python) so a half-typed file can't hide in there.

Exit code 0 = clean, 1 = at least one lie.

Run:
    python scripts/audit_channel_truths.py
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

# Allow tests / CI to override the project root via env var. Otherwise
# default to the parent of this script's parent.
_PROJECT_ROOT = Path(
    os.environ.get("RAVEN_PROJECT_ROOT")
    or Path(__file__).resolve().parents[1]
)
_APP_DIR = _PROJECT_ROOT / "app"
_TOOLS_DIR = _APP_DIR / "tools"
_ORCHESTRATOR = _APP_DIR / "core" / "orchestrator.py"
_AMBIENT_LOOP = _APP_DIR / "core" / "ambient_loop.py"
_MEMORY_MD = _PROJECT_ROOT / "MEMORY.md"

# Known channel connector directories. Each entry is a tuple
# (dir, expected_module, required_min_functions). The default
# required_min_functions is 2 (e.g. start + handle).
CHANNEL_DIRS: list[tuple[Path, str, int]] = [
    (_APP_DIR / "telegram", "app.telegram.bot", 3),
    (_APP_DIR / "discord", "app.discord.discordapp", 3),
    (_APP_DIR / "slack", "app.slack.slackapp", 3),
    (_APP_DIR / "whatsapp", "app.whatsapp.whatsappapp", 2),
    (_APP_DIR / "voice", "app.voice.pipeline", 3),
    (_APP_DIR / "web", "app.web.server", 2),
]


def _count_real_functions(py_file: Path) -> int:
    """Count non-dunder top-level defs and class methods in a .py file.

    A "real function" is anything not starting with `_`. This catches
    the common case where a connector is a single class with `start`
    / `handle` / etc. methods.
    """
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return -1
    count = 0
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            count += 1
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not child.name.startswith("_")
                ):
                    count += 1
    return count


def _has_status_marker(dir_path: Path) -> bool:
    """Return True if a STATUS.md exists and contains 'stub' or 'planned'."""
    marker = dir_path / "STATUS.md"
    if not marker.exists():
        return False
    text = marker.read_text(encoding="utf-8", errors="ignore").lower()
    return any(w in text for w in ("stub", "planned", "not implemented", "wip"))


def _check_channel_dirs() -> list[str]:
    """Return a list of human-readable problems; empty list == pass."""
    problems: list[str] = []
    for dir_path, expected_module, min_funcs in CHANNEL_DIRS:
        if not dir_path.exists():
            problems.append(
                f"[channel] {dir_path.name}/: directory missing — "
                f"remove from claims or implement."
            )
            continue
        py_files = [
            p
            for p in dir_path.rglob("*.py")
            if p.name != "__init__.py" and p.name != "__main__.py"
        ]
        if not py_files:
            # No python at all — must be a stub, claim must say so.
            if not _has_status_marker(dir_path):
                problems.append(
                    f"[channel] {dir_path.name}/: empty connector; "
                    f"add STATUS.md with 'stub' or 'planned', or implement it."
                )
            continue
        total = sum(_count_real_functions(p) for p in py_files)
        if total < min_funcs:
            if not _has_status_marker(dir_path):
                problems.append(
                    f"[channel] {dir_path.name}/: only {total} non-trivial "
                    f"function(s) found (need ≥{min_funcs}); "
                    f"add STATUS.md explaining why or implement it."
                )
    return problems


def _check_signal_matrix_irc() -> list[str]:
    """Signal/Matrix/IRC must be honest: either real or a STATUS marker."""
    problems: list[str] = []
    for name in ("signal", "matrix", "irc"):
        d = _APP_DIR / name
        if not d.exists():
            continue
        py_files = [p for p in d.rglob("*.py") if p.name != "__init__.py"]
        if not py_files:
            if not _has_status_marker(d):
                problems.append(
                    f"[channel] {name}/: empty; add STATUS.md saying 'stub' "
                    f"or implement the connector."
                )
    return problems


def _check_memory_md() -> list[str]:
    """MEMORY.md must not be empty (auto-write is wired)."""
    if not _MEMORY_MD.exists():
        return ["[memory] MEMORY.md does not exist; ambient loop seed broken."]
    if _MEMORY_MD.stat().st_size == 0:
        return ["[memory] MEMORY.md is empty; ambient tick not running or seed broken."]
    return []


def _check_skill_learner_wiring() -> list[str]:
    """Confirm SkillLearner.observe() is called from orchestrator."""
    if not _ORCHESTRATOR.exists():
        return ["[skills] orchestrator.py missing"]
    text = _ORCHESTRATOR.read_text(encoding="utf-8", errors="ignore")
    if "get_skill_learner" not in text or "learner.observe" not in text:
        return [
            "[skills] orchestrator.py does not call SkillLearner.observe() — "
            "the 'self-evolving skills' claim is a lie."
        ]
    return []


def _check_memory_ambient_wiring() -> list[str]:
    """Confirm AutoMemoryUpdater is wired into the ambient loop."""
    if not _AMBIENT_LOOP.exists():
        return ["[memory] ambient_loop.py missing"]
    text = _AMBIENT_LOOP.read_text(encoding="utf-8", errors="ignore")
    if "AutoMemoryUpdater" not in text:
        return [
            "[memory] ambient_loop.py does not call AutoMemoryUpdater — "
            "MEMORY.md will not auto-update."
        ]
    return []


def _check_tools_parse() -> list[str]:
    """Every tool .py file must parse as valid Python."""
    problems: list[str] = []
    if not _TOOLS_DIR.exists():
        return problems
    for py in _TOOLS_DIR.glob("*.py"):
        if py.name == "__init__.py":
            continue
        try:
            ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError as e:
            problems.append(f"[tools] {py.name} does not parse: {e}")
    return problems


def main() -> int:
    print("== RAVEN channel-truth audit (Phase 0.6) ==")
    all_problems: list[str] = []
    for check in (
        _check_channel_dirs,
        _check_signal_matrix_irc,
        _check_memory_md,
        _check_skill_learner_wiring,
        _check_memory_ambient_wiring,
        _check_tools_parse,
    ):
        all_problems.extend(check())

    if not all_problems:
        print("OK — no lies detected.")
        return 0

    print(f"FOUND {len(all_problems)} lie(s):", file=sys.stderr)
    for p in all_problems:
        print(f"  - {p}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())