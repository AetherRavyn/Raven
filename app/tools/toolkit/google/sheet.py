from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class GoogleSheetsTool(BaseTool):
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",  # needed for create/copy/delete
    ]

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "sheets_token.json",
    ):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._sheets_service = None
        self._drive_service = None

    # ------------------------------------------------------------------ #
    #  Auth / service                                                       #
    # ------------------------------------------------------------------ #

    def _get_sheets_service(self):
        if self._sheets_service is None:
            creds = self._get_credentials()
            self._sheets_service = build("sheets", "v4", credentials=creds)
        return self._sheets_service

    def _get_drive_service(self):
        if self._drive_service is None:
            creds = self._get_credentials()
            self._drive_service = build("drive", "v3", credentials=creds)
        return self._drive_service

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

    # ------------------------------------------------------------------ #
    #  Tool metadata                                                        #
    # ------------------------------------------------------------------ #

    def get_name(self) -> str:
        return "google_sheets"

    def get_description(self) -> str:
        return (
            "Google Sheets management tool. Supports: creating and deleting spreadsheets, "
            "reading/writing/appending/clearing cell ranges, batch reads and writes, "
            "adding/deleting/renaming/duplicating/reordering sheets, formatting cells, "
            "sorting and filtering data, finding and replacing values, copying spreadsheets, "
            "and reading spreadsheet metadata."
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
                    description="Sheets operation to perform.",
                    required=True,
                    enum=[
                        # Spreadsheet-level
                        "create_spreadsheet",
                        "get_spreadsheet_info",
                        "copy_spreadsheet",
                        "delete_spreadsheet",
                        # Sheet (tab) management
                        "add_sheet",
                        "delete_sheet",
                        "rename_sheet",
                        "duplicate_sheet",
                        "reorder_sheets",
                        # Data I/O
                        "read_range",
                        "write_range",
                        "append_rows",
                        "clear_range",
                        "batch_read",
                        "batch_write",
                        # Data manipulation
                        "find_replace",
                        "sort_range",
                        "copy_range",
                        # Formatting
                        "format_cells",
                        "auto_resize_columns",
                        # Metadata
                        "list_named_ranges",
                    ],
                ),
                # ── Identifiers ────────────────────────────────────────── #
                ToolParameter(
                    name="spreadsheet_id",
                    type="string",
                    description="ID of the spreadsheet (from its URL).",
                    required=False,
                ),
                ToolParameter(
                    name="sheet_id",
                    type="integer",
                    description="Numeric ID of the sheet tab (used for structural operations).",
                    required=False,
                ),
                ToolParameter(
                    name="sheet_name",
                    type="string",
                    description="Name of the sheet tab.",
                    required=False,
                ),
                ToolParameter(
                    name="destination_spreadsheet_id",
                    type="string",
                    description="Target spreadsheet ID for copy_range.",
                    required=False,
                ),
                # ── Spreadsheet creation ───────────────────────────────── #
                ToolParameter(
                    name="title",
                    type="string",
                    description="Title for a new spreadsheet or sheet tab.",
                    required=False,
                ),
                ToolParameter(
                    name="new_title",
                    type="string",
                    description="New title when renaming a sheet.",
                    required=False,
                ),
                # ── Range / data ───────────────────────────────────────── #
                ToolParameter(
                    name="range",
                    type="string",
                    description=(
                        "A1 notation range, optionally prefixed with a sheet name "
                        "(e.g. 'Sheet1!A1:D10' or 'A1:D10')."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="ranges",
                    type="array",
                    description="List of A1 notation ranges for batch_read or batch_write.",
                    required=False,
                ),
                ToolParameter(
                    name="values",
                    type="array",
                    description=(
                        "2-D array of values to write. Each inner list is one row "
                        "(e.g. [['Name', 'Age'], ['Alice', 30]])."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="batch_data",
                    type="array",
                    description=(
                        "List of {range, values} dicts for batch_write "
                        "(e.g. [{'range': 'A1', 'values': [['x']]}, ...])."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="value_input_option",
                    type="string",
                    description=(
                        "How input data should be interpreted: "
                        "'RAW' (literal) or 'USER_ENTERED' (parse formulas/dates). "
                        "Defaults to 'USER_ENTERED'."
                    ),
                    required=False,
                    enum=["RAW", "USER_ENTERED"],
                ),
                ToolParameter(
                    name="value_render_option",
                    type="string",
                    description=(
                        "How values are rendered in output: "
                        "'FORMATTED_VALUE' (display string), "
                        "'UNFORMATTED_VALUE' (raw number/bool), "
                        "'FORMULA'. Defaults to 'FORMATTED_VALUE'."
                    ),
                    required=False,
                    enum=["FORMATTED_VALUE", "UNFORMATTED_VALUE", "FORMULA"],
                ),
                ToolParameter(
                    name="major_dimension",
                    type="string",
                    description="Whether data is row-major ('ROWS') or column-major ('COLUMNS'). Defaults to 'ROWS'.",
                    required=False,
                    enum=["ROWS", "COLUMNS"],
                ),
                # ── Find & Replace ─────────────────────────────────────── #
                ToolParameter(
                    name="find",
                    type="string",
                    description="Text to search for in find_replace.",
                    required=False,
                ),
                ToolParameter(
                    name="replacement",
                    type="string",
                    description="Replacement text for find_replace.",
                    required=False,
                ),
                ToolParameter(
                    name="match_case",
                    type="boolean",
                    description="Case-sensitive find_replace (default: false).",
                    required=False,
                ),
                ToolParameter(
                    name="match_entire_cell",
                    type="boolean",
                    description="Match the entire cell content only (default: false).",
                    required=False,
                ),
                ToolParameter(
                    name="search_by_regex",
                    type="boolean",
                    description="Treat 'find' as a regular expression (default: false).",
                    required=False,
                ),
                # ── Sort ───────────────────────────────────────────────── #
                ToolParameter(
                    name="sort_specs",
                    type="array",
                    description=(
                        "List of sort specs for sort_range. "
                        "Each item: {'column_index': 0, 'ascending': true}."
                    ),
                    required=False,
                ),
                # ── Formatting ─────────────────────────────────────────── #
                ToolParameter(
                    name="format",
                    type="object",
                    description=(
                        "CellFormat object for format_cells. Supports keys: "
                        "backgroundColor ({red,green,blue}), "
                        "textFormat ({bold, italic, underline, strikethrough, fontSize, foregroundColor}), "
                        "horizontalAlignment ('LEFT'|'CENTER'|'RIGHT'), "
                        "verticalAlignment ('TOP'|'MIDDLE'|'BOTTOM'), "
                        "wrapStrategy ('OVERFLOW_CELL'|'WRAP'|'CLIP'), "
                        "numberFormat ({type, pattern})."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="column_indices",
                    type="array",
                    description="0-based column indices to auto-resize in auto_resize_columns.",
                    required=False,
                ),
                # ── Sheet ordering ─────────────────────────────────────── #
                ToolParameter(
                    name="sheet_order",
                    type="array",
                    description="Ordered list of sheet IDs (integers) for reorder_sheets.",
                    required=False,
                ),
                # ── Duplicate sheet ────────────────────────────────────── #
                ToolParameter(
                    name="insert_sheet_index",
                    type="integer",
                    description="Position at which to insert the duplicated sheet (0-based).",
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
        spreadsheet_id: Optional[str] = None,
        sheet_id: Optional[int] = None,
        sheet_name: Optional[str] = None,
        destination_spreadsheet_id: Optional[str] = None,
        title: Optional[str] = None,
        new_title: Optional[str] = None,
        range: Optional[str] = None,
        ranges: Optional[List[str]] = None,
        values: Optional[List[List[Any]]] = None,
        batch_data: Optional[List[Dict[str, Any]]] = None,
        value_input_option: str = "USER_ENTERED",
        value_render_option: str = "FORMATTED_VALUE",
        major_dimension: str = "ROWS",
        find: Optional[str] = None,
        replacement: Optional[str] = None,
        match_case: bool = False,
        match_entire_cell: bool = False,
        search_by_regex: bool = False,
        sort_specs: Optional[List[Dict[str, Any]]] = None,
        format: Optional[Dict[str, Any]] = None,
        column_indices: Optional[List[int]] = None,
        sheet_order: Optional[List[int]] = None,
        insert_sheet_index: Optional[int] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        try:
            sheets = self._get_sheets_service()
            ss = sheets.spreadsheets()

            # ── Spreadsheet level ────────────────────────────────────── #
            if operation == "create_spreadsheet":
                if not title:
                    return {"success": False, "error": "'title' is required."}
                return self._create_spreadsheet(sheets, title)

            elif operation == "get_spreadsheet_info":
                if not spreadsheet_id:
                    return {"success": False, "error": "'spreadsheet_id' is required."}
                info = ss.get(spreadsheetId=spreadsheet_id).execute()
                return {"success": True, "operation": operation, "spreadsheet": info}

            elif operation == "copy_spreadsheet":
                if not spreadsheet_id or not title:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id' and 'title' are required.",
                    }
                drive = self._get_drive_service()
                result = (
                    drive.files()
                    .copy(
                        fileId=spreadsheet_id,
                        body={"name": title},
                    )
                    .execute()
                )
                return {
                    "success": True,
                    "operation": operation,
                    "new_spreadsheet": result,
                }

            elif operation == "delete_spreadsheet":
                if not spreadsheet_id:
                    return {"success": False, "error": "'spreadsheet_id' is required."}
                drive = self._get_drive_service()
                drive.files().delete(fileId=spreadsheet_id).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "spreadsheet_id": spreadsheet_id,
                    "deleted": True,
                }

            # ── Sheet (tab) management ───────────────────────────────── #
            elif operation == "add_sheet":
                if not spreadsheet_id or not title:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id' and 'title' are required.",
                    }
                req = {"addSheet": {"properties": {"title": title}}}
                result = ss.batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": [req]}
                ).execute()
                new_sheet = result["replies"][0]["addSheet"]["properties"]
                return {"success": True, "operation": operation, "sheet": new_sheet}

            elif operation == "delete_sheet":
                if not spreadsheet_id or sheet_id is None:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id' and 'sheet_id' are required.",
                    }
                req = {"deleteSheet": {"sheetId": sheet_id}}
                ss.batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": [req]}
                ).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "sheet_id": sheet_id,
                    "deleted": True,
                }

            elif operation == "rename_sheet":
                if not spreadsheet_id or sheet_id is None or not new_title:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id', 'sheet_id', and 'new_title' are required.",
                    }
                req = {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "title": new_title},
                        "fields": "title",
                    }
                }
                ss.batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": [req]}
                ).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "sheet_id": sheet_id,
                    "new_title": new_title,
                }

            elif operation == "duplicate_sheet":
                if not spreadsheet_id or sheet_id is None:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id' and 'sheet_id' are required.",
                    }
                req_body: Dict[str, Any] = {
                    "duplicateSheet": {
                        "sourceSheetId": sheet_id,
                        "newSheetName": new_title or None,
                    }
                }
                if insert_sheet_index is not None:
                    req_body["duplicateSheet"]["insertSheetIndex"] = insert_sheet_index
                result = ss.batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": [req_body]}
                ).execute()
                dup_sheet = result["replies"][0]["duplicateSheet"]["properties"]
                return {"success": True, "operation": operation, "sheet": dup_sheet}

            elif operation == "reorder_sheets":
                if not spreadsheet_id or not sheet_order:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id' and 'sheet_order' are required.",
                    }
                requests = [
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": sid, "index": idx},
                            "fields": "index",
                        }
                    }
                    for idx, sid in enumerate(sheet_order)
                ]
                ss.batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": requests}
                ).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "new_order": sheet_order,
                }

            # ── Data I/O ─────────────────────────────────────────────── #
            elif operation == "read_range":
                if not spreadsheet_id or not range:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id' and 'range' are required.",
                    }
                result = (
                    ss.values()
                    .get(
                        spreadsheetId=spreadsheet_id,
                        range=range,
                        valueRenderOption=value_render_option,
                        majorDimension=major_dimension,
                    )
                    .execute()
                )
                rows = result.get("values", [])
                return {
                    "success": True,
                    "operation": operation,
                    "range": result.get("range"),
                    "values": rows,
                    "row_count": len(rows),
                }

            elif operation == "write_range":
                if not spreadsheet_id or not range or values is None:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id', 'range', and 'values' are required.",
                    }
                result = (
                    ss.values()
                    .update(
                        spreadsheetId=spreadsheet_id,
                        range=range,
                        valueInputOption=value_input_option,
                        body={"majorDimension": major_dimension, "values": values},
                    )
                    .execute()
                )
                return {
                    "success": True,
                    "operation": operation,
                    "updated_range": result.get("updatedRange"),
                    "updated_rows": result.get("updatedRows"),
                    "updated_columns": result.get("updatedColumns"),
                    "updated_cells": result.get("updatedCells"),
                }

            elif operation == "append_rows":
                if not spreadsheet_id or not range or values is None:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id', 'range', and 'values' are required.",
                    }
                result = (
                    ss.values()
                    .append(
                        spreadsheetId=spreadsheet_id,
                        range=range,
                        valueInputOption=value_input_option,
                        insertDataOption="INSERT_ROWS",
                        body={"majorDimension": major_dimension, "values": values},
                    )
                    .execute()
                )
                updates = result.get("updates", {})
                return {
                    "success": True,
                    "operation": operation,
                    "updated_range": updates.get("updatedRange"),
                    "updated_rows": updates.get("updatedRows"),
                    "updated_cells": updates.get("updatedCells"),
                }

            elif operation == "clear_range":
                if not spreadsheet_id or not range:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id' and 'range' are required.",
                    }
                result = (
                    ss.values()
                    .clear(spreadsheetId=spreadsheet_id, range=range, body={})
                    .execute()
                )
                return {
                    "success": True,
                    "operation": operation,
                    "cleared_range": result.get("clearedRange"),
                }

            elif operation == "batch_read":
                if not spreadsheet_id or not ranges:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id' and 'ranges' are required.",
                    }
                result = (
                    ss.values()
                    .batchGet(
                        spreadsheetId=spreadsheet_id,
                        ranges=ranges,
                        valueRenderOption=value_render_option,
                        majorDimension=major_dimension,
                    )
                    .execute()
                )
                return {
                    "success": True,
                    "operation": operation,
                    "value_ranges": result.get("valueRanges", []),
                }

            elif operation == "batch_write":
                if not spreadsheet_id or not batch_data:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id' and 'batch_data' are required.",
                    }
                data = [
                    {
                        "range": item["range"],
                        "majorDimension": major_dimension,
                        "values": item["values"],
                    }
                    for item in batch_data
                ]
                result = (
                    ss.values()
                    .batchUpdate(
                        spreadsheetId=spreadsheet_id,
                        body={"valueInputOption": value_input_option, "data": data},
                    )
                    .execute()
                )
                return {
                    "success": True,
                    "operation": operation,
                    "total_updated_cells": result.get("totalUpdatedCells"),
                    "total_updated_rows": result.get("totalUpdatedRows"),
                    "responses": result.get("responses", []),
                }

            # ── Data manipulation ────────────────────────────────────── #
            elif operation == "find_replace":
                if not spreadsheet_id or find is None or replacement is None:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id', 'find', and 'replacement' are required.",
                    }
                find_body: Dict[str, Any] = {
                    "find": find,
                    "replacement": replacement,
                    "matchCase": match_case,
                    "matchEntireCell": match_entire_cell,
                    "searchByRegex": search_by_regex,
                    "allSheets": sheet_id is None,
                }
                if sheet_id is not None:
                    find_body["sheetId"] = sheet_id
                req = {"findReplace": find_body}
                result = ss.batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": [req]}
                ).execute()
                fr = result["replies"][0].get("findReplace", {})
                return {
                    "success": True,
                    "operation": operation,
                    "occurrences_changed": fr.get("occurrencesChanged", 0),
                }

            elif operation == "sort_range":
                if not spreadsheet_id or not range or not sort_specs:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id', 'range', and 'sort_specs' are required.",
                    }
                grid_range = self._a1_to_grid_range(
                    spreadsheet_id, range, sheet_id, sheets
                )
                sort_requests = [
                    {
                        "sortSpec": {
                            "dimensionIndex": s["column_index"],
                            "sortOrder": "ASCENDING"
                            if s.get("ascending", True)
                            else "DESCENDING",
                        }
                    }
                    for s in sort_specs
                ]
                req = {
                    "sortRange": {
                        "range": grid_range,
                        "sortSpecs": [s["sortSpec"] for s in sort_requests],
                    }
                }
                ss.batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": [req]}
                ).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "range": range,
                    "sorted": True,
                }

            elif operation == "copy_range":
                if not spreadsheet_id or not range or not destination_spreadsheet_id:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id', 'range', and 'destination_spreadsheet_id' are required.",
                    }
                result = (
                    ss.values()
                    .get(
                        spreadsheetId=spreadsheet_id,
                        range=range,
                        valueRenderOption="UNFORMATTED_VALUE",
                    )
                    .execute()
                )
                rows = result.get("values", [])
                dest_range = (
                    new_title or range
                )  # reuse new_title as destination range if provided
                ss.values().update(
                    spreadsheetId=destination_spreadsheet_id,
                    range=dest_range,
                    valueInputOption="USER_ENTERED",
                    body={"values": rows},
                ).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "rows_copied": len(rows),
                    "destination_spreadsheet_id": destination_spreadsheet_id,
                    "destination_range": dest_range,
                }

            # ── Formatting ───────────────────────────────────────────── #
            elif operation == "format_cells":
                if not spreadsheet_id or not range or not format:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id', 'range', and 'format' are required.",
                    }
                grid_range = self._a1_to_grid_range(
                    spreadsheet_id, range, sheet_id, sheets
                )
                # Build fields mask from provided format keys
                fields = self._build_format_fields(format)
                req = {
                    "repeatCell": {
                        "range": grid_range,
                        "cell": {"userEnteredFormat": format},
                        "fields": f"userEnteredFormat({fields})",
                    }
                }
                ss.batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": [req]}
                ).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "range": range,
                    "formatted": True,
                }

            elif operation == "auto_resize_columns":
                if not spreadsheet_id or sheet_id is None or not column_indices:
                    return {
                        "success": False,
                        "error": "'spreadsheet_id', 'sheet_id', and 'column_indices' are required.",
                    }
                requests = [
                    {
                        "autoResizeDimensions": {
                            "dimensions": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": col,
                                "endIndex": col + 1,
                            }
                        }
                    }
                    for col in column_indices
                ]
                ss.batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": requests}
                ).execute()
                return {
                    "success": True,
                    "operation": operation,
                    "sheet_id": sheet_id,
                    "columns_resized": column_indices,
                }

            # ── Metadata ─────────────────────────────────────────────── #
            elif operation == "list_named_ranges":
                if not spreadsheet_id:
                    return {"success": False, "error": "'spreadsheet_id' is required."}
                info = ss.get(spreadsheetId=spreadsheet_id).execute()
                named_ranges = info.get("namedRanges", [])
                sheets_list = [
                    {
                        "sheet_id": s["properties"]["sheetId"],
                        "title": s["properties"]["title"],
                    }
                    for s in info.get("sheets", [])
                ]
                return {
                    "success": True,
                    "operation": operation,
                    "spreadsheet_id": spreadsheet_id,
                    "title": info.get("properties", {}).get("title"),
                    "sheets": sheets_list,
                    "named_ranges": named_ranges,
                }

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as e:
            return {"success": False, "error": f"Sheets tool error: {str(e)}"}

    # ------------------------------------------------------------------ #
    #  Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _create_spreadsheet(self, sheets_service, title: str) -> Dict[str, Any]:
        body = {
            "properties": {"title": title},
            "sheets": [{"properties": {"title": "Sheet1"}}],
        }
        result = sheets_service.spreadsheets().create(body=body).execute()
        return {
            "success": True,
            "operation": "create_spreadsheet",
            "spreadsheet_id": result["spreadsheetId"],
            "spreadsheet_url": result["spreadsheetUrl"],
            "title": result["properties"]["title"],
        }

    def _a1_to_grid_range(
        self,
        spreadsheet_id: str,
        a1_range: str,
        sheet_id: Optional[int],
        sheets_service,
    ) -> Dict[str, Any]:
        """
        Convert an A1-notation range to a GridRange dict.
        Resolves the sheetId from the sheet name embedded in the range if needed.
        """
        sheet_part = None
        cell_part = a1_range

        if "!" in a1_range:
            sheet_part, cell_part = a1_range.split("!", 1)
            sheet_part = sheet_part.strip("'")

        resolved_sheet_id = sheet_id
        if resolved_sheet_id is None and sheet_part:
            info = (
                sheets_service.spreadsheets()
                .get(spreadsheetId=spreadsheet_id)
                .execute()
            )
            for s in info.get("sheets", []):
                if s["properties"]["title"] == sheet_part:
                    resolved_sheet_id = s["properties"]["sheetId"]
                    break

        grid: Dict[str, Any] = {}
        if resolved_sheet_id is not None:
            grid["sheetId"] = resolved_sheet_id

        # Parse start/end columns and rows from cell_part (e.g. "B2:D10")
        if ":" in cell_part:
            start_cell, end_cell = cell_part.split(":", 1)
        else:
            start_cell = end_cell = cell_part

        def parse_cell(cell: str):
            col_str = "".join(c for c in cell if c.isalpha()).upper()
            row_str = "".join(c for c in cell if c.isdigit())
            col_idx = 0
            for ch in col_str:
                col_idx = col_idx * 26 + (ord(ch) - ord("A") + 1)
            return col_idx - 1, int(row_str) - 1 if row_str else None

        sc, sr = parse_cell(start_cell)
        ec, er = parse_cell(end_cell)
        grid["startColumnIndex"] = sc
        grid["endColumnIndex"] = ec + 1
        if sr is not None:
            grid["startRowIndex"] = sr
        if er is not None:
            grid["endRowIndex"] = er + 1

        return grid

    def _build_format_fields(self, format_dict: Dict[str, Any]) -> str:
        """Return a comma-separated field mask for the provided format keys."""
        keys = []
        if "backgroundColor" in format_dict:
            keys.append("backgroundColor")
        if "textFormat" in format_dict:
            keys.append("textFormat")
        if "horizontalAlignment" in format_dict:
            keys.append("horizontalAlignment")
        if "verticalAlignment" in format_dict:
            keys.append("verticalAlignment")
        if "wrapStrategy" in format_dict:
            keys.append("wrapStrategy")
        if "numberFormat" in format_dict:
            keys.append("numberFormat")
        return ",".join(keys) if keys else "*"
