---
name: OCR Text Extraction
module_id: skill.bundled.ocr_tool
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "extract.*text.*image|read.*text.*photo|ocr"
    confidence: 0.90
  - pattern: "scan.*document|digitize.*pdf"
    confidence: 0.85
  - pattern: "convert.*image.*text"
    confidence: 0.80
capabilities: [ocr, text-extraction, document-scanning]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# OCR Text Extraction

Extract text from images and scanned PDFs using OCR (Optical Character Recognition).

## When to Use
Use when the user needs text extracted from an image file (JPG, PNG, WebP), a screenshot, or a scanned PDF document.

## Procedure

### Extract from Image
1. Call `ocr` with `action=image` and `filepath=<path>`
2. Optionally set `language` (default "eng") for non-English text
3. Return the extracted text to the user

### Extract from PDF
1. Call `ocr` with `action=pdf` and `filepath=<path>`
2. The tool first tries text extraction (PyPDF2/pdfminer), falls back to OCR
3. Result includes `method` field showing which method succeeded
4. Present the text with page count info

### Check Status
- Call `ocr` with `action=status` to verify OCR is configured

## Example
```
User: What does this screenshot say?
Agent: [ocr: action=image, filepath=screenshot.png]
       Here's the extracted text:
       "System update available. Click to install."
```

## Dependencies
- Python: pytesseract, Pillow
- System: tesseract-ocr installed on the host
