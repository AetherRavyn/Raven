"""Google Drive Tool — List, upload, download, search files and create folders.

Agents use this to manage files on Google Drive.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class DriveTool(BaseTool):
    """Manage files and folders on Google Drive.

    Uses OAuth 2.0 with credentials.json for authentication.
    """

    SCOPES = [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ]

    group = "productivity"

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "drive_token.json",
    ):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._service = None

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
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, self.SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self.token_file, "w") as token:
                token.write(creds.to_json())
        return creds

    def _get_service(self):
        if self._service is None:
            creds = self._get_credentials()
            self._service = build("drive", "v3", credentials=creds)
        return self._service

    def _check_config(self) -> dict[str, Any] | None:
        if not os.path.exists(self.credentials_file):
            return {
                "success": False,
                "error": (
                    "Google API is not configured. "
                    f"Credentials file '{self.credentials_file}' not found. "
                    "Place your OAuth client secrets JSON at that path."
                ),
            }
        return None

    # ------------------------------------------------------------------ #
    #  Tool metadata                                                        #
    # ------------------------------------------------------------------ #

    def get_name(self) -> str:
        return "google_drive"

    def get_description(self) -> str:
        return (
            "Google Drive file management tool. "
            "Actions: 'list_files' (list files in a folder), "
            "'upload_file' (upload a local file to Drive), "
            "'download_file' (download a file from Drive by ID), "
            "'search' (search files by name or content), "
            "'create_folder' (create a new folder). "
            "Requires Google API OAuth credentials (credentials.json)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: list_files, upload_file, download_file, search, create_folder",
                    required=True,
                    enum=["list_files", "upload_file", "download_file", "search", "create_folder"],
                ),
                ToolParameter(
                    name="folder_id",
                    type="string",
                    description="Folder ID (for list_files, upload_file). Use 'root' for My Drive root.",
                    required=False,
                ),
                ToolParameter(
                    name="page_size",
                    type="integer",
                    description="Max results per page (default 20)",
                    required=False,
                ),
                ToolParameter(
                    name="local_path",
                    type="string",
                    description="Local file path (required for upload_file, download_file)",
                    required=False,
                ),
                ToolParameter(
                    name="mime_type",
                    type="string",
                    description="MIME type of the file being uploaded (upload_file)",
                    required=False,
                ),
                ToolParameter(
                    name="parent_folder_id",
                    type="string",
                    description="Parent folder ID for upload (upload_file)",
                    required=False,
                ),
                ToolParameter(
                    name="file_id",
                    type="string",
                    description="Drive file ID (required for download_file)",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query string (required for search action)",
                    required=False,
                ),
                ToolParameter(
                    name="name",
                    type="string",
                    description="Folder name (required for create_folder)",
                    required=False,
                ),
            ],
        )

    # ------------------------------------------------------------------ #
    #  Entry point                                                          #
    # ------------------------------------------------------------------ #

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        config_err = self._check_config()
        if config_err:
            return config_err

        action = kwargs.get("action")

        try:
            if action == "list_files":
                return await self._list_files(kwargs)
            elif action == "upload_file":
                return await self._upload_file(kwargs)
            elif action == "download_file":
                return await self._download_file(kwargs)
            elif action == "search":
                return await self._search(kwargs)
            elif action == "create_folder":
                return await self._create_folder(kwargs)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("Drive tool failed")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Actions                                                              #
    # ------------------------------------------------------------------ #

    async def _list_files(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        folder_id = kwargs.get("folder_id")
        page_size = min(int(kwargs.get("page_size", 20)), 100)

        q = f"'{folder_id}' in parents and trashed = false" if folder_id else "trashed = false"

        service = self._get_service()
        results = (
            service.files()
            .list(
                q=q,
                pageSize=page_size,
                fields="files(id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )
        files = results.get("files", [])
        return {
            "success": True,
            "action": "list_files",
            "files": files,
            "total": len(files),
        }

    async def _upload_file(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        local_path = kwargs.get("local_path")
        if not local_path:
            return {"success": False, "error": "'local_path' is required for upload_file"}
        if not os.path.exists(local_path):
            return {"success": False, "error": f"File not found: {local_path}"}

        file_name = os.path.basename(local_path)
        mime_type = kwargs.get("mime_type", "application/octet-stream")
        parent_id = kwargs.get("parent_folder_id")

        body: dict[str, Any] = {"name": file_name}
        if parent_id:
            body["parents"] = [parent_id]

        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
        service = self._get_service()
        uploaded = (
            service.files()
            .create(body=body, media_body=media, fields="id, name, mimeType, size, webViewLink")
            .execute()
        )
        return {
            "success": True,
            "action": "upload_file",
            "file": uploaded,
        }

    async def _download_file(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        file_id = kwargs.get("file_id")
        if not file_id:
            return {"success": False, "error": "'file_id' is required for download_file"}
        local_path = kwargs.get("local_path")
        if not local_path:
            return {"success": False, "error": "'local_path' is required for download_file"}

        service = self._get_service()
        request = service.files().get_media(fileId=file_id)

        os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)
        with open(local_path, "wb") as f:
            downloader = request.execute()
            f.write(downloader)

        return {
            "success": True,
            "action": "download_file",
            "file_id": file_id,
            "saved_to": local_path,
        }

    async def _search(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        query_text = kwargs.get("query")
        if not query_text:
            return {"success": False, "error": "'query' is required for search"}

        q = f"name contains '{query_text}' and trashed = false"
        service = self._get_service()
        results = (
            service.files()
            .list(
                q=q,
                pageSize=20,
                fields="files(id, name, mimeType, size, createdTime, modifiedTime, parents, webViewLink)",
            )
            .execute()
        )
        files = results.get("files", [])
        return {
            "success": True,
            "action": "search",
            "query": query_text,
            "files": files,
            "total": len(files),
        }

    async def _create_folder(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        name = kwargs.get("name")
        if not name:
            return {"success": False, "error": "'name' is required for create_folder"}

        parent_id = kwargs.get("folder_id")
        body: dict[str, Any] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            body["parents"] = [parent_id]

        service = self._get_service()
        folder = (
            service.files()
            .create(body=body, fields="id, name, mimeType, webViewLink, createdTime")
            .execute()
        )
        return {
            "success": True,
            "action": "create_folder",
            "folder": folder,
        }
