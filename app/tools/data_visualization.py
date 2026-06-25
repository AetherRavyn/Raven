"""Data Visualization — generate charts and plots from data.

Provides tools for creating bar charts, line charts, pie charts,
scatter plots, and heatmaps from structured data.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ChartGeneratorTool(BaseTool):
    """Generate charts and plots from data."""

    def get_name(self) -> str:
        return "chart_generator"

    def get_description(self) -> str:
        return (
            "Generate charts and visualizations: bar, line, pie, scatter, heatmap. "
            "Input is structured data (labels + values). Output is a PNG image file."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": ["bar", "line", "pie", "scatter", "heatmap", "histogram"],
                    "description": "Type of chart to generate",
                },
                "title": {"type": "string", "description": "Chart title"},
                "labels": {"type": "array", "items": {"type": "string"}, "description": "X-axis labels or category names"},
                "values": {"type": "array", "description": "Y-axis values or data points"},
                "series": {"type": "array", "description": "Multiple data series for line/bar charts"},
                "x_label": {"type": "string", "description": "X-axis label"},
                "y_label": {"type": "string", "description": "Y-axis label"},
                "output_path": {"type": "string", "description": "Output PNG path"},
                "width": {"type": "integer", "description": "Chart width in pixels (default 800)"},
                "height": {"type": "integer", "description": "Chart height in pixels (default 500)"},
                "colors": {"type": "array", "items": {"type": "string"}, "description": "Custom colors (hex or names)"},
            },
            "required": ["chart_type", "labels", "values"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        chart_type = kwargs.get("chart_type", "bar")
        title = kwargs.get("title", "Chart")
        labels = kwargs.get("labels", [])
        values = kwargs.get("values", [])
        series = kwargs.get("series", [])
        x_label = kwargs.get("x_label", "")
        y_label = kwargs.get("y_label", "")
        output_path = kwargs.get("output_path", "")
        width = kwargs.get("width", 800)
        height = kwargs.get("height", 500)
        colors = kwargs.get("colors", [])

        if not labels or not values:
            return {"error": "labels and values are required"}

        if not output_path:
            import time
            output_path = f"workspace/exports/chart_{int(time.time())}.png"

        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import numpy as np

            fig, ax = plt.subplots(figsize=(width/100, height/100), dpi=100)

            # Apply style
            plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn' in plt.style.available else 'default')

            default_colors = ['#007bff', '#28a745', '#ffc107', '#dc3545', '#17a2b8', '#6f42c1', '#fd7e14', '#20c997']
            use_colors = colors if colors else default_colors

            if chart_type == "bar":
                x = np.arange(len(labels))
                if series:
                    for i, s in enumerate(series):
                        ax.bar(x + i * 0.15, s, 0.15, label=f'Series {i+1}', color=use_colors[i % len(use_colors)])
                    ax.legend()
                else:
                    ax.bar(x, values, color=use_colors[:len(values)])
                ax.set_xticks(x)
                ax.set_xticklabels(labels, rotation=45 if len(labels) > 5 else 0, ha='right')

            elif chart_type == "line":
                if series:
                    for i, s in enumerate(series):
                        ax.plot(labels, s, marker='o', label=f'Series {i+1}', color=use_colors[i % len(use_colors)])
                    ax.legend()
                else:
                    ax.plot(labels, values, marker='o', color=use_colors[0], linewidth=2, markersize=8)

            elif chart_type == "pie":
                explode = [0.05] * len(labels)
                wedges, texts, autotexts = ax.pie(
                    values, labels=labels, autopct='%1.1f%%', startangle=90,
                    colors=use_colors[:len(labels)], explode=explode,
                    textprops={'fontsize': 10},
                )
                for text in autotexts:
                    text.set_fontsize(9)

            elif chart_type == "scatter":
                if isinstance(values[0], (list, tuple)) and len(values[0]) == 2:
                    x_data = [v[0] for v in values]
                    y_data = [v[1] for v in values]
                else:
                    x_data = list(range(len(values)))
                    y_data = values
                ax.scatter(x_data, y_data, c=use_colors[0], s=80, alpha=0.7, edgecolors='white')
                if len(x_data) == len(labels):
                    for i, label in enumerate(labels):
                        ax.annotate(label, (x_data[i], y_data[i]), fontsize=8)

            elif chart_type == "heatmap":
                data = np.array(values) if isinstance(values[0], list) else np.array([values])
                im = ax.imshow(data, cmap='YlOrRd', aspect='auto')
                plt.colorbar(im, ax=ax)
                ax.set_xticks(range(len(labels)))
                ax.set_xticklabels(labels, rotation=45)
                if len(values[0]) if isinstance(values[0], list) else 0:
                    for i in range(data.shape[0]):
                        for j in range(data.shape[1]):
                            ax.text(j, i, f'{data[i,j]:.1f}', ha='center', va='center', fontsize=8)

            elif chart_type == "histogram":
                ax.hist(values, bins=20, color=use_colors[0], edgecolor='white', alpha=0.7)

            ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
            if x_label:
                ax.set_xlabel(x_label, fontsize=11)
            if y_label:
                ax.set_ylabel(y_label, fontsize=11)

            plt.tight_layout()
            fig.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

            return {"success": True, "path": output_path, "chart_type": chart_type, "data_points": len(labels)}

        except ImportError:
            return {"error": "matplotlib not installed. Run: pip install matplotlib"}
        except Exception as e:
            return {"error": str(e)[:500]}


class TableVisualizerTool(BaseTool):
    """Create visual table images from data."""

    def get_name(self) -> str:
        return "table_visualizer"

    def get_description(self) -> str:
        return "Create a styled table image from JSON data."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "data": {"type": "array", "description": "Array of objects or arrays"},
                "title": {"type": "string"},
                "output_path": {"type": "string"},
            },
            "required": ["data"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        data = kwargs.get("data", [])
        title = kwargs.get("title", "Data Table")
        output_path = kwargs.get("output_path", "")

        if not data:
            return {"error": "data is required"}

        if not output_path:
            import time
            output_path = f"workspace/exports/table_{int(time.time())}.png"

        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt

            if isinstance(data[0], dict):
                headers = list(data[0].keys())
                rows = [[str(row.get(h, '')) for h in headers] for row in data]
            else:
                headers = [f"Col {i}" for i in range(len(data[0]))]
                rows = [[str(c) for c in row] for row in data]

            fig, ax = plt.subplots(figsize=(max(8, len(headers)*2), max(2, len(rows)*0.4 + 1)))
            ax.axis('off')
            ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

            table = ax.table(
                cellText=rows, colLabels=headers, loc='center',
                cellLoc='center', colColours=['#007bff']*len(headers),
            )
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1.2, 1.5)

            for (row, col), cell in table.get_celld().items():
                if row == 0:
                    cell.set_text_props(color='white', fontweight='bold')
                elif row % 2 == 0:
                    cell.set_facecolor('#f8f9fa')

            plt.tight_layout()
            fig.savefig(output_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

            return {"success": True, "path": output_path, "rows": len(rows), "columns": len(headers)}
        except ImportError:
            return {"error": "matplotlib not installed. Run: pip install matplotlib"}
        except Exception as e:
            return {"error": str(e)[:500]}
