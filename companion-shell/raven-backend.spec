# PyInstaller spec for the RAVEN desktop sidecar.
#
# Builds a single-file binary `raven-backend` that bundles:
#   * main.py (RAVEN entry point)
#   * app/ (all core code, agents, tools, channels, web)
#   * all third-party deps from pyproject.toml
#
# The resulting binary is dropped into:
#   companion-shell/src-tauri/binaries/raven-backend
#   companion-shell/src-tauri/binaries/raven-backend.exe   (Windows)
#
# Tauri then references it via `externalBin` in tauri.conf.json
# and copies it into the bundle's resource dir on `cargo tauri build`.
#
# Build
# -----
#   uv run pyinstaller raven-backend.spec
#   # or
#   bash scripts/build-desktop.sh
#
# Cross-platform notes
# --------------------
# * macOS arm64 + x86_64 both work; the PyInstaller binary inherits
#   the host arch.  For universal macOS, build on each arch and
#   lipo them.
# * Windows: PyInstaller auto-appends `.exe`.  No need to set
#   `target_arch` here.
# * Linux: produces a single ELF binary.  Bundle it as `.AppImage`
#   or extract into a `.deb` / `.rpm` via Tauri's bundler.

# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

# We bundle from the repo root so the spec file can live in
# `companion-shell/` while still picking up `main.py` + `app/`.
ROOT = Path(os.getcwd()).resolve()
sys.path.insert(0, str(ROOT))

block_cipher = None

# Hidden imports — modules imported dynamically that PyInstaller's
# static analysis misses.  Add a new entry every time a new
# dynamic import is added to the codebase.
HIDDEN_IMPORTS = [
    # Tauri shell expects a working main loop.
    "uvicorn",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # FastAPI + Starlette
    "fastapi",
    "fastapi.middleware.cors",
    "fastapi.responses",
    "fastapi.staticfiles",
    "fastapi.templating",
    "starlette.templating",
    "starlette.responses",
    # LLM provider SDKs
    "openai",
    "anthropic",
    "google.generativeai",
    "google.ai.generativelanguage",
    "google.generativelanguage",
    "groq",
    "together",
    "cohere",
    "xai_sdk",
    # HelixDB client
    "helix",
    "helix.client",
    # Voice
    "piper",
    "piper.config",
    "piper.voice",
    "edge_tts",
    "TTS",
    "TTS.api",
    "TTS.utils",
    "whisper",
    # Discord / Telegram / Slack
    "discord",
    "discord.ext",
    "telegram",
    "telegram.ext",
    "slack_bolt",
    "slack_sdk",
    # Tools
    "playwright",
    "playwright.async_api",
    "selenium",
    "PIL",
    "cv2",
    "numpy",
    "pandas",
    "requests",
    "httpx",
    "aiohttp",
    "bs4",
    "lxml",
    "feedparser",
    "wikipedia",
    "wolframalpha",
    "yfinance",
    "pyowm",
    "praw",
    "tweepy",
    "pytube",
    "yt_dlp",
    # cowork
    "app.cowork",
    "app.cowork.workspace",
    "app.cowork.plan",
    "app.cowork.diff",
    "app.cowork.session",
    "app.cowork.worker",
    "app.cowork.store",
    "app.cowork.manager",
    # provider health probes
    "app.provider.health",
    "app.provider.manager",
    "app.provider.registry",
    # ml
    "sentence_transformers",
    "transformers",
    "torch",
    "sklearn",
    "onnxruntime",
]

# Datas — files / directories the binary needs at runtime.
# We use `Tree` so PyInstaller preserves directory structure.
def collect_data():
    """Return list of (source, dest_dir_in_bundle) tuples."""
    datas = [
        # Workspace dir is created at runtime; we don't bundle it.
        # But config defaults and SOUL.md template should ship.
        (str(ROOT / "pyproject.toml"), "."),
    ]
    # Include app/web/templates and app/web/static (templates dir
    # is required by the FastAPI server).
    for sub in ("templates", "static"):
        src = ROOT / "app" / "web" / sub
        if src.exists():
            datas.append((str(src), f"app/web/{sub}"))
    # Include the agent_reach/ skill tree if it exists.
    skill_dir = ROOT / "agent_reach"
    if skill_dir.exists():
        datas.append((str(skill_dir), "agent_reach"))
    return datas

# Excluded modules — third-party packages we don't actually
# import but transitive deps drag in.  Excluding them shrinks
# the binary by ~50MB.
EXCLUDES = [
    "tkinter",
    "matplotlib",
    "notebook",
    "jupyter",
    "IPython",
    "pytest",
    "pyright",
    "ruff",
    "sphinx",
    "setuptools",
    "wheel",
    "pip",
    "conda",
    "mkl",
    "intel_openmp",
]

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=collect_data(),
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-file vs one-dir:
#   * one-file is what we want for `externalBin` — Tauri expects
#     a single sidecar binary.  Slower to start (~1s warm-up)
#     but ships as one file.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="raven-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,             # compress with UPX if available
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,         # RAVEN writes to stdout which the shell tails
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # We do NOT set `icon` here — the shell provides the icon.
)
