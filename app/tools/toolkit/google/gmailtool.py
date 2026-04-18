from __future__ import annotations

import base64
import os
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema


class GmailTool(BaseTool):
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "token.json",
    ):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._service = None

    def _get_service(self):
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def _authenticate(self):
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
        return build("gmail", "v1", credentials=creds)

    def get_name(self) -> str:
        return "gmail"

    def get_description(self) -> str:
        return (
            "Gmail operations tool for advanced email management: send, read, list, search, "
            "update, and delete emails; reply to and forward messages; mark emails as read or "
            "unread; manage labels and folders; create, update, and delete drafts; handle "
            "attachments including upload and download; organize conversations and threads; "
            "filter messages by sender, subject, label, or date; and retrieve complete email "
            "message details and metadata."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Gmail operation to perform",
                    required=True,
                    enum=[
                        "send_email",
                        "get_email",
                        "list_emails",
                        "get_unread",
                        "search_emails",
                        "delete_email",
                        "mark_read",
                        "mark_unread",
                        "reply_email",
                        "download_attachments",
                        "list_labels",
                        "create_label",
                        "create_draft",
                        "list_drafts",
                    ],
                ),
                ToolParameter(
                    name="to",
                    type="string",
                    description="Recipient email address",
                    required=False,
                ),
                ToolParameter(
                    name="subject",
                    type="string",
                    description="Email subject",
                    required=False,
                ),
                ToolParameter(
                    name="body",
                    type="string",
                    description="Email body content",
                    required=False,
                ),
                ToolParameter(
                    name="message_id",
                    type="string",
                    description="Gmail message ID",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query for emails",
                    required=False,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum number of results to return",
                    required=False,
                ),
                ToolParameter(
                    name="attachments",
                    type="array",
                    description="List of file paths to attach",
                    required=False,
                ),
                ToolParameter(
                    name="save_folder",
                    type="string",
                    description="Folder to save downloaded attachments",
                    required=False,
                ),
                ToolParameter(
                    name="label_name",
                    type="string",
                    description="Name for creating a label",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["mail.read", "mail.send"],
            risk_level="high",
            cost_tier="low",
            confirmation_policy="confirm",
            readonly=False,
        )

    async def execute(
        self,
        operation: str,
        to: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        message_id: str | None = None,
        query: str | None = None,
        max_results: int = 10,
        attachments: List[str] | None = None,
        save_folder: str = "attachments",
        label_name: str | None = None,
        **_: Any,
    ) -> Dict[str, Any]:
        try:
            service = self._get_service()

            if operation == "send_email":
                if not to or not subject or not body:
                    return {
                        "success": False,
                        "error": "to, subject, and body are required",
                    }
                result = self._send_email(service, to, subject, body, attachments or [])
                return {"success": True, "operation": operation, "result": result}

            elif operation == "get_email":
                if not message_id:
                    return {"success": False, "error": "message_id is required"}
                result = self._get_email(service, message_id)
                return {
                    "success": True,
                    "operation": operation,
                    "message_id": message_id,
                    "email": result,
                }

            elif operation == "list_emails":
                result = self._list_emails(service, query, max_results)
                return {
                    "success": True,
                    "operation": operation,
                    "query": query,
                    "messages": result,
                    "count": len(result),
                }

            elif operation == "get_unread":
                result = self._list_emails(service, "is:unread", max_results)
                return {
                    "success": True,
                    "operation": operation,
                    "messages": result,
                    "count": len(result),
                }

            elif operation == "search_emails":
                if not query:
                    return {"success": False, "error": "query is required"}
                result = self._list_emails(service, query, max_results)
                return {
                    "success": True,
                    "operation": operation,
                    "query": query,
                    "messages": result,
                    "count": len(result),
                }

            elif operation == "delete_email":
                if not message_id:
                    return {"success": False, "error": "message_id is required"}
                self._delete_email(service, message_id)
                return {
                    "success": True,
                    "operation": operation,
                    "message_id": message_id,
                    "deleted": True,
                }

            elif operation == "mark_read":
                if not message_id:
                    return {"success": False, "error": "message_id is required"}
                self._modify_labels(service, message_id, remove_labels=["UNREAD"])
                return {
                    "success": True,
                    "operation": operation,
                    "message_id": message_id,
                    "marked_read": True,
                }

            elif operation == "mark_unread":
                if not message_id:
                    return {"success": False, "error": "message_id is required"}
                self._modify_labels(service, message_id, add_labels=["UNREAD"])
                return {
                    "success": True,
                    "operation": operation,
                    "message_id": message_id,
                    "marked_unread": True,
                }

            elif operation == "reply_email":
                if not message_id or not body:
                    return {
                        "success": False,
                        "error": "message_id and body are required",
                    }
                result = self._reply_email(service, message_id, body)
                return {
                    "success": True,
                    "operation": operation,
                    "message_id": message_id,
                    "result": result,
                }

            elif operation == "download_attachments":
                if not message_id:
                    return {"success": False, "error": "message_id is required"}
                files = self._download_attachments(service, message_id, save_folder)
                return {
                    "success": True,
                    "operation": operation,
                    "message_id": message_id,
                    "files": files,
                    "count": len(files),
                }

            elif operation == "list_labels":
                result = self._list_labels(service)
                return {
                    "success": True,
                    "operation": operation,
                    "labels": result.get("labels", []),
                }

            elif operation == "create_label":
                if not label_name:
                    return {"success": False, "error": "label_name is required"}
                result = self._create_label(service, label_name)
                return {
                    "success": True,
                    "operation": operation,
                    "label": result,
                }

            elif operation == "create_draft":
                if not to or not subject or not body:
                    return {
                        "success": False,
                        "error": "to, subject, and body are required",
                    }
                result = self._create_draft(service, to, subject, body)
                return {
                    "success": True,
                    "operation": operation,
                    "draft": result,
                }

            elif operation == "list_drafts":
                result = self._list_drafts(service)
                return {
                    "success": True,
                    "operation": operation,
                    "drafts": result.get("drafts", []),
                }

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as e:
            return {"success": False, "error": f"Gmail tool error: {str(e)}"}

    def _send_email(
        self, service, to: str, subject: str, body: str, attachments: List[str]
    ):
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        message.attach(MIMEText(body, "plain"))

        for file_path in attachments:
            if os.path.exists(file_path):
                part = MIMEBase("application", "octet-stream")
                with open(file_path, "rb") as f:
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename={os.path.basename(file_path)}",
                )
                message.attach(part)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return service.users().messages().send(userId="me", body={"raw": raw}).execute()

    def _get_email(self, service, message_id: str):
        return (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

    def _list_emails(self, service, query: str | None, max_results: int):
        result = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return result.get("messages", [])

    def _delete_email(self, service, message_id: str):
        service.users().messages().delete(userId="me", id=message_id).execute()

    def _modify_labels(
        self,
        service,
        message_id: str,
        add_labels: List[str] | None = None,
        remove_labels: List[str] | None = None,
    ):
        body = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels
        service.users().messages().modify(
            userId="me", id=message_id, body=body
        ).execute()

    def _reply_email(self, service, message_id: str, body: str):
        message = self._get_email(service, message_id)
        headers = message["payload"]["headers"]
        subject = ""
        to = ""
        for h in headers:
            if h["name"] == "Subject":
                subject = h["value"]
            if h["name"] == "From":
                to = h["value"]

        reply = MIMEText(body)
        reply["to"] = to
        reply["subject"] = "Re: " + subject
        raw = base64.urlsafe_b64encode(reply.as_bytes()).decode()
        return service.users().messages().send(userId="me", body={"raw": raw}).execute()

    def _download_attachments(
        self, service, message_id: str, save_folder: str
    ) -> List[str]:
        os.makedirs(save_folder, exist_ok=True)
        message = self._get_email(service, message_id)
        parts = message["payload"].get("parts", [])
        files = []

        for part in parts:
            filename = part.get("filename")
            if filename:
                attachment_id = part["body"]["attachmentId"]
                attachment = (
                    service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=message_id, id=attachment_id)
                    .execute()
                )
                data = base64.urlsafe_b64decode(attachment["data"])
                path = os.path.join(save_folder, filename)
                with open(path, "wb") as f:
                    f.write(data)
                files.append(path)

        return files

    def _list_labels(self, service):
        return service.users().labels().list(userId="me").execute()

    def _create_label(self, service, name: str):
        body = {
            "name": name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        return service.users().labels().create(userId="me", body=body).execute()

    def _create_draft(self, service, to: str, subject: str, body: str):
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )

    def _list_drafts(self, service):
        return service.users().drafts().list(userId="me").execute()
