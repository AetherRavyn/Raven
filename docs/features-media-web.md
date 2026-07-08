# Media & Web Management

RAVEN is equipped with an extensive suite of tools for processing external media, browsing the web, manipulating files, parsing documents, generating documents, and performing OCR. All tools are registered through the `MessageOrchestrator` (`app/core/orchestrator.py`) and available to the LLM during ReAct loop execution.

## 1. Browser Automation

RAVEN uses Playwright/Selenium-based headless browser automation through the `BrowserOperationTool` (`app/tools/browsertool.py`). The browser operates in a sandboxed environment with configurable resource limits.

### Supported Operations (22+)

| Operation | Description | Parameters | Security Notes |
|---|---|---|---|
| `navigate` | Load a URL in the browser | `url` (string, required) | URL validated against blocklist |
| `click` | Click an element by selector | `selector` (string, required) | Requires approval if on sensitive domain |
| `type` | Type text into an input | `selector`, `text` (strings) | Subject to keystroke audit |
| `screenshot` | Capture visible viewport | `full_page` (bool, optional) | Stored in workspace, auto-deleted after 1h |
| `scroll` | Scroll by pixels or to element | `direction`, `amount` or `selector` | No security restrictions |
| `extract_text` | Return visible text content | `selector` (optional, defaults to body) | Content goes through prompt injection defense |
| `extract_html` | Return raw HTML | `selector` (optional) | Sanitized before injection |
| `extract_markdown` | Convert page to markdown | None | Preferred format for LLM consumption |
| `get_links` | Return all links on page | None | Subject to same-origin policy |
| `get_forms` | Detect and describe forms | None | No auto-submit without approval |
| `fill_form` | Fill a form field | `selector`, `value` | Requires approval |
| `submit_form` | Submit a detected form | `form_selector` (optional) | Requires approval |
| `wait_for` | Wait for element/condition | `selector` or `timeout` | Max timeout 30s |
| `wait_for_navigation` | Wait for page load | `timeout` (optional, default 10s) | Configurable timeout |
| `get_cookies` | Read browser cookies | None | Only same-domain, no cross-origin |
| `clear_cookies` | Clear all session data | None | Always allowed |
| `set_headers` | Set custom request headers | `headers` (dict) | Audited |
| `download_file` | Download a file from link | `url`, `selector` | Scanned by VirusTotal if configured |
| `back` | Navigate browser back | None | No-op if no history |
| `forward` | Navigate browser forward | None | No-op if no history |
| `reload` | Reload current page | None | Safe operation |
| `close` | Close browser instance | None | Auto-closed after 5min idle |

### Configuration

```ini
# Browser pool
BROWSER_POOL_SIZE=4  # Concurrent browser instances
BROWSER_TIMEOUT=30000  # Page load timeout (ms)
BROWSER_HEADLESS=true  # Run headless mode

# Content filtering
WEB_MAX_CONTENT_LENGTH=50000  # Max chars extracted per page
WEB_ALLOWED_DOMAINS=*  # Comma-separated allowed domains
WEB_BLOCKED_DOMAINS=  # Comma-separated blocked domains

# Security
ALLOW_BROWSER_AUTO_SUBMIT=false  # Require approval for form submission
BROWSER_SANDBOX=true  # Run browser in sandbox container
```

### Security Sandboxing

The browser runs with:
- **No persistent storage**: Cookies and session data are cleared between sessions unless explicitly saved
- **Domain restrictions**: Configurable allowlist/blocklist
- **Content sanitization**: Extracted text passes through the prompt injection defense (`app/core/security.py`) before LLM injection
- **Isolation**: Each browser instance runs in a separate sandboxed process with memory limits
- **Timeout**: All operations default to 30-second timeout, configurable

## 2. Web Extraction Pipeline

RAVEN converts web content into LLM-friendly formats through a multi-stage pipeline:

```
URL → HTTP Request → HTML Parsing → Markdown Conversion → LLM Context
                                                      → Structured Data
                                                      → Raw Text (fallback)
```

