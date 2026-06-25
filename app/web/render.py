"""Jinja2Templates mount + ``render_page(name, ctx)`` helper.

The Hermes-class dashboard (v31+, 2026-06-21) renders every page
through a single ``Jinja2Templates`` instance so the templates dir
and the static dir stay in lockstep with :class:`app.settings.Config`.

The render helper is intentionally tiny — every page route does::

    return render_page(request, "chat.html", {"messages": [...]})

which is just ``TemplateResponse(name, {"request": request, **ctx})``
under the hood.  Centralising the call means tests can patch
``app.web.render.render_page`` once if they need to assert every
page renders, without touching each route.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.settings.config import Config


def templates_dir() -> Path:
    """Resolve the templates directory.

    Resolved at call time (not import time) so a test that mutates
    ``Config.DASHBOARD_TEMPLATES_DIR`` before calling
    ``render_page`` sees the new path.  Defaults to the
    in-tree ``app/web/templates/``.
    """
    return Path(Config.DASHBOARD_TEMPLATES_DIR).resolve()


def templates_instance() -> Jinja2Templates:
    """Return a ``Jinja2Templates`` bound to ``templates_dir()``.

    A fresh instance per call is intentional — Jinja2Templates is
    stateless after construction, and a fresh instance avoids the
    "stale environment" footgun if a test patches the dir mid-suite.
    """
    return Jinja2Templates(directory=str(templates_dir()))


def render_page(request: Request, name: str, ctx: dict[str, Any] | None = None) -> HTMLResponse:
    """Render a template with ``{"request": request, **ctx}``."""
    payload: dict[str, Any] = {"request": request}
    if ctx:
        payload.update(ctx)
    return templates_instance().TemplateResponse(request, name, payload)
