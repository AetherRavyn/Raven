"""Theme Engine — Skins & Themes system for Raven.

Provides theme dataclasses, a built-in theme palette (dark/light/high-contrast),
SQLite-backed persistence, CSS custom property rendering, and import/export.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class ThemeColors:
    bg_primary: str
    bg_secondary: str
    bg_tertiary: str
    text_primary: str
    text_secondary: str
    accent: str
    accent_hover: str
    success: str
    warning: str
    error: str
    border: str


@dataclass
class ThemeTypography:
    font_family: str = "system-ui, -apple-system, sans-serif"
    font_size_base: str = "16px"
    font_size_sm: str = "14px"
    font_size_lg: str = "18px"
    font_size_xl: str = "24px"
    font_size_heading: str = "32px"
    line_height: float = 1.6
    letter_spacing: str = "0.01em"


@dataclass
class ThemeSpacing:
    padding: str = "16px"
    margin: str = "16px"
    gap: str = "12px"
    border_radius: str = "8px"
    border_radius_lg: str = "16px"


@dataclass
class ThemeEffects:
    shadow_sm: str = "0 1px 2px rgba(0,0,0,0.3)"
    shadow_md: str = "0 4px 6px rgba(0,0,0,0.4)"
    shadow_lg: str = "0 10px 30px rgba(0,0,0,0.5)"
    blur: str = "8px"
    transition: str = "0.2s ease"


@dataclass
class Theme:
    name: str
    author: str = "community"
    version: str = "1.0.0"
    description: str = ""
    colors: ThemeColors = field(default_factory=lambda: _DARK_COLORS)
    typography: ThemeTypography | None = None
    spacing: ThemeSpacing | None = None
    effects: ThemeEffects | None = None
    is_dark: bool = True
    custom_css: str = ""


# ── Built-in theme palettes ──────────────────────────────────────────────────

_DARK_COLORS = ThemeColors(
    bg_primary="#0a0a0a",
    bg_secondary="#111111",
    bg_tertiary="#1a1a1a",
    text_primary="#f5f5f5",
    text_secondary="#999999",
    accent="#ff3366",
    accent_hover="#ff6699",
    success="#22c55e",
    warning="#f59e0b",
    error="#ef4444",
    border="#2a2a2a",
)

_LIGHT_COLORS = ThemeColors(
    bg_primary="#ffffff",
    bg_secondary="#f5f5f5",
    bg_tertiary="#ebebeb",
    text_primary="#111111",
    text_secondary="#666666",
    accent="#e6005c",
    accent_hover="#cc0052",
    success="#16a34a",
    warning="#d97706",
    error="#dc2626",
    border="#d4d4d4",
)

_HIGH_CONTRAST_COLORS = ThemeColors(
    bg_primary="#000000",
    bg_secondary="#000000",
    bg_tertiary="#1a1a1a",
    text_primary="#ffffff",
    text_secondary="#ffff00",
    accent="#00ffff",
    accent_hover="#ffffff",
    success="#00ff00",
    warning="#ffff00",
    error="#ff4444",
    border="#ffffff",
)

_HIGH_CONTRAST_TYPOGRAPHY = ThemeTypography(
    font_family="system-ui, -apple-system, sans-serif",
    font_size_base="18px",
    font_size_sm="16px",
    font_size_lg="20px",
    font_size_xl="28px",
    font_size_heading="36px",
    line_height=1.8,
    letter_spacing="0.02em",
)

_HIGH_CONTRAST_EFFECTS = ThemeEffects(
    shadow_sm="0 0 0 2px #ffffff",
    shadow_md="0 0 0 3px #ffffff",
    shadow_lg="0 0 0 4px #ffffff",
    blur="0px",
    transition="0s",
)

DARK = Theme(
    name="dark",
    author="raven",
    version="1.0.0",
    description="Default dark theme",
    colors=_DARK_COLORS,
    is_dark=True,
)

LIGHT = Theme(
    name="light",
    author="raven",
    version="1.0.0",
    description="Light theme variant",
    colors=_LIGHT_COLORS,
    is_dark=False,
)

HIGH_CONTRAST = Theme(
    name="high_contrast",
    author="raven",
    version="1.0.0",
    description="Accessibility-focused high-contrast theme",
    colors=_HIGH_CONTRAST_COLORS,
    typography=_HIGH_CONTRAST_TYPOGRAPHY,
    effects=_HIGH_CONTRAST_EFFECTS,
    is_dark=True,
)

_BUILTIN_THEMES: dict[str, Theme] = {
    "dark": DARK,
    "light": LIGHT,
    "high_contrast": HIGH_CONTRAST,
}


# ── Serialisation helpers ────────────────────────────────────────────────────


def _theme_to_dict(theme: Theme) -> dict[str, Any]:
    return {
        "name": theme.name,
        "author": theme.author,
        "version": theme.version,
        "description": theme.description,
        "is_dark": theme.is_dark,
        "custom_css": theme.custom_css,
        "colors": _asdict(theme.colors) if theme.colors else None,
        "typography": _asdict(theme.typography) if theme.typography else None,
        "spacing": _asdict(theme.spacing) if theme.spacing else None,
        "effects": _asdict(theme.effects) if theme.effects else None,
    }


def _dict_to_theme(data: dict[str, Any]) -> Theme:
    colors_data = data.get("colors")
    colors = ThemeColors(**colors_data) if colors_data else _DARK_COLORS

    typography = None
    if typo_data := data.get("typography"):
        typography = ThemeTypography(**typo_data)

    spacing = None
    if spacing_data := data.get("spacing"):
        spacing = ThemeSpacing(**spacing_data)

    effects = None
    if effects_data := data.get("effects"):
        effects = ThemeEffects(**effects_data)

    return Theme(
        name=data["name"],
        author=data.get("author", "community"),
        version=data.get("version", "1.0.0"),
        description=data.get("description", ""),
        colors=colors,
        typography=typography,
        spacing=spacing,
        effects=effects,
        is_dark=data.get("is_dark", True),
        custom_css=data.get("custom_css", ""),
    )


def _asdict(obj: Any) -> dict[str, Any]:
    """Recursively convert a dataclass instance to a plain dict."""
    if hasattr(obj, "__dataclass_fields__"):
        return {f.name: _asdict(getattr(obj, f.name)) for f in obj.__dataclass_fields__.values()}
    return obj


# ── CSS rendering ────────────────────────────────────────────────────────────


def _render_color_properties(colors: ThemeColors, prefix: str = "") -> str:
    lines: list[str] = []
    for field_name in ("bg_primary", "bg_secondary", "bg_tertiary",
                       "text_primary", "text_secondary",
                       "accent", "accent_hover",
                       "success", "warning", "error",
                       "border"):
        value = getattr(colors, field_name)
        css_var = field_name.replace("_", "-")
        lines.append(f"  --{prefix}{css_var}: {value};")
    return "\n".join(lines)


def _render_typography_properties(typography: ThemeTypography, prefix: str = "") -> str:
    if typography is None:
        return ""
    lines: list[str] = []
    for field_name in ("font_family", "font_size_base", "font_size_sm", "font_size_lg",
                       "font_size_xl", "font_size_heading", "line_height", "letter_spacing"):
        value = getattr(typography, field_name)
        css_var = field_name.replace("_", "-")
        lines.append(f"  --{prefix}{css_var}: {value};")
    return "\n".join(lines)


def _render_spacing_properties(spacing: ThemeSpacing | None, prefix: str = "") -> str:
    if spacing is None:
        return ""
    lines: list[str] = []
    for field_name in ("padding", "margin", "gap", "border_radius", "border_radius_lg"):
        value = getattr(spacing, field_name)
        css_var = field_name.replace("_", "-")
        lines.append(f"  --{prefix}{css_var}: {value};")
    return "\n".join(lines)


def _render_effects_properties(effects: ThemeEffects | None, prefix: str = "") -> str:
    if effects is None:
        return ""
    lines: list[str] = []
    for field_name in ("shadow_sm", "shadow_md", "shadow_lg", "blur", "transition"):
        value = getattr(effects, field_name)
        css_var = field_name.replace("_", "-")
        lines.append(f"  --{prefix}{css_var}: {value};")
    return "\n".join(lines)


def render_css(theme: Theme) -> str:
    """Generate a CSS custom-properties string from a Theme."""
    sections: list[str] = [":root {"]

    colors_css = _render_color_properties(theme.colors)
    if colors_css:
        sections.append(colors_css)

    if theme.typography:
        typo_css = _render_typography_properties(theme.typography)
        if typo_css:
            sections.append("")
            sections.append(typo_css)

    if theme.spacing:
        spacing_css = _render_spacing_properties(theme.spacing)
        if spacing_css:
            sections.append("")
            sections.append(spacing_css)

    if theme.effects:
        effects_css = _render_effects_properties(theme.effects)
        if effects_css:
            sections.append("")
            sections.append(effects_css)

    if theme.custom_css:
        sections.append("")
        sections.append(f"  /* custom */\n{theme.custom_css}")

    sections.append("}")
    return "\n".join(sections)


# ── SQLite schema ────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS themes (
    name TEXT PRIMARY KEY,
    author TEXT NOT NULL DEFAULT 'community',
    version TEXT NOT NULL DEFAULT '1.0.0',
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL,
    installed_at TEXT NOT NULL
);
"""