The pipeline uses the `WebFetchOperationTool` (`app/tools/webfetch.py`) and `WebOperationTool` (`app/tools/websearch.py`):

1. **URL Fetch**: Async HTTP request with configurable headers, cookies, and timeout
2. **HTML Parsing**: BeautifulSoup4-based HTML cleaner removes scripts, styles, navigation, ads
3. **Markdown Conversion**: HTML-to-markdown via `html2text` or custom extractor — preferred format for LLM consumption
4. **Content Truncation**: Configurable max content length (default 50K chars)
5. **Security Filter**: Adversarial input detection via `app/core/security.py`
6. **Structure Preservation**: Headers, lists, tables, code blocks converted to markdown equivalents

```python
# From orchestrator.py — web fetch route
if lowered.startswith("/webfetch") or lowered.startswith("web fetch"):
    tool = self._direct_tool("_web_fetch_tool", "web_fetch_ops")
    url = text.split(maxsplit=1)[1]
    result = await tool.execute(operation="fetch", url=url)
```

### Prompt Injection Defense

All web-extracted content passes through `app/core/security.py` which:
- Detects and neutralizes prompt injection attempts (e.g., "Ignore previous instructions")
- Wraps untrusted data in strict delimiter bounds (`[UNTRUSTED_CONTENT_START]`...`[UNTRUSTED_CONTENT_END]`)
- Strips known attack patterns (system prompt override attempts, role-play injections)
- Validates output before sending to user

## 3. Vision Pipeline

When a user uploads an image (or a camera captures a frame), RAVEN applies a multi-modal pipeline:

### Stage 1: Image Ingestion
Images arrive through:
- Platform attachment uploads (Telegram, Discord, WhatsApp, web dashboard)
- Camera snapshot tool (`CameraSnapshotTool`)
- URL references in user messages
- Direct file paths from the workspace

### Stage 2: YOLO Detection
The external monitoring system runs YOLO-based object detection on RTSP camera streams. Results are posted to the webhook receiver at `POST /internal/camera-alert` with payload:
```json
{
  "event": "person_detected",
  "camera": "front_door",
  "confidence": 0.92,
  "snapshot_path": "/tmp/snap.jpg"
}
```

### Stage 3: Semantic Embedding
Images are embedded into ChromaDB for semantic recall using:
- MobileNet (default, fast, good accuracy)
- ONNX-based models (configurable)

This enables natural language queries like "show me the picture of the red car from yesterday" or "find the screenshot with the error message."

### Stage 4: VLM Analysis
The `MultimodalContextBuilder` (`app/core/multimodal.py`) constructs a multimodal context block that is injected into the LLM messages:

```python
# From runtime.py — multimodal content array construction
if request.image_urls:
    content_array = [{"type": "text", "text": input_text}]
    for url in request.image_urls:
        content_array.append({"type": "image_url", "image_url": {"url": url}})
    user_msg = {"role": "user", "content": content_array}
```

Supported VLMs:
- xAI Grok Vision (via `XAIImageUnderstandTool`)
- GPT-4o (OpenAI)
- Gemini 1.5 Pro Vision (Google)
- Claude 3.5 Sonnet (Anthropic — accepts base64 encoded images)

### Video Fusion

The `VideoEventFusion` module (`app/core/video_fusion.py`) provides temporal analysis:
- Correlates detections across frames
- Tracks object movement and trajectories
- Generates event summaries (e.g., "Person walked from front door to kitchen over 12 seconds")
- Reduces false positives by requiring consistent detections across multiple frames

## 4. Document Parsing

RAVEN supports parsing of PDF, DOCX, XLSX, and CSV files. Parsed content is extracted and injected into the LLM context window for analysis.

### PDF Parsing

**Library**: PyMuPDF (fitz)
**Tool**: `PDFReaderTool` (`app/tools/document_parser.py`)

```python
import fitz  # PyMuPDF

async def parse_pdf(filepath: str) -> dict:
    doc = fitz.open(filepath)
    pages = []
    for page_num in range(min(len(doc), 50)):  # Max 50 pages
        page = doc[page_num]
        text = page.get_text()
        pages.append({"page": page_num + 1, "text": text, "char_count": len(text)})
    doc.close()
    return {
        "success": True,
        "total_pages": len(pages),
        "content": "\n--- Page Break ---\n".join(p["text"] for p in pages),
        "metadata": {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
        }
    }
```

