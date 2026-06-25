"""Auth — module authentication and authorization.

A2A-inspired: each module can require authentication.
The auth layer validates tokens, API keys, and permissions
before allowing message delivery.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from raven_protocol.message import Message

logger = logging.getLogger(__name__)


@dataclass
class AuthToken:
    """An authentication token for module access."""
    token_id: str
    module_name: str  # Which module this token grants access to
    permissions: list[str] = field(default_factory=lambda: ["read", "write"])
    expires_at: float = 0.0  # 0 = never expires
    metadata: dict[str, Any] = field(default_factory=dict)


class AuthProvider:
    """Provides authentication and authorization for module access."""

    def __init__(self) -> None:
        self._tokens: dict[str, AuthToken] = {}  # token_id → token
        self._api_keys: dict[str, str] = {}  # module_name → api_key
        self._permissions: dict[str, list[str]] = {}  # module_name → allowed permissions

    def generate_token(
        self,
        module_name: str,
        permissions: list[str] | None = None,
        expires_in_seconds: float = 0,
    ) -> str:
        """Generate an auth token for a module."""
        token_id = secrets.token_urlsafe(32)
        token = AuthToken(
            token_id=token_id,
            module_name=module_name,
            permissions=permissions or ["read", "write"],
            expires_at=time.time() + expires_in_seconds if expires_in_seconds else 0,
        )
        self._tokens[token_id] = token
        logger.info("Auth token generated for module: %s", module_name)
        return token_id

    def generate_api_key(self, module_name: str) -> str:
        """Generate an API key for a module."""
        api_key = secrets.token_urlsafe(48)
        self._api_keys[module_name] = api_key
        return api_key

    def validate_token(self, token_id: str) -> AuthToken | None:
        """Validate a token and return it if valid."""
        token = self._tokens.get(token_id)
        if not token:
            return None
        if token.expires_at and time.time() > token.expires_at:
            del self._tokens[token_id]
            return None
        return token

    def validate_api_key(self, api_key: str, module_name: str) -> bool:
        """Validate an API key for a module."""
        expected = self._api_keys.get(module_name)
        if not expected:
            return False
        return hmac.compare_digest(api_key, expected)

    def check_permission(self, token_id: str, permission: str) -> bool:
        """Check if a token has a specific permission."""
        token = self.validate_token(token_id)
        if not token:
            return False
        return permission in token.permissions

    def revoke_token(self, token_id: str) -> bool:
        """Revoke a token."""
        if token_id in self._tokens:
            del self._tokens[token_id]
            return True
        return False

    def extract_auth_from_message(self, message: Message) -> str | None:
        """Extract auth token from a message's metadata."""
        return message.metadata.get("auth_token")


class AuthMiddleware:
    """Middleware that validates auth before message delivery."""

    def __init__(self, provider: AuthProvider | None = None) -> None:
        self._provider = provider or AuthProvider()

    async def validate(self, message: Message) -> bool:
        """Validate that the message has valid auth.

        Returns True if auth is valid or no auth is required.
        """
        token_id = self._provider.extract_auth_from_message(message)
        if not token_id:
            # No auth required — allow
            return True

        token = self._provider.validate_token(token_id)
        if not token:
            logger.warning("Invalid or expired auth token for message %s", message.id)
            return False

        # Check if token is for the target module
        if token.module_name and token.module_name != message.target:
            logger.warning("Token not valid for target module %s", message.target)
            return False

        return True


# Singleton
_auth_provider: AuthProvider | None = None
_auth_middleware: AuthMiddleware | None = None


def get_auth_provider() -> AuthProvider:
    global _auth_provider
    if _auth_provider is None:
        _auth_provider = AuthProvider()
    return _auth_provider


def get_auth_middleware() -> AuthMiddleware:
    global _auth_middleware
    if _auth_middleware is None:
        _auth_middleware = AuthMiddleware(get_auth_provider())
    return _auth_middleware
