"""OCR Tool — Extract text from images and PDFs using Tesseract.

Agents use this to perform optical character recognition on images
and PDF documents with optional language selection.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class OcrTool(BaseTool):
    """Extract text from images and PDF documents via OCR.

    Supports image files (jpg, png, bmp, tiff, webp) and PDF files.
    For PDFs, text extraction is attempted first; if no text is found,
    the tool falls back to OCR by converting pages to images.
    """

    group = "utility"

    def get_name(self) -> str:
        return "ocr"

    def get_description(self) -> str:
        return (
            "Extract text from images and PDF files using OCR. "
            "Actions: 'image' (OCR an image file), "
            "'pdf' (extract text from a PDF, with OCR fallback), "
            "'status' (check OCR dependencies). "
            "Supports language selection via the 'language' parameter."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: image, pdf, status",
                    required=True,
                    enum=["image", "pdf", "status"],
                ),
                ToolParameter(
                    name="filepath",
                    type="string",
                    description="Path to the image or PDF file (required for image/pdf)",
                    required=False,
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Tesseract language code (default: eng)",
                    required=False,
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Timeout in seconds for OCR operations (default: 30)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action")
        filepath = kwargs.get("filepath", "").strip()
        language = kwargs.get("language", "eng")
        timeout = int(kwargs.get("timeout", 30))

        if action == "status":
            return self._check_dependencies()

        if action in ("image", "pdf"):
            if not filepath:
                return {"success": False, "error": "filepath is required"}
            path = Path(filepath)
            if not path.exists():
                return {"success": False, "error": f"File not found: {filepath}"}

        try:
            if action == "image":
                return self._ocr_image(path, language, timeout)
            elif action == "pdf":
                return self._extract_pdf(path, language, timeout)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("OCR operation failed")
            return {"success": False, "error": str(e)}

    def _check_dependencies(self) -> dict[str, Any]:
        import importlib.util

        deps = {"tesseract": False, "pytesseract": False, "pil": False}

        deps["pytesseract"] = importlib.util.find_spec("pytesseract") is not None
        if deps["pytesseract"]:
            try:
                import pytesseract as _pt

                _pt.get_tesseract_version()
                deps["tesseract"] = True
            except Exception:
                deps["tesseract"] = False

        deps["pil"] = importlib.util.find_spec("PIL") is not None

        all_available = all(deps.values())
        return {
            "success": all_available,
            "dependencies": deps,
            "available": all_available,
        }

    def _ocr_image(self, path: Path, language: str, timeout: int) -> dict[str, Any]:
        try:
            import pytesseract
        except ImportError:
            return {
                "success": False,
                "error": "pytesseract is not installed. Run: uv pip install pytesseract",
            }

        try:
            from PIL import Image
        except ImportError:
            return {
                "success": False,
                "error": "Pillow is not installed. Run: uv pip install Pillow",
            }

        try:
            image = Image.open(path)
        except Exception as e:
            return {"success": False, "error": f"Failed to open image: {e}"}

        try:
            text = pytesseract.image_to_string(image, lang=language, timeout=timeout)
            return {
                "success": True,
                "text": text.strip(),
                "pages": 1,
                "method": "ocr",
            }
        except RuntimeError as e:
            return {"success": False, "error": f"Tesseract error: {e}"}
        except Exception as e:
            return {"success": False, "error": f"OCR failed: {e}"}

    def _extract_pdf(self, path: Path, language: str, timeout: int) -> dict[str, Any]:
        # Try text extraction first
        text_result = self._extract_pdf_text(path)
        if text_result["success"] and text_result["text"].strip():
            return {
                "success": True,
                "text": text_result["text"].strip(),
                "pages": text_result["pages"],
                "method": "text",
            }

        # Fall back to OCR
        ocr_result = self._ocr_pdf_pages(path, language, timeout)
        if ocr_result["success"]:
            ocr_result["method"] = "ocr"
            return ocr_result

        # If OCR also failed, return the original text extraction error
        # if there was meaningful text content but extraction failed somehow
        return {
            "success": False,
            "error": (
                f"Text extraction returned no content and OCR fallback failed. "
                f"Text error: {text_result.get('error', 'none')}. "
                f"OCR error: {ocr_result.get('error', 'none')}."
            ),
        }

    def _extract_pdf_text(self, path: Path) -> dict[str, Any]:
        # Try pdfminer first, then PyPDF2
        try:
            return self._extract_with_pdfminer(path)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("pdfminer extraction failed: %s", e)

        try:
            return self._extract_with_pypdf2(path)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("PyPDF2 extraction failed: %s", e)

        return {
            "success": False,
            "error": (
                "No PDF text extraction library available. "
                "Install one of: uv pip install pdfminer.six  or  uv pip install PyPDF2"
            ),
            "text": "",
            "pages": 0,
        }

    def _extract_with_pdfminer(self, path: str | Path) -> dict[str, Any]:
        from pdfminer.high_level import extract_text as pdfminer_extract_text
        from pdfminer.pdfparser import PDFParser
        from pdfminer.pdfdocument import PDFDocument

        text = pdfminer_extract_text(str(path))
        # Count pages
        with open(path, "rb") as f:
            parser = PDFParser(f)
            doc = PDFDocument(parser)
            pages = len(list(doc.get_pages()))
        return {"success": True, "text": text, "pages": pages}

    def _extract_with_pypdf2(self, path: str | Path) -> dict[str, Any]:
        from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        pages = len(reader.pages)
        text_parts: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        return {"success": True, "text": "\n".join(text_parts), "pages": pages}

    def _ocr_pdf_pages(self, path: Path, language: str, timeout: int) -> dict[str, Any]:
        try:
            import pytesseract
        except ImportError:
            return {
                "success": False,
                "error": "pytesseract is not installed. Run: uv pip install pytesseract",
            }

        try:
            from pdf2image import convert_from_path
        except ImportError:
            return {
                "success": False,
                "error": "pdf2image is not installed. Run: uv pip install pdf2image",
            }

        try:
            images = convert_from_path(str(path), dpi=300)
        except Exception as e:
            return {"success": False, "error": f"Failed to convert PDF to images: {e}"}

        all_text: list[str] = []
        for i, image in enumerate(images):
            try:
                text = pytesseract.image_to_string(image, lang=language, timeout=timeout)
                all_text.append(text)
            except RuntimeError as e:
                logger.warning("Tesseract failed on page %d: %s", i + 1, e)
                all_text.append("")
            except Exception as e:
                logger.warning("OCR failed on page %d: %s", i + 1, e)
                all_text.append("")

        combined = "\n".join(all_text).strip()
        return {
            "success": bool(combined) or len(images) > 0,
            "text": combined,
            "pages": len(images),
        }