**Edge cases**:
- Scanned PDFs (no text layer): Returns empty text; user is prompted to use OCR
- Password-protected: Returns error with instructions
- Exceeding 50 pages: Only first 50 pages extracted with warning
- Embedded images: Not extracted (use OCR for image-based content)

### DOCX Parsing

**Library**: python-docx
**Tool**: `DocxReaderTool` (`app/tools/document_parser.py`)

```python
from docx import Document

async def parse_docx(filepath: str) -> dict:
    doc = Document(filepath)
    paragraphs = [p.text for p in doc.paragraphs]
    tables = []
    for table in doc.tables:
        rows = []
        for row in table.rows:
            cells = [cell.text for cell in row.cells]
            rows.append(cells)
        tables.append(rows)
    return {
        "success": True,
        "content": "\n\n".join(paragraphs),
        "tables": tables,
        "metadata": {
            "paragraph_count": len(paragraphs),
            "table_count": len(tables),
            "character_count": sum(len(p) for p in paragraphs),
        }
    }
```

**Edge cases**:
- Empty documents: Returns empty content with metadata
- Very large documents (>100KB text): Truncated at 50K chars
- Embedded images: Not extracted; only text content
- Tracked changes: Not processed (stripped by python-docx)

### XLSX Parsing

**Library**: openpyxl
**Tool**: `ExcelReaderTool` (`app/tools/document_parser.py`)

```python
from openpyxl import load_workbook

async def parse_xlsx(filepath: str) -> dict:
    wb = load_workbook(filepath, read_only=True, data_only=True)
    sheets = {}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([str(cell) if cell is not None else "" for cell in row])
        sheets[sheet_name] = {
            "rows": len(rows),
            "columns": max(len(r) for r in rows) if rows else 0,
            "data": rows[:100],  # First 100 rows
        }
    wb.close()
    return {"success": True, "sheets": sheets}
```

**Edge cases**:
- Very large files (>10MB): Returns error; use batch processing
- Empty sheets: Included in sheets dict with 0 rows
- Formulas: Evaluated with `data_only=True`
- Charts/PivotTables: Not extracted; only cell data

## 5. Document Generation

RAVEN generates PDF, DOCX, XLSX, CSV, and HTML files through dedicated tools registered in the `MessageOrchestrator`.

### PDF Generation

**Library**: reportlab
**Tool**: `PDFGeneratorTool` (`app/tools/document_generator.py`)

```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table

async def generate_pdf(title: str, content: str, filename: str) -> str:
    doc = SimpleDocTemplate(filename, pagesize=letter)
    story = []
    story.append(Paragraph(f"<h1>{title}</h1>"))
    for line in content.split("\n"):
        story.append(Paragraph(line))
        story.append(Spacer(1, 6))
    doc.build(story)
    return filename
```

Features: Unicode text, tables, headers/footers, page numbers, margins, font embedding, color support, image embedding, hyperlinks.

### DOCX Generation

**Library**: python-docx
**Tool**: `DocxGeneratorTool` (`app/tools/document_generator.py`)

```python
from docx import Document
from docx.shared import Inches, Pt, RGBColor

async def generate_docx(title: str, content: str, filename: str) -> str:
    doc = Document()
    doc.add_heading(title, 0)
    for line in content.split("\n"):
        if line.strip():
            doc.add_paragraph(line)
        else:
            doc.add_paragraph("")  # Blank line
    doc.save(filename)
    return filename
```

Features: Headings (6 levels), tables, images, bullet lists, numbered lists, styles, margins, page breaks, headers/footers.

### XLSX Generation

**Library**: openpyxl
**Tool**: `ExcelGeneratorTool` (`app/tools/document_generator.py`)

```python
from openpyxl import Workbook

async def generate_xlsx(sheet_name: str, headers: list[str], data: list[list], filename: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in data:
        ws.append(row)
    wb.save(filename)
    return filename
```

