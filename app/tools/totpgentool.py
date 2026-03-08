# app/tools/totpgentool.py
"""TOTPGeneratorTool — generate TOTP 2FA codes."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

try:
    import pyotp
except ImportError:
    pyotp = None


class TOTPGeneratorTool(BaseTool):
    """Generate TOTP (Time-based One-Time Password) 2FA codes. Manage 2FA secrets."""

    def __init__(self, secrets_file: str = "workspace/totp_secrets.json"):
        self.secrets_file = Path(secrets_file)
        self._secrets: Dict[str, str] = {}
        self._load_secrets()

    def _load_secrets(self) -> None:
        if self.secrets_file.exists():
            import json

            try:
                self._secrets = json.loads(self.secrets_file.read_text())
            except Exception:
                self._secrets = {}

    def _save_secrets(self) -> None:
        self.secrets_file.parent.mkdir(parents=True, exist_ok=True)
        import json

        self.secrets_file.write_text(json.dumps(self._secrets, indent=2))

    def get_name(self) -> str:
        return "totp_generator"

    def get_description(self) -> str:
        return (
            "Generate TOTP (Time-based One-Time Password) 2FA codes for services. "
            "Add new 2FA secrets, list accounts, generate current codes, "
            "and delete saved secrets. Uses standard TOTP algorithm (RFC 6238)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation to perform",
                    required=True,
                    enum=["generate", "add", "list", "delete", "verify"],
                ),
                ToolParameter(
                    name="account",
                    type="string",
                    description="Account name/service (e.g., 'google', 'github')",
                    required=False,
                ),
                ToolParameter(
                    name="secret",
                    type="string",
                    description="Base32 secret key (from 2FA setup)",
                    required=False,
                ),
                ToolParameter(
                    name="code",
                    type="string",
                    description="Code to verify",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if pyotp is None:
            return {
                "success": False,
                "error": "pyotp not installed. pip install pyotp",
            }

        operation = kwargs.get("operation", "generate")
        account = kwargs.get("account", "").lower().strip()
        secret = kwargs.get("secret", "").upper().replace(" ", "").strip()
        code = kwargs.get("code", "").strip()

        try:
            if operation == "generate":
                if not account:
                    return {"success": False, "error": "account name required"}
                if account not in self._secrets:
                    return {
                        "success": False,
                        "error": f"Account '{account}' not found. Use 'add' to add a secret.",
                    }
                totp = pyotp.TOTP(self._secrets[account])
                current_code = totp.now()
                import datetime

                remaining = 30 - (datetime.datetime.now().timestamp() % 30)
                return {
                    "success": True,
                    "account": account,
                    "code": current_code,
                    "remaining_seconds": int(remaining),
                    "note": f"Code refreshes in {remaining}s",
                }

            if operation == "add":
                if not account or not secret:
                    return {"success": False, "error": "account and secret required"}
                try:
                    pyotp.TOTP(secret).now()
                except Exception:
                    return {
                        "success": False,
                        "error": "Invalid secret key (must be Base32)",
                    }
                self._secrets[account] = secret
                self._save_secrets()
                return {
                    "success": True,
                    "action": "added",
                    "account": account,
                    "note": "Secret saved securely. Use 'generate' to get codes.",
                }

            if operation == "list":
                accounts = list(self._secrets.keys())
                return {
                    "success": True,
                    "accounts": accounts,
                    "count": len(accounts),
                    "note": "Use 'generate' with account name to get 2FA code",
                }

            if operation == "delete":
                if not account:
                    return {"success": False, "error": "account name required"}
                if account not in self._secrets:
                    return {"success": False, "error": f"Account '{account}' not found"}
                del self._secrets[account]
                self._save_secrets()
                return {"success": True, "action": "deleted", "account": account}

            if operation == "verify":
                if not account or not code:
                    return {"success": False, "error": "account and code required"}
                if account not in self._secrets:
                    return {"success": False, "error": f"Account '{account}' not found"}
                totp = pyotp.TOTP(self._secrets[account])
                valid = totp.verify(code)
                return {
                    "success": True,
                    "account": account,
                    "valid": valid,
                    "note": "Code is valid" if valid else "Code is invalid or expired",
                }

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as exc:
            logger.exception("TOTPGeneratorTool error")
            return {"success": False, "error": str(exc)}
