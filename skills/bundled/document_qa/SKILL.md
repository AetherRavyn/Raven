---
name: Document Q&A
module_id: skill.bundled.document_qa
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "read.*pdf"
    confidence: 0.85
  - pattern: "summarize.*document"
    confidence: 0.85
  - pattern: "what.*excel|read.*spreadsheet"
    confidence: 0.85
capabilities: [document-analysis, pdf-extraction, spreadsheet-query]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Document Q&A

Extract, summarize, and answer questions about PDFs, Word docs, and Excel spreadsheets.

## When to Use
User provides a document path or asks to read/analyze a PDF, DOCX, or XLSX file. Supports question-answering over document content.

## Procedure

### Step 1: Identify Document Type
1. Check the file extension (.pdf, .docx, .xlsx, .csv)
2. Select the appropriate reader tool

### Step 2: Extract Content
- **PDF**: Use `pdf_reader` with operation `extract_text`
- **DOCX**: Use `docx_reader` with operation `extract_text` or `structure`
- **Excel**: Use `excel_reader` with operation `read` or `stats`

### Step 3: Answer the Question
1. Search the extracted content for relevant information
2. Synthesize a direct answer
3. Cite page/row numbers when possible

### Step 4: Follow-up
- Offer to extract specific sections
- Offer to summarize or create bullet points
- Offer to export filtered data

## Example
**User:** "Summarize the contract at /docs/contract.pdf"
**Raven:** Extracts text from PDF, identifies key clauses (parties, dates, terms, obligations), produces a structured summary.
