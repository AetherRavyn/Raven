"""Document Generator — create PDF, DOCX, Excel, CSV, and HTML files.

Provides three tools:
- PDFGeneratorTool: create PDFs from text, markdown, or HTML
- DocxGeneratorTool: create Word documents with structured content
- ExcelGeneratorTool: create spreadsheets with data, charts, formulas
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class PDFGeneratorTool(BaseTool):
    """Generate PDF documents from text or markdown."""

    def get_name(self) -> str:
        return "pdf_generator"

    def get_description(self) -> str:
        return (
            "Generate PDF documents from text, markdown, or HTML. "
            "Supports titles, headers, tables, lists, and basic formatting."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Text or markdown content"},
                "output_path": {"type": "string", "description": "Output file path (optional)"},
                "title": {"type": "string", "description": "Document title"},
            },
            "required": ["content"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        content = kwargs.get("content", "")
        output_path = kwargs.get("output_path", "")
        title = kwargs.get("title", "Document")

        if not content:
            return {"error": "content is required"}

        if not output_path:
            import time
            output_path = f"workspace/exports/doc_{int(time.time())}.pdf"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.units import inch
            from reportlab.lib import colors

            doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
            styles = getSampleStyleSheet()
            story = []

            # Title
            title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontSize=18, spaceAfter=12)
            story.append(Paragraph(title, title_style))
            story.append(Spacer(1, 12))

            # Content — parse markdown-like formatting
            for line in content.split('\n'):
                line = line.rstrip()
                if not line:
                    story.append(Spacer(1, 6))
                elif line.startswith('# '):
                    story.append(Paragraph(line[2:], styles['Heading1']))
                elif line.startswith('## '):
                    story.append(Paragraph(line[3:], styles['Heading2']))
                elif line.startswith('### '):
                    story.append(Paragraph(line[4:], styles['Heading3']))
                elif line.startswith('- '):
                    story.append(Paragraph(f'• {line[2:]}', styles['Normal']))
                elif line.startswith('|'):
                    # Simple table row
                    cells = [c.strip() for c in line.split('|')[1:-1]]
                    story.append(Table([cells], style=TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ])))
                else:
                    # Bold text
                    import re
                    line = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
                    line = re.sub(r'\*(.+?)\*', r'<i>\1</i>', line)
                    story.append(Paragraph(line, styles['Normal']))

            doc.build(story)
            return {"success": True, "path": output_path, "format": "pdf"}

        except ImportError:
            # Fallback: plain text PDF using fpdf2
            try:
                from fpdf import FPDF
                pdf = FPDF()
                pdf.add_page()
                pdf.set_font("Helvetica", size=12)
                pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT", align="C")
                pdf.ln(10)
                for line in content.split('\n')[:200]:
                    pdf.set_font("Helvetica", size=10)
                    pdf.multi_cell(0, 5, line[:200])
                pdf.output(output_path)
                return {"success": True, "path": output_path, "format": "pdf"}
            except ImportError:
                # Last resort: write as plain text
                txt_path = output_path.replace('.pdf', '.txt')
                Path(txt_path).write_text(f"{title}\n{'='*len(title)}\n\n{content}", encoding='utf-8')
                return {"success": True, "path": txt_path, "format": "txt", "note": "PDF libraries not installed, saved as text"}

        except Exception as e:
            return {"error": str(e)[:500]}


class DocxGeneratorTool(BaseTool):
    """Generate Word documents with structured content."""

    def get_name(self) -> str:
        return "docx_generator"

    def get_description(self) -> str:
        return "Generate Word DOCX documents with headers, paragraphs, tables, and lists."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Markdown content"},
                "output_path": {"type": "string", "description": "Output file path"},
                "title": {"type": "string", "description": "Document title"},
            },
            "required": ["content"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        content = kwargs.get("content", "")
        output_path = kwargs.get("output_path", "")
        title = kwargs.get("title", "Document")

        if not content:
            return {"error": "content is required"}

        if not output_path:
            import time
            output_path = f"workspace/exports/doc_{int(time.time())}.docx"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            from docx import Document
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            doc = Document()

            # Title
            heading = doc.add_heading(title, 0)
            heading.alignment = WD_ALIGN_PARAGRAPH.CENTER

            # Parse content
            for line in content.split('\n'):
                line = line.rstrip()
                if not line:
                    doc.add_paragraph('')
                elif line.startswith('# '):
                    doc.add_heading(line[2:], level=1)
                elif line.startswith('## '):
                    doc.add_heading(line[3:], level=2)
                elif line.startswith('### '):
                    doc.add_heading(line[4:], level=3)
                elif line.startswith('- '):
                    doc.add_paragraph(line[2:], style='List Bullet')
                elif line.startswith('1. ') or line.startswith('2. ') or line.startswith('3. '):
                    doc.add_paragraph(line[3:], style='List Number')
                elif line.startswith('|'):
                    # Table
                    rows = [c.strip() for c in line.split('|')[1:-1]]
                    if not hasattr(doc, '_current_table'):
                        table = doc.add_table(rows=1, cols=len(rows))
                        table.style = 'Table Grid'
                        for i, cell in enumerate(rows):
                            table.rows[0].cells[i].text = cell
                        doc._current_table = table
                    else:
                        row = doc._current_table.add_row()
                        for i, cell in enumerate(rows[:len(row.cells)]):
                            row.cells[i].text = cell
                else:
                    if hasattr(doc, '_current_table'):
                        delattr(doc, '_current_table')
                    doc.add_paragraph(line)

            doc.save(output_path)
            return {"success": True, "path": output_path, "format": "docx"}

        except ImportError:
            return {"error": "python-docx not installed. Run: pip install python-docx"}
        except Exception as e:
            return {"error": str(e)[:500]}


class ExcelGeneratorTool(BaseTool):
    """Generate Excel spreadsheets with data."""

    def get_name(self) -> str:
        return "excel_generator"

    def get_description(self) -> str:
        return "Generate Excel spreadsheets with structured data, headers, and basic formatting."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "headers": {"type": "array", "items": {"type": "string"}, "description": "Column headers"},
                "rows": {"type": "array", "description": "Data rows (array of arrays)"},
                "output_path": {"type": "string", "description": "Output file path"},
                "sheet_name": {"type": "string", "description": "Sheet name"},
            },
            "required": ["headers", "rows"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        headers = kwargs.get("headers", [])
        rows = kwargs.get("rows", [])
        output_path = kwargs.get("output_path", "")
        sheet_name = kwargs.get("sheet_name", "Sheet1")

        if not headers:
            return {"error": "headers is required"}

        if not output_path:
            import time
            output_path = f"workspace/exports/data_{int(time.time())}.xlsx"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = sheet_name

            # Header row with formatting
            header_font = Font(bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")

            # Data rows
            for row_idx, row_data in enumerate(rows, 2):
                for col_idx, value in enumerate(row_data, 1):
                    ws.cell(row=row_idx, column=col_idx, value=value)

            # Auto-width columns
            for col in range(1, len(headers) + 1):
                max_width = max(
                    len(str(ws.cell(row=r, column=col).value or ""))
                    for r in range(1, len(rows) + 2)
                )
                ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = min(max_width + 2, 50)

            wb.save(output_path)
            return {"success": True, "path": output_path, "format": "xlsx", "rows": len(rows)}

        except ImportError:
            return {"error": "openpyxl not installed. Run: pip install openpyxl"}
        except Exception as e:
            return {"error": str(e)[:500]}


class CSVGeneratorTool(BaseTool):
    """Generate CSV files from structured data."""

    def get_name(self) -> str:
        return "csv_generator"

    def get_description(self) -> str:
        return "Generate CSV files with headers and data rows."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "headers": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array"},
                "output_path": {"type": "string"},
            },
            "required": ["headers", "rows"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        import time
        headers = kwargs.get("headers", [])
        rows = kwargs.get("rows", [])
        output_path = kwargs.get("output_path", f"workspace/exports/data_{int(time.time())}.csv")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)
            return {"success": True, "path": output_path, "format": "csv", "rows": len(rows)}
        except Exception as e:
            return {"error": str(e)[:500]}


class HTMLGeneratorTool(BaseTool):
    """Generate styled HTML documents/reports."""

    def get_name(self) -> str:
        return "html_generator"

    def get_description(self) -> str:
        return "Generate styled HTML documents with tables, lists, and responsive layout."

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Markdown content"},
                "output_path": {"type": "string"},
                "title": {"type": "string"},
                "style": {"type": "string", "enum": ["default", "dark", "minimal"], "description": "CSS style"},
            },
            "required": ["content"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        import time
        content = kwargs.get("content", "")
        output_path = kwargs.get("output_path", f"workspace/exports/report_{int(time.time())}.html")
        title = kwargs.get("title", "Report")
        style = kwargs.get("style", "default")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Convert markdown to HTML
        import re
        html_content = content
        html_content = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html_content, flags=re.MULTILINE)
        html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)
        html_content = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html_content)
        html_content = re.sub(r'^- (.+)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)
        html_content = html_content.replace('\n\n', '</p><p>')

        bg, fg = ("#1a1a2e", "#e0e0e0") if style == "dark" else ("#ffffff", "#333333") if style == "minimal" else ("#f8f9fa", "#212529")

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: {bg}; color: {fg}; }}
h1 {{ border-bottom: 2px solid #007bff; padding-bottom: 8px; }}
h2 {{ color: #007bff; margin-top: 24px; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
th, td {{ border: 1px solid #dee2e6; padding: 8px 12px; text-align: left; }}
th {{ background: #007bff; color: white; }}
tr:nth-child(even) {{ background: #f2f2f2; }}
code {{ background: #f1f1f1; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
pre {{ background: #f8f9fa; padding: 12px; border-radius: 6px; overflow-x: auto; }}
</style></head><body>
<div class="header"><h1>{title}</h1><p style="color:#666">Generated by Raven</p></div>
<p>{html_content}</p>
</body></html>"""

        Path(output_path).write_text(html, encoding='utf-8')
        return {"success": True, "path": output_path, "format": "html"}
