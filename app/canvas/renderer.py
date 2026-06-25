"""Canvas Renderer — Converts canvas components to HTML/JS.

Generates a self-contained HTML page (or fragment) from canvas state.
Uses Chart.js for charts, Prism.js for code highlighting, and custom
CSS for the AetherRavyn HUD aesthetic.
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

from app.canvas.live_canvas import CanvasComponent, ComponentType, LiveCanvas

logger = logging.getLogger(__name__)

# ── CSS Theme ───────────────────────────────────────────────────────

_CSS = """
:root {
  --bg-primary: #0a0e17;
  --bg-card: #111827;
  --bg-card-hover: #1a2332;
  --border: #1e293b;
  --text-primary: #e2e8f0;
  --text-secondary: #94a3b8;
  --accent: #6366f1;
  --accent-glow: rgba(99, 102, 241, 0.3);
  --success: #22c55e;
  --warning: #f59e0b;
  --danger: #ef4444;
  --font: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  --radius: 12px;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: var(--font);
  line-height: 1.6;
  padding: 24px;
}

.canvas-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  max-width: 1400px;
  margin: 0 auto;
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  transition: all 0.2s ease;
  backdrop-filter: blur(10px);
}

.card:hover {
  border-color: var(--accent);
  box-shadow: 0 0 20px var(--accent-glow);
  transform: translateY(-1px);
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.w-full { grid-column: span 4; }
.w-half { grid-column: span 2; }
.w-third { grid-column: span 1; }
.w-quarter { grid-column: span 1; }

/* Metric Card */
.metric-value {
  font-size: 36px;
  font-weight: 700;
  color: var(--accent);
  line-height: 1;
}
.metric-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}
.metric-trend { font-size: 12px; margin-top: 4px; }
.trend-up { color: var(--success); }
.trend-down { color: var(--danger); }

/* Table */
table { width: 100%; border-collapse: collapse; }
th {
  text-align: left;
  font-size: 12px;
  text-transform: uppercase;
  color: var(--text-secondary);
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}
td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
}
tr:hover { background: var(--bg-card-hover); }

/* Code */
.code-block {
  background: #0d1117;
  border-radius: 8px;
  padding: 16px;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.5;
  color: #e6edf3;
}

/* Terminal */
.terminal {
  background: #000;
  border-radius: 8px;
  padding: 16px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: #4ade80;
  white-space: pre-wrap;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
}

/* Progress */
.progress-bar {
  background: var(--border);
  border-radius: 6px;
  height: 8px;
  overflow: hidden;
  margin-top: 8px;
}
.progress-fill {
  background: linear-gradient(90deg, var(--accent), #818cf8);
  height: 100%;
  border-radius: 6px;
  transition: width 0.5s ease;
}
.progress-label {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--text-secondary);
}

