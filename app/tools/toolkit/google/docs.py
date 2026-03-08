from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class GoogleDocsTool(BaseTool):
    SCOPES = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive.file",  # needed for create/copy/delete/export
    ]

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "docs_token.json",
    ):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._docs_service = None
        self._drive_service = None

    # ------------------------------------------------------------------ #
    #  Auth / service                                                       #
    # ------------------------------------------------------------------ #

    def _get_credentials(self) -> Credentials:
        creds = None
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(self.token_file, "w") as token:
                token.write(creds.to_json())
        return creds

    def _get_docs_service(self):
        if self._docs_service is None:
            self._docs_service = build(
                "docs", "v1", credentials=self._get_credentials()
            )
        return self._docs_service

    def _get_drive_service(self):
        if self._drive_service is None:
            self._drive_service = build(
                "drive", "v3", credentials=self._get_credentials()
            )
        return self._drive_service

    # ------------------------------------------------------------------ #
    #  Tool metadata                                                        #
    # ------------------------------------------------------------------ #

    def get_name(self) -> str:
        return "google_docs"

    def get_description(self) -> str:
        return (
            "Google Docs management tool. Supports: creating, copying, and deleting documents; "
            "reading full document content and metadata; inserting, replacing, and deleting text; "
            "applying paragraph styles and text formatting; inserting tables, images, page breaks, "
            "and horizontal rules; managing headers and footers; finding and replacing text; "
            "batch updates for complex multi-step edits; and exporting documents to PDF, DOCX, or plain text."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                # ── Core ──────────────────────────────────────────────── #
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Docs operation to perform.",
                    required=True,
                    enum=[
                        # Document lifecycle
                        "create_document",
                        "get_document",
                        "copy_document",
                        "delete_document",
                        "export_document",
                        # Reading
                        "read_content",
                        "get_document_info",
                        # Text editing
                        "insert_text",
                        "delete_content",
                        "replace_text",
                        "find_replace",
                        # Structural inserts
                        "insert_table",
                        "insert_image",
                        "insert_page_break",
                        "insert_horizontal_rule",
                        # Formatting
                        "apply_paragraph_style",
                        "apply_text_style",
                        "apply_named_style",
                        # Header / footer
                        "create_header_footer",
                        "insert_text_in_header_footer",
                        # Batch
                        "batch_update",
                    ],
                ),
                # ── Identifiers ────────────────────────────────────────── #
                ToolParameter(
                    name="document_id",
                    type="string",
                    description="ID of the Google Doc (from its URL).",
                    required=False,
                ),
                # ── Document creation ──────────────────────────────────── #
                ToolParameter(
                    name="title",
                    type="string",
                    description="Title for a new or copied document.",
                    required=False,
                ),
                # ── Export ────────────────────────────────────────────── #
                ToolParameter(
                    name="export_format",
                    type="string",
                    description="Format for export_document: 'pdf', 'docx', or 'txt'.",
                    required=False,
                    enum=["pdf", "docx", "txt"],
                ),
                ToolParameter(
                    name="export_path",
                    type="string",
                    description="Local file path where the exported file will be saved.",
                    required=False,
                ),
                # ── Text / content ─────────────────────────────────────── #
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text content to insert.",
                    required=False,
                ),
                ToolParameter(
                    name="index",
                    type="integer",
                    description=(
                        "1-based character index in the document where the operation starts. "
                        "Use 1 to insert at the very beginning."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="start_index",
                    type="integer",
                    description="1-based start index of a content range.",
                    required=False,
                ),
                ToolParameter(
                    name="end_index",
                    type="integer",
                    description="1-based end index (exclusive) of a content range.",
                    required=False,
                ),
                # ── Find & Replace ─────────────────────────────────────── #
                ToolParameter(
                    name="find",
                    type="string",
                    description="Text or regex pattern to search for.",
                    required=False,
                ),
                ToolParameter(
                    name="replacement",
                    type="string",
                    description="Replacement text.",
                    required=False,
                ),
                ToolParameter(
                    name="match_case",
                    type="boolean",
                    description="Case-sensitive find/replace (default: false).",
                    required=False,
                ),
                # ── Named paragraph style ──────────────────────────────── #
                ToolParameter(
                    name="named_style",
                    type="string",
                    description=(
                        "Named paragraph style for apply_named_style. "
                        "One of: 'NORMAL_TEXT', 'TITLE', 'SUBTITLE', "
                        "'HEADING_1' … 'HEADING_6'."
                    ),
                    required=False,
                    enum=[
                        "NORMAL_TEXT",
                        "TITLE",
                        "SUBTITLE",
                        "HEADING_1",
                        "HEADING_2",
                        "HEADING_3",
                        "HEADING_4",
                        "HEADING_5",
                        "HEADING_6",
                    ],
                ),
                # ── Paragraph style ────────────────────────────────────── #
                ToolParameter(
                    name="paragraph_style",
                    type="object",
                    description=(
                        "ParagraphStyle fields for apply_paragraph_style. "
                        "Supported keys: alignment ('START'|'CENTER'|'END'|'JUSTIFIED'), "
                        "lineSpacing (float, e.g. 1.5), "
                        "spaceAbove ({magnitude, unit}), spaceBelow ({magnitude, unit}), "
                        "indentStart ({magnitude, unit}), indentEnd ({magnitude, unit}), "
                        "indentFirstLine ({magnitude, unit}), "
                        "keepLinesTogether (bool), keepWithNext (bool)."
                    ),
                    required=False,
                ),
                # ── Text style ─────────────────────────────────────────── #
                ToolParameter(
                    name="text_style",
                    type="object",
                    description=(
                        "TextStyle fields for apply_text_style. "
                        "Supported keys: bold (bool), italic (bool), underline (bool), "
                        "strikethrough (bool), smallCaps (bool), "
                        "fontSize ({magnitude, unit}), "
                        "foregroundColor ({color: {rgbColor: {red,green,blue}}}), "
                        "backgroundColor ({color: {rgbColor: {red,green,blue}}}), "
                        "link ({url: 'https://...'}), baselineOffset ('NONE'|'SUPERSCRIPT'|'SUBSCRIPT'), "
                        "weightedFontFamily ({fontFamily: 'Arial'})."
                    ),
                    required=False,
                ),
                # ── Table ──────────────────────────────────────────────── #
                ToolParameter(
                    name="rows",
                    type="integer",
                    description="Number of rows for insert_table.",
                    required=False,
                ),
                ToolParameter(
                    name="columns",
                    type="integer",
                    description="Number of columns for insert_table.",
                    required=False,
                ),
                # ── Image ──────────────────────────────────────────────── #
                ToolParameter(
                    name="image_uri",
                    type="string",
                    description="Publicly accessible URI of the image to insert.",
                    required=False,
                ),
                ToolParameter(
                    name="image_width",
                    type="number",
                    description="Image width in points (1 inch = 72 pt).",
                    required=False,
                ),
                ToolParameter(
                    name="image_height",
                    type="number",
                    description="Image height in points.",
                    required=False,
                ),
                # ── Header / footer ────────────────────────────────────── #
                ToolParameter(
                    name="header_footer_type",
                    type="string",
                    description="'header' or 'footer' for header/footer operations.",
                    required=False,
                    enum=["header", "footer"],
                ),
                ToolParameter(
                    name="section_type",
                    type="string",
                    description="Section type when creating a header/footer: 'DEFAULT' or 'FIRST_PAGE'.",
                    required=False,
                    enum=["DEFAULT", "FIRST_PAGE"],
                ),
                # ── Batch ──────────────────────────────────────────────── #
                ToolParameter(
                    name="requests",
                    type="array",
                    description=(
                        "Raw list of Docs API request objects for batch_update. "
                        "Each item is a dict matching a Docs API Request type "
                        "(e.g. {'insertText': {'location': {'index': 1}, 'text': 'Hello'}})."
                    ),
                    required=False,
                ),
            ],
        )

    # ------------------------------------------------------------------ #
    #  Entry point                                                          #
    # ------------------------------------------------------------------ #

    async def execute(
        self,
        operation: str,
        document_id: Optional[str] = None,
        title: Optional[str] = None,
        export_format: Optional[str] = None,
        export_path: Optional[str] = None,
        text: Optional[str] = None,
        index: Optional[int] = None,
        start_index: Optional[int] = None,
        end_index: Optional[int] = None,
        find: Optional[str] = None,
        replacement: Optional[str] = None,
        match_case: bool = False,
        named_style: Optional[str] = None,
        paragraph_style: Optional[Dict[str, Any]] = None,
        text_style: Optional[Dict[str, Any]] = None,
        rows: Optional[int] = None,
        columns: Optional[int] = None,
        image_uri: Optional[str] = None,
        image_width: Optional[float] = None,
        image_height: Optional[float] = None,
        header_footer_type: Optional[str] = None,
        section_type: str = "DEFAULT",
        requests: Optional[List[Dict[str, Any]]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        try:
            docs = self._get_docs_service()

            # ── Document lifecycle ───────────────────────────────────── #
            if operation == "create_document":
                if not title:
                    return {"success": False, "error": "'title' is required."}
                doc = docs.documents().create(body={"title": title}).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "document_id": doc["documentId"],
                    "title": doc.get("title"),
                    "document_url": f"https://docs.google.com/document/d/{doc['documentId']}/edit",
                }

            elif operation == "get_document":
                if not document_id:
                    return {"success": False, "error": "'document_id' is required."}
                doc = docs.documents().get(documentId=document_id).execute()
                return {"success": True, "operation": operation, "document": doc}

            elif operation == "copy_document":
                if not document_id or not title:
                    return {
                        "success": False,
                        "error": "'document_id' and 'title' are required.",
                    }
                drive = self._get_drive_service()
                result = (
                    drive.files()
                    .copy(fileId=document_id, body={"name": title})
                    .execute()
                )
                return {
                    "success": True,
                    "operation": operation,
                    "new_document_id": result["id"],
                    "title": result.get("name"),
                    "document_url": f"https://docs.google.com/document/d/{result['id']}/edit",
                }

            elif operation == "delete_document":
                if not document_id:
                    return {"success": False, "error": "'document_id' is required."}
                drive = self._get_drive_service()
                drive.files().delete(fileId=document_id).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "document_id": document_id,
                    "deleted": True,
                }

            elif operation == "export_document":
                if not document_id or not export_format or not export_path:
                    return {
                        "success": False,
                        "error": "'document_id', 'export_format', and 'export_path' are required.",
                    }
                return self._export_document(document_id, export_format, export_path)

            # ── Reading ──────────────────────────────────────────────── #
            elif operation == "read_content":
                if not document_id:
                    return {"success": False, "error": "'document_id' is required."}
                doc = docs.documents().get(documentId=document_id).execute()
                plain_text = self._extract_plain_text(doc)
                return {
                    "success": True,
                    "operation": operation,
                    "document_id": document_id,
                    "title": doc.get("title"),
                    "text": plain_text,
                    "character_count": len(plain_text),
                }

            elif operation == "get_document_info":
                if not document_id:
                    return {"success": False, "error": "'document_id' is required."}
                doc = docs.documents().get(documentId=document_id).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "document_id": document_id,
                    "title": doc.get("title"),
                    "revision_id": doc.get("revisionId"),
                    "document_style": doc.get("documentStyle"),
                    "named_styles": doc.get("namedStyles"),
                    "inline_objects_count": len(doc.get("inlineObjects", {})),
                    "lists_count": len(doc.get("lists", {})),
                    "document_url": f"https://docs.google.com/document/d/{document_id}/edit",
                }

            # ── Text editing ─────────────────────────────────────────── #
            elif operation == "insert_text":
                if not document_id or text is None or index is None:
                    return {
                        "success": False,
                        "error": "'document_id', 'text', and 'index' are required.",
                    }
                req = {"insertText": {"location": {"index": index}, "text": text}}
                return self._batch(docs, document_id, [req], operation)

            elif operation == "delete_content":
                if not document_id or start_index is None or end_index is None:
                    return {
                        "success": False,
                        "error": "'document_id', 'start_index', and 'end_index' are required.",
                    }
                req = {
                    "deleteContentRange": {
                        "range": {"startIndex": start_index, "endIndex": end_index}
                    }
                }
                return self._batch(docs, document_id, [req], operation)

            elif operation == "replace_text":
                if (
                    not document_id
                    or start_index is None
                    or end_index is None
                    or text is None
                ):
                    return {
                        "success": False,
                        "error": "'document_id', 'start_index', 'end_index', and 'text' are required.",
                    }
                reqs = [
                    {
                        "deleteContentRange": {
                            "range": {"startIndex": start_index, "endIndex": end_index}
                        }
                    },
                    {"insertText": {"location": {"index": start_index}, "text": text}},
                ]
                return self._batch(docs, document_id, reqs, operation)

            elif operation == "find_replace":
                if not document_id or find is None or replacement is None:
                    return {
                        "success": False,
                        "error": "'document_id', 'find', and 'replacement' are required.",
                    }
                req = {
                    "replaceAllText": {
                        "containsText": {"text": find, "matchCase": match_case},
                        "replaceText": replacement,
                    }
                }
                result = self._batch(docs, document_id, [req], operation)
                occurrences = (
                    result.get("replies", [{}])[0]
                    .get("replaceAllText", {})
                    .get("occurrencesChanged", 0)
                    if "replies" in result
                    else 0
                )
                result["occurrences_changed"] = occurrences
                return result

            # ── Structural inserts ───────────────────────────────────── #
            elif operation == "insert_table":
                if not document_id or rows is None or columns is None or index is None:
                    return {
                        "success": False,
                        "error": "'document_id', 'index', 'rows', and 'columns' are required.",
                    }
                req = {
                    "insertTable": {
                        "location": {"index": index},
                        "rows": rows,
                        "columns": columns,
                    }
                }
                return self._batch(docs, document_id, [req], operation)

            elif operation == "insert_image":
                if not document_id or not image_uri or index is None:
                    return {
                        "success": False,
                        "error": "'document_id', 'image_uri', and 'index' are required.",
                    }
                inline_obj: Dict[str, Any] = {"uri": image_uri}
                if image_width and image_height:
                    inline_obj["objectSize"] = {
                        "width": {"magnitude": image_width, "unit": "PT"},
                        "height": {"magnitude": image_height, "unit": "PT"},
                    }
                req = {
                    "insertInlineImage": {
                        "location": {"index": index},
                        "uri": image_uri,
                        **(
                            {"objectSize": inline_obj["objectSize"]}
                            if "objectSize" in inline_obj
                            else {}
                        ),
                    }
                }
                return self._batch(docs, document_id, [req], operation)

            elif operation == "insert_page_break":
                if not document_id or index is None:
                    return {
                        "success": False,
                        "error": "'document_id' and 'index' are required.",
                    }
                req = {"insertPageBreak": {"location": {"index": index}}}
                return self._batch(docs, document_id, [req], operation)

            elif operation == "insert_horizontal_rule":
                if not document_id or index is None:
                    return {
                        "success": False,
                        "error": "'document_id' and 'index' are required.",
                    }
                req = {
                    "insertSectionBreak": {
                        "location": {"index": index},
                        "sectionType": "CONTINUOUS",
                    }
                }
                # Google Docs API doesn't have a direct horizontal rule insert;
                # emulate it by inserting a paragraph with a bottom border instead.
                reqs = [
                    {"insertText": {"location": {"index": index}, "text": "\n"}},
                    {
                        "updateParagraphStyle": {
                            "range": {"startIndex": index, "endIndex": index + 1},
                            "paragraphStyle": {
                                "borderBottom": {
                                    "color": {
                                        "color": {
                                            "rgbColor": {
                                                "red": 0,
                                                "green": 0,
                                                "blue": 0,
                                            }
                                        }
                                    },
                                    "width": {"magnitude": 1, "unit": "PT"},
                                    "padding": {"magnitude": 1, "unit": "PT"},
                                    "dashStyle": "SOLID",
                                }
                            },
                            "fields": "borderBottom",
                        }
                    },
                ]
                return self._batch(docs, document_id, reqs, operation)

            # ── Formatting ───────────────────────────────────────────── #
            elif operation == "apply_named_style":
                if (
                    not document_id
                    or not named_style
                    or start_index is None
                    or end_index is None
                ):
                    return {
                        "success": False,
                        "error": "'document_id', 'named_style', 'start_index', and 'end_index' are required.",
                    }
                req = {
                    "updateParagraphStyle": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                        "paragraphStyle": {"namedStyleType": named_style},
                        "fields": "namedStyleType",
                    }
                }
                return self._batch(docs, document_id, [req], operation)

            elif operation == "apply_paragraph_style":
                if (
                    not document_id
                    or not paragraph_style
                    or start_index is None
                    or end_index is None
                ):
                    return {
                        "success": False,
                        "error": "'document_id', 'paragraph_style', 'start_index', and 'end_index' are required.",
                    }
                fields = self._build_paragraph_style_fields(paragraph_style)
                req = {
                    "updateParagraphStyle": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                        "paragraphStyle": paragraph_style,
                        "fields": fields,
                    }
                }
                return self._batch(docs, document_id, [req], operation)

            elif operation == "apply_text_style":
                if (
                    not document_id
                    or not text_style
                    or start_index is None
                    or end_index is None
                ):
                    return {
                        "success": False,
                        "error": "'document_id', 'text_style', 'start_index', and 'end_index' are required.",
                    }
                fields = self._build_text_style_fields(text_style)
                req = {
                    "updateTextStyle": {
                        "range": {"startIndex": start_index, "endIndex": end_index},
                        "textStyle": text_style,
                        "fields": fields,
                    }
                }
                return self._batch(docs, document_id, [req], operation)

            # ── Header / Footer ──────────────────────────────────────── #
            elif operation == "create_header_footer":
                if not document_id or not header_footer_type:
                    return {
                        "success": False,
                        "error": "'document_id' and 'header_footer_type' are required.",
                    }
                return self._create_header_footer(
                    docs, document_id, header_footer_type, section_type
                )

            elif operation == "insert_text_in_header_footer":
                if not document_id or not header_footer_type or text is None:
                    return {
                        "success": False,
                        "error": "'document_id', 'header_footer_type', and 'text' are required.",
                    }
                return self._insert_text_in_header_footer(
                    docs, document_id, header_footer_type, text
                )

            # ── Batch ────────────────────────────────────────────────── #
            elif operation == "batch_update":
                if not document_id or not requests:
                    return {
                        "success": False,
                        "error": "'document_id' and 'requests' are required.",
                    }
                return self._batch(docs, document_id, requests, operation)

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as e:
            return {"success": False, "error": f"Docs tool error: {str(e)}"}

    # ------------------------------------------------------------------ #
    #  Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _batch(
        self,
        docs,
        document_id: str,
        requests: List[Dict[str, Any]],
        operation: str,
    ) -> Dict[str, Any]:
        """Execute a batchUpdate and return a normalised response."""
        result = (
            docs.documents()
            .batchUpdate(documentId=document_id, body={"requests": requests})
            .execute()
        )
        return {
            "success": True,
            "operation": operation,
            "document_id": document_id,
            "replies": result.get("replies", []),
        }

    def _extract_plain_text(self, doc: Dict[str, Any]) -> str:
        """Walk the document body and extract all text content."""
        text_parts: List[str] = []
        for element in doc.get("body", {}).get("content", []):
            if "paragraph" in element:
                for pe in element["paragraph"].get("elements", []):
                    if "textRun" in pe:
                        text_parts.append(pe["textRun"].get("content", ""))
            elif "table" in element:
                for row in element["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        for ce in cell.get("content", []):
                            if "paragraph" in ce:
                                for pe in ce["paragraph"].get("elements", []):
                                    if "textRun" in pe:
                                        text_parts.append(
                                            pe["textRun"].get("content", "")
                                        )
        return "".join(text_parts)

    def _build_paragraph_style_fields(self, style: Dict[str, Any]) -> str:
        """Return a comma-separated fields mask from a paragraphStyle dict."""
        known = [
            "alignment",
            "lineSpacing",
            "spaceAbove",
            "spaceBelow",
            "indentStart",
            "indentEnd",
            "indentFirstLine",
            "keepLinesTogether",
            "keepWithNext",
            "namedStyleType",
            "borderTop",
            "borderBottom",
            "borderLeft",
            "borderRight",
            "shading",
            "direction",
            "spacingMode",
        ]
        fields = [k for k in known if k in style]
        return ",".join(fields) if fields else "*"

    def _build_text_style_fields(self, style: Dict[str, Any]) -> str:
        """Return a comma-separated fields mask from a textStyle dict."""
        known = [
            "bold",
            "italic",
            "underline",
            "strikethrough",
            "smallCaps",
            "fontSize",
            "foregroundColor",
            "backgroundColor",
            "link",
            "baselineOffset",
            "weightedFontFamily",
        ]
        fields = [k for k in known if k in style]
        return ",".join(fields) if fields else "*"

    def _create_header_footer(
        self,
        docs,
        document_id: str,
        hf_type: str,
        section_type: str,
    ) -> Dict[str, Any]:
        """Create a document header or footer and return its ID."""
        req_key = "createHeader" if hf_type == "header" else "createFooter"
        req = {req_key: {"sectionType": section_type}}
        result = (
            docs.documents()
            .batchUpdate(documentId=document_id, body={"requests": [req]})
            .execute()
        )
        reply_key = "createHeader" if hf_type == "header" else "createFooter"
        hf_id = (
            result["replies"][0]
            .get(reply_key, {})
            .get("headerId" if hf_type == "header" else "footerId")
        )
        return {
            "success": True,
            "operation": "create_header_footer",
            "document_id": document_id,
            f"{hf_type}_id": hf_id,
        }

    def _insert_text_in_header_footer(
        self,
        docs,
        document_id: str,
        hf_type: str,
        text: str,
    ) -> Dict[str, Any]:
        """
        Insert text into the first header or footer found in the document.
        The header/footer must already exist (use create_header_footer first).
        """
        doc = docs.documents().get(documentId=document_id).execute()
        id_key = "headerId" if hf_type == "header" else "footerId"

        # Find the header/footer ID from the document sections
        hf_id: Optional[str] = None
        doc_style = doc.get("documentStyle", {})
        hf_id = doc_style.get(id_key)  # default section header/footer

        if not hf_id:
            return {
                "success": False,
                "error": (f"No {hf_type} found. Use 'create_header_footer' first."),
            }

        # The header/footer body starts at index 1
        req = {
            "insertText": {
                "location": {"index": 1, f"{hf_type}Id": hf_id},
                "text": text,
            }
        }
        result = (
            docs.documents()
            .batchUpdate(documentId=document_id, body={"requests": [req]})
            .execute()
        )
        return {
            "success": True,
            "operation": "insert_text_in_header_footer",
            "document_id": document_id,
            f"{hf_type}_id": hf_id,
            "text_inserted": text,
        }

    def _export_document(
        self,
        document_id: str,
        export_format: str,
        export_path: str,
    ) -> Dict[str, Any]:
        """Export a Google Doc to PDF, DOCX, or plain text and save locally."""
        mime_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "txt": "text/plain",
        }
        mime_type = mime_map.get(export_format)
        if not mime_type:
            return {
                "success": False,
                "error": f"Unsupported export format: {export_format}",
            }

        drive = self._get_drive_service()
        content = drive.files().export(fileId=document_id, mimeType=mime_type).execute()

        with open(export_path, "wb") as f:
            f.write(content)

        return {
            "success": True,
            "operation": "export_document",
            "document_id": document_id,
            "export_format": export_format,
            "export_path": export_path,
            "bytes_written": len(content),
        }
