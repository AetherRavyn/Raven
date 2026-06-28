"""Playwright-based screenshot capture for the Hermes dashboard.

Usage:
    python tests/visual/snap.py v31     # capture the 4 v31 pages
    python tests/visual/snap.py v32     # capture all 12 sidebar pages
    python tests/visual/snap.py --list  # list available page sets

Captures 1440x900 PNGs into ``tests/visual/_snaps/<cycle>/<page>.png``.
The user opens the PNGs, replies "ship" or annotates; a cycle
is locked when ``git tag v3X-ship`` is applied.

Notes:
- The script boots a fresh ``WebDashboard`` against a
  ``MagicMock`` orchestrator on 127.0.0.1:<random>; this matches
  the test fixture's shape so what the screenshots show is what
  the tests assert.
- HTMX and Tailwind CDN scripts may take a moment to fetch on
  the first run; the script waits for ``networkidle`` before
  snapping so the screenshot reflects the rendered page, not
  the loading state.
- If the chromium browser is not installed, run:
    .venv/bin/playwright install chromium
  The script falls back to a printed list of URLs when
  Playwright is missing so a CI without the browser still
  documents the page set.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
from pathlib import Path

# ── Repo layout ─────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
SNAPS_DIR = TESTS_DIR / "visual" / "_snaps"
SNAPS_DIR.mkdir(parents=True, exist_ok=True)

# ── Page sets per cycle ─────────────────────────────────────────────
PAGE_SETS: dict[str, list[str]] = {
    # v31 ships 4 read-only pages.
    "v31": ["chat", "sessions", "models", "logs"],
    # v32 will add 8 more (full 12-page dashboard).
    "v32": [
        "chat",
        "sessions",
        "models",
        "logs",
        "cron",
        "skills",
        "plugins",
        "mcp",
        "channels",
        "webhooks",
        "pairing",
        "profiles",
    ],
    # v33 voice-stack — same 12 pages; the chat page now has
    # the 🎙 button + Voice: <name> header, but the layout is
    # unchanged.  We re-snap so the v33 visual record shows
    # the post-refactor chrome.
    "v33": [
        "chat",
        "sessions",
        "models",
        "logs",
        "cron",
        "skills",
        "plugins",
        "mcp",
        "channels",
        "webhooks",
        "pairing",
        "profiles",
    ],
}


def _free_port() -> int:
    """Return an unused TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_dashboard(port: int) -> tuple["uvicorn.Server", threading.Thread]:
    """Boot the unified dashboard on 127.0.0.1:<port> in a background thread.

    Returns the uvicorn server handle and the thread it's running on.
    Caller is responsible for ``server.should_exit = True`` at teardown.
    """
    import uvicorn

    from app.api.server import app as dashboard_app

    config = uvicorn.Config(
        dashboard_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="snap-uvicorn")
    thread.start()

    # Wait for the server to be ready (max 5s).
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return server, thread
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"uvicorn did not bind 127.0.0.1:{port} within 5s")


def _snap_with_playwright(cycle: str, port: int, slugs: list[str]) -> list[Path]:
    """Use Playwright to capture each page at 1440x900."""
    from playwright.sync_api import sync_playwright

    out_dir = SNAPS_DIR / cycle
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    base = f"http://127.0.0.1:{port}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            for slug in slugs:
                page.goto(f"{base}/page/{slug}", wait_until="networkidle")
                # Give Tailwind CDN a moment to apply.
                page.wait_for_timeout(500)
                out_path = out_dir / f"{slug}.png"
                page.screenshot(path=str(out_path), full_page=False)
                paths.append(out_path)
                print(f"  ✓ {slug:<10s} → {out_path.relative_to(REPO_ROOT)}")
        finally:
            browser.close()
    return paths


def _print_fallback(cycle: str, port: int, slugs: list[str]) -> list[Path]:
    """If Playwright is missing, print URLs so CI still documents the set."""
    print(
        "\n[snap.py] Playwright not available — printing URLs instead.\n"
        "  To enable visual capture: .venv/bin/playwright install chromium\n"
    )
    base = f"http://127.0.0.1:{port}"
    for slug in slugs:
        print(f"  {base}/page/{slug}")
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("cycle", nargs="?", help="cycle key (e.g. v31) — see PAGE_SETS")
    parser.add_argument("--list", action="store_true", help="list available cycles")
    parser.add_argument("--port", type=int, default=0, help="bind port (default: random free port)")
    args = parser.parse_args(argv)

    if args.list:
        for cycle, slugs in PAGE_SETS.items():
            print(f"  {cycle}: {len(slugs)} page(s) — {', '.join(slugs)}")
        return 0

    if not args.cycle:
        parser.error("cycle is required (or pass --list)")

    if args.cycle not in PAGE_SETS:
        print(f"[snap.py] unknown cycle {args.cycle!r}; known: {list(PAGE_SETS)}")
        return 2

    slugs = PAGE_SETS[args.cycle]
    port = args.port or _free_port()
    print(f"[snap.py] booting dashboard on 127.0.0.1:{port}")
    server, _thread = _start_dashboard(port)
    try:
        try:
            paths = _snap_with_playwright(args.cycle, port, slugs)
        except Exception as exc:
            print(f"[snap.py] Playwright capture failed: {exc}")
            _print_fallback(args.cycle, port, slugs)
            return 1
        print(
            f"\n[snap.py] {len(paths)} screenshot(s) saved under tests/visual/_snaps/{args.cycle}/"
        )
    finally:
        server.should_exit = True
        time.sleep(0.3)  # give uvicorn a moment to drain
    return 0


if __name__ == "__main__":
    sys.exit(main())