/* Markdown */
.markdown-content h1, .markdown-content h2, .markdown-content h3 {
  margin-top: 16px;
  margin-bottom: 8px;
}
.markdown-content p { margin-bottom: 8px; }
.markdown-content code {
  background: rgba(99, 102, 241, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 13px;
}

/* Image */
.canvas-image {
  max-width: 100%;
  border-radius: 8px;
}

/* Header */
.canvas-header {
  text-align: center;
  margin-bottom: 24px;
}
.canvas-header h1 {
  font-size: 24px;
  background: linear-gradient(135deg, var(--accent), #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.canvas-header .version {
  font-size: 12px;
  color: var(--text-secondary);
}

@media (max-width: 768px) {
  .canvas-grid { grid-template-columns: 1fr; }
  .w-half, .w-third, .w-quarter { grid-column: span 1; }
}
"""


class CanvasRenderer:
    """Renders a LiveCanvas to HTML."""

    def render_full_page(self, canvas: LiveCanvas, title: str = "AetherRavyn HUD") -> str:
        """Render a complete self-contained HTML page."""
        body = self.render_fragment(canvas)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>
<div class="canvas-header">
  <h1>🦅 {html.escape(title)}</h1>
  <div class="version">v{canvas.version} · {canvas.component_count} components</div>
</div>
{body}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>{self._chart_scripts(canvas)}</script>
</body>
</html>"""

    def render_fragment(self, canvas: LiveCanvas) -> str:
        """Render just the grid of components (for embedding)."""
        components = canvas.list_components()
        if not components:
            return '<div class="canvas-grid"><div class="card w-full">No components</div></div>'

        parts: list[str] = ['<div class="canvas-grid">']
        for comp in components:
            if not comp.visible:
                continue
            parts.append(self._render_component(comp))
        parts.append("</div>")
        return "\n".join(parts)

    def _render_component(self, comp: CanvasComponent) -> str:
        """Render a single component to HTML."""
        width_class = {
            "full": "w-full", "half": "w-half",
            "third": "w-third", "quarter": "w-quarter",
        }.get(comp.width, "w-full")

        title_html = ""
        if comp.title:
            title_html = f'<div class="card-title">{html.escape(comp.title)}</div>'

        content = self._render_content(comp)

        return f'<div class="card {width_class}" id="comp-{comp.id}">{title_html}{content}</div>'

    def _render_content(self, comp: CanvasComponent) -> str:
        """Render component content based on type."""
        handlers = {
            ComponentType.MARKDOWN.value: self._render_markdown,
            ComponentType.TABLE.value: self._render_table,
            ComponentType.CHART.value: self._render_chart,
            ComponentType.CODE.value: self._render_code,
            ComponentType.METRIC.value: self._render_metric,
            ComponentType.PROGRESS.value: self._render_progress,
            ComponentType.TERMINAL.value: self._render_terminal,
            ComponentType.IMAGE.value: self._render_image,
            ComponentType.DIVIDER.value: lambda _: "<hr>",
        }
        handler = handlers.get(comp.type, self._render_markdown)
        return handler(comp)

    def _render_markdown(self, comp: CanvasComponent) -> str:
        content = html.escape(comp.data.get("content", ""))
        return f'<div class="markdown-content">{content}</div>'

    def _render_table(self, comp: CanvasComponent) -> str:
        headers = comp.data.get("headers", [])
        rows = comp.data.get("rows", [])
        ths = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
        trs: list[str] = []
        for row in rows:
            tds = "".join(f"<td>{html.escape(str(c))}</td>" for c in row)
            trs.append(f"<tr>{tds}</tr>")
        return f"<table><thead><tr>{ths}</tr></thead><tbody>{''.join(trs)}</tbody></table>"

    def _render_chart(self, comp: CanvasComponent) -> str:
        canvas_id = f"chart-{comp.id}"
        return f'<canvas id="{canvas_id}" height="200"></canvas>'

    def _render_code(self, comp: CanvasComponent) -> str:
        code = html.escape(comp.data.get("code", ""))
        lang = html.escape(comp.data.get("language", ""))
        return f'<div class="code-block"><code data-lang="{lang}">{code}</code></div>'

    def _render_metric(self, comp: CanvasComponent) -> str:
        value = html.escape(str(comp.data.get("value", "—")))
        label = html.escape(str(comp.data.get("label", "")))
        trend = comp.data.get("trend", "")
        trend_class = "trend-up" if trend.startswith("+") else "trend-down" if trend.startswith("-") else ""
        trend_html = f'<div class="metric-trend {trend_class}">{html.escape(trend)}</div>' if trend else ""
        return f'<div class="metric-value">{value}</div><div class="metric-label">{label}</div>{trend_html}'

    def _render_progress(self, comp: CanvasComponent) -> str:
        value = float(comp.data.get("value", 0))
        max_val = float(comp.data.get("max", 1.0))
        label = html.escape(str(comp.data.get("label", "")))
        pct = (value / max_val * 100) if max_val > 0 else 0
        return (
            f'<div class="progress-label"><span>{label}</span><span>{pct:.0f}%</span></div>'
            f'<div class="progress-bar"><div class="progress-fill" style="width:{pct}%"></div></div>'
        )

    def _render_terminal(self, comp: CanvasComponent) -> str:
        output = html.escape(comp.data.get("output", ""))
        return f'<div class="terminal">{output}</div>'

    def _render_image(self, comp: CanvasComponent) -> str:
        url = html.escape(comp.data.get("url", ""))
        alt = html.escape(comp.data.get("alt", ""))
        return f'<img class="canvas-image" src="{url}" alt="{alt}" loading="lazy">'

    def _chart_scripts(self, canvas: LiveCanvas) -> str:
        """Generate Chart.js initialization scripts for all chart components."""
        scripts: list[str] = []
        for comp in canvas.list_components():
            if comp.type != ComponentType.CHART.value:
                continue
            chart_type = comp.data.get("chart_type", "bar")
            labels = json.dumps(comp.data.get("labels", []))
            datasets = json.dumps(comp.data.get("datasets", []))
            scripts.append(f"""
new Chart(document.getElementById('chart-{comp.id}'), {{
  type: '{chart_type}',
  data: {{ labels: {labels}, datasets: {datasets} }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }},
      y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }}
            }}
   }}
}});""")
        return "\n".join(scripts)


def render_canvas_html(canvas: LiveCanvas, title: str = "AetherRavyn HUD") -> str:
    """Convenience function to render a full HTML page from a canvas."""
    renderer = CanvasRenderer()
    return renderer.render_full_page(canvas, title)
