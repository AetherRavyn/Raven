"""Secret Vault — Encrypted secrets management.

Stores API keys and tokens in an encrypted vault file instead of plaintext
.env. Uses Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256).

Usage:
    vault = SecretVault()
    vault.store("OPENAI_API_KEY", "sk-...")
    key = vault.retrieve("OPENAI_API_KEY")
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SecretVault:
    """Encrypted secrets management using Fernet symmetric encryption.

    The master key is derived from:
    1. ``RAVYN_MASTER_KEY`` env var (recommended)
    2. A generated key stored in ``~/.raven/vault.key`` (fallback)

    Vault file: ``workspace/secrets/vault.enc``
    """

    def __init__(
        self,
        vault_path: str | Path | None = None,
        master_key: str | None = None,
    ) -> None:
        if vault_path is None:
            from app.settings.config import Config
            vault_path = Path(Config.MEMORY_ROOT) / "secrets" / "vault.enc"

        self._vault_path = Path(vault_path)
        self._vault_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = self._init_fernet(master_key)
        self._secrets: dict[str, str] = {}
        self._load()

    # ── Public API ──────────────────────────────────────────────────

    def store(self, key: str, value: str) -> None:
        """Encrypt and store a secret."""
        self._secrets[key] = value
        self._save()
        logger.debug("Secret stored")

    def retrieve(self, key: str) -> str | None:
        """Decrypt and return a secret."""
        return self._secrets.get(key)

    def list_keys(self) -> list[str]:
        """List all stored key names (not values)."""
        return sorted(self._secrets.keys())

    def delete(self, key: str) -> bool:
        """Remove a secret."""
        if key in self._secrets:
            del self._secrets[key]
            self._save()
            logger.debug("Secret deleted")
            return True
        return False

    def has(self, key: str) -> bool:
        """Check if a key exists."""
        return key in self._secrets

    def export_to_env(self) -> dict[str, str]:
        """Return all secrets as a dict (for runtime injection)."""
        return dict(self._secrets)

    def inject_to_environ(self) -> int:
        """Inject all secrets into os.environ. Returns count injected."""
        count = 0
        for key, value in self._secrets.items():
            if key not in os.environ:
                os.environ[key] = value
                count += 1
        return count

    def count(self) -> int:
        """Number of stored secrets."""
        return len(self._secrets)

    # ── Encryption ──────────────────────────────────────────────────

    def _init_fernet(self, master_key: str | None) -> Any:
        """Initialize Fernet cipher from master key."""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            logger.warning(
                "cryptography package not installed — vault will use base64 fallback"
            )
            return None

        if master_key:
            raw_key = master_key
        else:
            raw_key = os.environ.get("RAVYN_MASTER_KEY", "")

        if not raw_key:
            # Auto-generate and persist a key
            raw_key = self._get_or_create_key()

        # Derive a Fernet-compatible key from the raw key
        derived = hashlib.sha256(raw_key.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(derived)
        return Fernet(fernet_key)

    def _get_or_create_key(self) -> str:
        """Get or create a persistent key file."""
        key_path = Path(os.path.expanduser("~/.raven/vault.key"))
        key_path.parent.mkdir(parents=True, exist_ok=True)

        if key_path.exists():
            return key_path.read_text(encoding="utf-8").strip()

        # Generate a new key
        import secrets
        new_key = secrets.token_urlsafe(32)
        key_path.write_text(new_key, encoding="utf-8")
        os.chmod(str(key_path), 0o600)  # Owner-only read/write
        logger.info("Generated new vault key at %s", key_path)
        return new_key

    def _encrypt(self, data: str) -> bytes:
        """Encrypt a string."""
        if self._fernet is None:
            return base64.b64encode(data.encode("utf-8"))
        return self._fernet.encrypt(data.encode("utf-8"))

    def _decrypt(self, data: bytes) -> str:
        """Decrypt bytes to string."""
        if self._fernet is None:
            return base64.b64decode(data).decode("utf-8")
        return self._fernet.decrypt(data).decode("utf-8")

    # ── Persistence ─────────────────────────────────────────────────

    def _save(self) -> None:
        """Encrypt all secrets and write to vault file."""
        try:
            payload = json.dumps(self._secrets, ensure_ascii=False)
            encrypted = self._encrypt(payload)
            self._vault_path.write_bytes(encrypted)
        except Exception as exc:
            logger.error("Failed to save vault: %s", exc)

    def _load(self) -> None:
        """Load and decrypt secrets from vault file."""
        if not self._vault_path.exists():
            self._secrets = {}
            return

        try:
            encrypted = self._vault_path.read_bytes()
            if not encrypted:
                self._secrets = {}
                return
            payload = self._decrypt(encrypted)
            self._secrets = json.loads(payload)
        except Exception as exc:
            logger.warning("Failed to load vault (may need re-encryption): %s", exc)
            self._secrets = {}


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_VAULT: SecretVault | None = None


def get_secret_vault() -> SecretVault:
    """Get or create the global SecretVault."""
    global _GLOBAL_VAULT
    if _GLOBAL_VAULT is None:
        _GLOBAL_VAULT = SecretVault()
    return _GLOBAL_VAULT