# ── ThemeManager ─────────────────────────────────────────────────────────────


class ThemeManager:
    """SQLite-backed theme registry.

    Manages installation, activation, import/export, and CSS rendering
    of themes for the Raven UI.
    """

    def __init__(self, db_path: str | Path = "workspace/memory/themes.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()
        self._seed_builtins()

    # ── connection management ───────────────────────────────────────────

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def _seed_builtins(self) -> None:
        for name, theme in _BUILTIN_THEMES.items():
            existing = self._conn.execute(
                "SELECT name FROM themes WHERE name = ?", (name,)
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    """INSERT INTO themes (name, author, version, description, active, data, installed_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        theme.name,
                        theme.author,
                        theme.version,
                        theme.description,
                        1 if name == "dark" else 0,
                        json.dumps(_theme_to_dict(theme)),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        self._conn.commit()

    # ── public API ──────────────────────────────────────────────────────

    def get_active_theme(self) -> Theme:
        """Return the currently active theme (falls back to 'dark')."""
        row = self._conn.execute(
            "SELECT data FROM themes WHERE active = 1 ORDER BY name LIMIT 1"
        ).fetchone()
        if row is None:
            return DARK
        return _dict_to_theme(json.loads(row["data"]))

    def set_active_theme(self, name: str) -> bool:
        """Set a theme as active, deactivating all others.

        Returns True if the theme was found and activated.
        """
        row = self._conn.execute(
            "SELECT name FROM themes WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            logger.warning("Theme '%s' not found — cannot activate", name)
            return False
        self._conn.execute("UPDATE themes SET active = 0")
        self._conn.execute("UPDATE themes SET active = 1 WHERE name = ?", (name,))
        self._conn.commit()
        logger.info("Activated theme '%s'", name)
        return True

    def list_themes(self) -> list[Theme]:
        """Return all installed themes."""
        rows = self._conn.execute("SELECT data FROM themes ORDER BY name").fetchall()
        return [_dict_to_theme(json.loads(r["data"])) for r in rows]

    def get_theme(self, name: str) -> Theme | None:
        """Look up a single theme by name."""
        row = self._conn.execute(
            "SELECT data FROM themes WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return _dict_to_theme(json.loads(row["data"]))

    def install_theme(self, theme: Theme | dict) -> bool:
        """Install a theme, overwriting any existing one with the same name."""
        if isinstance(theme, dict):
            theme = _dict_to_theme(theme)
        data = json.dumps(_theme_to_dict(theme))
        self._conn.execute(
            """INSERT OR REPLACE INTO themes (name, author, version, description, active, data, installed_at)
               VALUES (?, ?, ?, ?, 0, ?, ?)""",
            (
                theme.name,
                theme.author,
                theme.version,
                theme.description,
                data,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        logger.info("Installed theme '%s' v%s", theme.name, theme.version)
        return True

    def uninstall_theme(self, name: str) -> bool:
        """Remove a theme by name. Cannot remove the last theme."""
        if name in _BUILTIN_THEMES:
            logger.warning("Cannot uninstall built-in theme '%s'", name)
            return False
        row = self._conn.execute(
            "SELECT name FROM themes WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            logger.warning("Theme '%s' not found — nothing to uninstall", name)
            return False
        self._conn.execute("DELETE FROM themes WHERE name = ?", (name,))
        self._conn.commit()
        logger.info("Uninstalled theme '%s'", name)
        return True

    def create_theme(
        self,
        name: str,
        colors: ThemeColors,
        *,
        author: str = "community",
        version: str = "1.0.0",
        description: str = "",
        typography: ThemeTypography | None = None,
        spacing: ThemeSpacing | None = None,
        effects: ThemeEffects | None = None,
        is_dark: bool = True,
        custom_css: str = "",
    ) -> Theme:
        """Factory method — builds and returns a new Theme (does not install)."""
        return Theme(
            name=name,
            author=author,
            version=version,
            description=description,
            colors=colors,
            typography=typography,
            spacing=spacing,
            effects=effects,
            is_dark=is_dark,
            custom_css=custom_css,
        )

    def export_theme(self, name: str) -> dict[str, Any]:
        """Return a JSON-serialisable dict for a named theme."""
        theme = self.get_theme(name)
        if theme is None:
            msg = f"Theme '{name}' not found"
            raise ValueError(msg)
        return _theme_to_dict(theme)

    def import_theme(self, data: dict) -> bool:
        """Install a theme from a JSON-serialisable dict."""
        theme = _dict_to_theme(data)
        return self.install_theme(theme)

    def render_css(self, theme: Theme | None = None) -> str:
        """Render CSS custom properties for the given theme (or active one)."""
        if theme is None:
            theme = self.get_active_theme()
        return render_css(theme)
