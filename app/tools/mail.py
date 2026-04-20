# app/tools/mail.py
"""MailTool — Send and read email via SMTP / Gmail OAuth.

Operations:
  send_email  — compose and send via SMTP
  read_inbox  — fetch recent inbox messages via Gmail API (OAuth)
  search_email — search inbox by keyword via Gmail API
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema
from app.settings.config import Config

logger = logging.getLogger(__name__)


class MailTool(BaseTool):
    group = "communication"

    def get_name(self) -> str:
        return "email_ops"

    def get_description(self) -> str:
        return (
            "Email operations: send_email (via SMTP), read_inbox (recent Gmail inbox), "
            "search_email (keyword search in Gmail). Requires SMTP or Gmail OAuth credentials."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="send_email | read_inbox | search_email",
                    required=True,
                    enum=["send_email", "read_inbox", "search_email"],
                ),
                ToolParameter(
                    name="to",
                    type="string",
                    description="Recipient email address (for send_email)",
                    required=False,
                ),
                ToolParameter(
                    name="subject",
                    type="string",
                    description="Email subject line (for send_email)",
                    required=False,
                ),
                ToolParameter(
                    name="body",
                    type="string",
                    description="Email body text (for send_email)",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query (for search_email), e.g. 'from:boss subject:meeting'",
                    required=False,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum number of emails to return (default: 10)",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["email"],
            risk_level="medium",
            cost_tier="low",
            confirmation_policy="send_only",
            readonly=False,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation", "read_inbox")

        if operation == "send_email":
            return await self._send_email(
                to=kwargs.get("to", ""),
                subject=kwargs.get("subject", ""),
                body=kwargs.get("body", ""),
            )
        elif operation == "read_inbox":
            max_results = int(kwargs.get("max_results", 10))
            return await self._read_inbox(max_results=max_results)
        elif operation == "search_email":
            query = kwargs.get("query", "")
            max_results = int(kwargs.get("max_results", 10))
            return await self._search_email(query=query, max_results=max_results)
        else:
            return {"success": False, "error": f"Unknown operation: {operation}"}

    # ── SMTP Send ──────────────────────────────────────────────────────

    async def _send_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Send an email via SMTP using Config credentials."""
        if not to:
            return {"success": False, "error": "Recipient 'to' address is required"}
        if not subject:
            return {"success": False, "error": "Subject is required"}

        smtp_host = Config.SMTP_HOST
        smtp_port = Config.SMTP_PORT
        smtp_user = Config.SMTP_USER
        smtp_pass = Config.SMTP_PASS

        if not smtp_host or not smtp_user:
            return {
                "success": False,
                "error": "SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASS in .env",
            }

        import asyncio
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        def _send_sync() -> Dict[str, Any]:
            try:
                msg = MIMEMultipart()
                msg["From"] = smtp_user
                msg["To"] = to
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "plain", "utf-8"))

                with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                    server.ehlo()
                    if smtp_port != 25:
                        server.starttls()
                        server.ehlo()
                    if smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, [to], msg.as_string())

                logger.info("Email sent to %s: %s", to, subject)
                return {
                    "success": True,
                    "message": f"Email sent to {to}",
                    "subject": subject,
                }
            except Exception as exc:
                logger.error("Failed to send email: %s", exc)
                return {"success": False, "error": str(exc)}

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _send_sync)

    # ── Gmail OAuth Helpers ────────────────────────────────────────────

    def _get_gmail_service(self):
        """Build and return an authenticated Gmail API service object."""
        import os
        import json

        creds_path = Config.GMAIL_CREDENTIALS_PATH
        token_path = os.path.join(os.path.dirname(creds_path), "gmail_token.json")

        if not os.path.exists(creds_path):
            raise FileNotFoundError(
                f"Gmail OAuth credentials not found at {creds_path}. "
                "Download from Google Cloud Console and place at that path."
            )

        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
        creds = None

        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    def _parse_message(self, service, msg_id: str) -> Dict[str, Any]:
        """Fetch and parse a single Gmail message into a clean dict."""
        msg = service.users().messages().get(userId="me", id=msg_id, format="metadata").execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}

        return {
            "id": msg_id,
            "from": headers.get("from", "unknown"),
            "to": headers.get("to", "unknown"),
            "subject": headers.get("subject", "(no subject)"),
            "date": headers.get("date", "unknown"),
            "snippet": msg.get("snippet", ""),
        }

    # ── Gmail Read ─────────────────────────────────────────────────────

    async def _read_inbox(self, max_results: int = 10) -> Dict[str, Any]:
        """Fetch recent inbox messages via Gmail API."""
        import asyncio

        def _read_sync() -> Dict[str, Any]:
            try:
                service = self._get_gmail_service()
                results = (
                    service.users()
                    .messages()
                    .list(userId="me", labelIds=["INBOX"], maxResults=max_results)
                    .execute()
                )
                messages = results.get("messages", [])
                if not messages:
                    return {"success": True, "emails": [], "message": "Inbox is empty"}

                emails = []
                for msg_stub in messages:
                    try:
                        emails.append(self._parse_message(service, msg_stub["id"]))
                    except Exception as exc:
                        logger.debug("Failed to parse message %s: %s", msg_stub.get("id"), exc)

                return {
                    "success": True,
                    "emails": emails,
                    "total": len(emails),
                    "message": f"Found {len(emails)} recent emails",
                }
            except FileNotFoundError as exc:
                return {"success": False, "error": str(exc)}
            except Exception as exc:
                logger.error("Gmail read failed: %s", exc)
                return {"success": False, "error": str(exc)}

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _read_sync)

    # ── Gmail Search ───────────────────────────────────────────────────

    async def _search_email(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """Search Gmail inbox by query string."""
        if not query:
            return {"success": False, "error": "Search query is required"}

        import asyncio

        def _search_sync() -> Dict[str, Any]:
            try:
                service = self._get_gmail_service()
                results = (
                    service.users()
                    .messages()
                    .list(userId="me", q=query, maxResults=max_results)
                    .execute()
                )
                messages = results.get("messages", [])
                if not messages:
                    return {
                        "success": True,
                        "emails": [],
                        "message": f"No emails found for query: {query}",
                    }

                emails = []
                for msg_stub in messages:
                    try:
                        emails.append(self._parse_message(service, msg_stub["id"]))
                    except Exception as exc:
                        logger.debug("Failed to parse message %s: %s", msg_stub.get("id"), exc)

                return {
                    "success": True,
                    "emails": emails,
                    "total": len(emails),
                    "query": query,
                    "message": f"Found {len(emails)} emails matching '{query}'",
                }
            except FileNotFoundError as exc:
                return {"success": False, "error": str(exc)}
            except Exception as exc:
                logger.error("Gmail search failed: %s", exc)
                return {"success": False, "error": str(exc)}

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _search_sync)