Features: Multiple sheets, cell styling, formulas, column widths, row heights, merged cells, data validation, conditional formatting.

### CSV Generation

**Tool**: `CSVGeneratorTool` (`app/tools/document_generator.py`)

Simple CSV generation with proper escaping (quotes around fields containing commas, newlines, or quotes). UTF-8 encoding with BOM for Excel compatibility. Configurable delimiter and quoting style.

### HTML Generation

**Tool**: `HTMLGeneratorTool` (`app/tools/document_generator.py`)

Generates standalone HTML documents with CSS styling. Supports: responsive layout, tables, code syntax highlighting, images, hyperlinks, embedded CSS, meta tags, and print-friendly formatting.

## 6. OCR (Optical Character Recognition)

**Library**: pytesseract (Tesseract OCR wrapper)
**Tool**: `OcrTool` (`app/tools/ocrtool.py`)

Extracts text from images when document parsing returns empty content (scanned PDFs, photographed documents):

```python
import pytesseract
from PIL import Image

async def extract_text_from_image(image_path: str, lang: str = "eng") -> dict:
    try:
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image, lang=lang)
        return {
            "success": True,
            "text": text.strip(),
            "confidence": pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
```

**Languages**: eng, spa, fra, deu, ita, por, rus, jpn, chn, kor, ara, hin (requires corresponding Tesseract language packs)

**Pre-processing**: The tool applies optional pre-processing:
- Grayscale conversion
- Binarization (thresholding)
- Deskewing
- Noise removal
- Contrast enhancement

**Edge cases**:
- Low-resolution images: Returns lower confidence; suggests using higher-res source
- Handwritten text: Returns with confidence < 50%; warns user
- Multi-column layout: Processes left-to-right, top-to-bottom
- Mixed-language documents: Best results with single language; multi-language falls back to auto-detect

## 7. Media Format Support Matrix

| Operation | Input Formats | Output Formats | Libraries |
|---|---|---|---|
| Document Parse | PDF, DOCX, XLSX, CSV, TXT | Text | PyMuPDF, python-docx, openpyxl |
| Document Generate | Text/Data | PDF, DOCX, XLSX, CSV, HTML | reportlab, python-docx, openpyxl |
| OCR | PNG, JPG, JPEG, TIFF, BMP, WEBP | Text | pytesseract, Pillow |
| Image Analyze | PNG, JPG, GIF, WEBP | Structured Analysis | YOLO, MobileNet, VLMs |
| Audio Transcribe | MP3, WAV, M4A, OGG, FLAC | Text | pywhispercpp, Vosk |
| Image Generate | Text prompt | PNG | Stable Diffusion, DALL-E, etc. |
| Video Fusion | RTSP stream URLs | Text events | OpenCV, YOLO |
| Web Browsing | URLs | Markdown, Text, HTML | Playwright, BeautifulSoup4 |
| Web Search | Text query | Structured results | Google API, SearXNG, DuckDuckGo |
| File Operations | Any | Same format | pathlib, shutil |

## 8. Configuration

```ini
# Web extraction
WEB_MAX_CONTENT_LENGTH=50000
WEB_REQUEST_TIMEOUT=10

# Browser automation
BROWSER_POOL_SIZE=4
BROWSER_TIMEOUT=30000
BROWSER_HEADLESS=true
BROWSER_SANDBOX=true

# Document parsing
PDF_MAX_PAGES=50
DOCX_MAX_CHARS=50000
XLSX_MAX_ROWS=100
XLSX_MAX_SIZE_MB=10

# OCR
OCR_DEFAULT_LANG=eng
OCR_ENABLE_PREPROCESSING=true
OCR_CONFIDENCE_THRESHOLD=50

# Image analysis
VISION_ENABLED=true
VISION_MAX_IMAGE_SIZE_MB=20
YOLO_CONFIDENCE_THRESHOLD=0.5

# Media storage
MEDIA_CACHE_DIR=workspace/media
MEDIA_CACHE_TTL_HOURS=24
MEDIA_AUTO_DELETE=true
```
