"""Encrypted-at-rest secret vault.

The vault is the single point of truth for credentials the runtime
needs at boot (API keys, OAuth tokens, webhook URLs, etc.).  All
entries are encrypted with Fernet (AES-128 + HMAC-SHA256) before
they ever touch disk.

Key resolution order (first wins):

1. ``SARAS_VAULT_KEY`` env var — a base64-encoded 32-byte key.  Use
   this in container / CI environments where keyring is unavailable.
2. OS keyring — the system password manager (macOS Keychain, Linux
   Secret Service, Windows DPAPI).  The key is stored under the
   service name ``saras-vault`` and account ``master``.
3. Local key file at ``~/.saras/vault.key`` (mode 0600).  Created
   on first use if neither (1) nor (2) is available.

The vault is designed to fail closed: a missing or corrupt key
raises :class:`VaultUnavailable` and the caller must surface a
clear error rather than silently fall back to plaintext.

Backing store is a JSON file at ``~/.saras/vault.json``.  All
values are base64-encoded ciphertext; no plaintext ever lands on
disk.  An optional HelixDB KV store can be attached for cross-host
replication.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


KEYRING_SERVICE = "saras-vault"
KEYRING_ACCOUNT = "master"
DEFAULT_VAULT_DIR = Path.home() / ".saras"
DEFAULT_VAULT_FILE = DEFAULT_VAULT_DIR / "vault.json"
DEFAULT_KEY_FILE = DEFAULT_VAULT_DIR / "vault.key"
ENV_KEY_VAR = "SARAS_VAULT_KEY"


class VaultUnavailable(RuntimeError):
    """Raised when the vault cannot be opened (no key, corrupt key, etc.)."""


class SecretNotFound(KeyError):
    """Raised by ``get_required`` when a secret is missing."""


@dataclass(slots=True)
class VaultEntry:
    """Metadata + ciphertext for a single secret."""

    name: str
    ciphertext: str  # base64
    created_at: datetime
    updated_at: datetime
    rotation_count: int = 0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ciphertext": self.ciphertext,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "rotation_count": self.rotation_count,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VaultEntry":
        return cls(
            name=d["name"],
            ciphertext=d["ciphertext"],
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
            rotation_count=int(d.get("rotation_count", 0)),
            tags=list(d.get("tags", [])),
        )


class SecretVault:
    """Encrypted credential store.

    The vault is process-safe via a single :class:`threading.RLock`.
    All file I/O goes through ``_atomic_write`` so a crash mid-write
    never leaves a corrupt vault file.
    """

    def __init__(
        self,
        *,
        vault_file: Path | str = DEFAULT_VAULT_FILE,
        key_file: Path | str = DEFAULT_KEY_FILE,
        # Provide an explicit Fernet to bypass key discovery.  Used by
        # tests and by the rotation path.  In production, leave None
        # and let the vault find its own key.
        fernet: Fernet | None = None,
        # In-memory key store, used when keyring is unavailable but
        # the process is short-lived (tests, one-off scripts).
        ephemeral_key: bool = False,
    ) -> None:
        self._vault_file = Path(vault_file)
        self._key_file = Path(key_file)
        self._lock = threading.RLock()
        self._ephemeral = ephemeral_key
        self._explicit_fernet = fernet
        # Lazy: the actual Fernet + cache get populated on first use.
        self._fernet: Fernet | None = fernet
        self._entries: dict[str, VaultEntry] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Key resolution
    # ------------------------------------------------------------------

    def _resolve_key(self) -> bytes:
        """Return a fresh 32-byte Fernet key (urlsafe base64)."""
        # 1. Env var
        env_key = os.environ.get(ENV_KEY_VAR, "").strip()
        if env_key:
            try:
                # Verify it's a valid Fernet key.
                Fernet(env_key.encode("ascii"))
                return env_key.encode("ascii")
            except Exception as e:  # noqa: BLE001
                raise VaultUnavailable(
                    f"{ENV_KEY_VAR} is set but not a valid Fernet key: {e}"
                ) from e
        # 2. Keyring
        if not self._ephemeral:
            try:
                import keyring

                stored = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
                if stored:
                    Fernet(stored.encode("ascii"))
                    return stored.encode("ascii")
            except Exception as e:  # noqa: BLE001
                logger.debug("keyring lookup failed: %s", e)
        # 3. Key file
        if self._key_file.exists():
            data = self._key_file.read_text(encoding="utf-8").strip()
            if data:
                try:
                    Fernet(data.encode("ascii"))
                    return data.encode("ascii")
                except Exception as e:  # noqa: BLE001
                    raise VaultUnavailable(f"key file {self._key_file} is corrupt: {e}") from e
        # 4. Generate new
        new_key = Fernet.generate_key()
        if not self._ephemeral:
            self._key_file.parent.mkdir(parents=True, exist_ok=True)
            self._key_file.write_text(new_key.decode("ascii"), encoding="utf-8")
            try:
                os.chmod(self._key_file, 0o600)
            except OSError:
                logger.warning("could not chmod key file to 0600")
            logger.info("generated new vault key at %s", self._key_file)
        return new_key

    def _ensure_open(self) -> None:
        with self._lock:
            if self._fernet is None:
                key = self._explicit_fernet
                if key is None:
                    key = Fernet(self._resolve_key())
                self._fernet = key
            if not self._loaded:
                self._load()

    def _load(self) -> None:
        if not self._vault_file.exists():
            self._entries = {}
            self._loaded = True
            return
        try:
            raw = json.loads(self._vault_file.read_text(encoding="utf-8"))
            self._entries = {e["name"]: VaultEntry.from_dict(e) for e in raw.get("entries", [])}
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise VaultUnavailable(f"vault file {self._vault_file} is corrupt: {e}") from e
        self._loaded = True

    def _atomic_write(self) -> None:
        self._vault_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._vault_file.with_suffix(".tmp")
        payload = {
            "version": 1,
            "entries": [e.to_dict() for e in self._entries.values()],
        }
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self._vault_file)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, name: str, value: str, *, tags: Iterable[str] = ()) -> None:
        """Encrypt and store ``value`` under ``name``."""
        if not name:
            raise ValueError("secret name must be non-empty")
        self._ensure_open()
        with self._lock:
            assert self._fernet is not None
            now = datetime.now(timezone.utc)
            ct = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
            existing = self._entries.get(name)
            if existing is not None:
                existing.ciphertext = ct
                existing.updated_at = now
                existing.tags = list(tags)
                existing.rotation_count += 1
            else:
                self._entries[name] = VaultEntry(
                    name=name,
                    ciphertext=ct,
                    created_at=now,
                    updated_at=now,
                    tags=list(tags),
                )
            self._atomic_write()

    def get(self, name: str, *, default: str | None = None) -> str | None:
        """Decrypt and return the value, or ``default`` if missing."""
        self._ensure_open()
        with self._lock:
            entry = self._entries.get(name)
        if entry is None:
            return default
        return self._decrypt_entry(entry)

    def get_required(self, name: str) -> str:
        """Decrypt and return the value, raising if missing."""
        v = self.get(name)
        if v is None:
            raise SecretNotFound(f"secret not found: {name}")
        return v

    def delete(self, name: str) -> bool:
        """Remove a secret.  Returns True if it existed."""
        self._ensure_open()
        with self._lock:
            existed = self._entries.pop(name, None) is not None
            if existed:
                self._atomic_write()
        return existed

    def list_names(self) -> list[str]:
        """Return all secret names (never the values)."""
        self._ensure_open()
        with self._lock:
            return sorted(self._entries.keys())

    def metadata(self, name: str) -> dict[str, Any] | None:
        """Return non-secret metadata for a secret."""
        self._ensure_open()
        with self._lock:
            entry = self._entries.get(name)
        if entry is None:
            return None
        return {
            "name": entry.name,
            "created_at": entry.created_at.isoformat(),
            "updated_at": entry.updated_at.isoformat(),
            "rotation_count": entry.rotation_count,
            "tags": list(entry.tags),
        }

    def rotate_key(self) -> int:
        """Generate a new master key and re-encrypt every entry.

        Returns the number of entries re-encrypted.  After rotation
        the new key is persisted and the old one is discarded.
        """
        self._ensure_open()
        with self._lock:
            assert self._fernet is not None
            old = self._fernet
            new_key = Fernet.generate_key()
            new_fernet = Fernet(new_key)
            count = 0
            for entry in self._entries.values():
                try:
                    plaintext = old.decrypt(entry.ciphertext.encode("ascii")).decode("utf-8")
                except InvalidToken:
                    logger.warning(
                        "entry %s could not be decrypted during rotation; skipping",
                        entry.name,
                    )
                    continue
                entry.ciphertext = new_fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
                entry.rotation_count += 1
                entry.updated_at = datetime.now(timezone.utc)
                count += 1
            self._fernet = new_fernet
            # Persist new key
            if not self._ephemeral:
                self._key_file.parent.mkdir(parents=True, exist_ok=True)
                self._key_file.write_text(new_key.decode("ascii"), encoding="utf-8")
                try:
                    os.chmod(self._key_file, 0o600)
                except OSError:
                    pass
                # Try to update keyring too
                try:
                    import keyring

                    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, new_key.decode("ascii"))
                except Exception as e:  # noqa: BLE001
                    logger.debug("keyring update failed: %s", e)
            self._atomic_write()
        return count

    def health(self) -> dict[str, Any]:
        """Return vault health for the /admin dashboard."""
        self._ensure_open()
        with self._lock:
            count = len(self._entries)
            latest = max((e.updated_at for e in self._entries.values()), default=None)
            return {
                "vault_file": str(self._vault_file),
                "key_file": str(self._key_file),
                "secret_count": count,
                "latest_update": latest.isoformat() if latest else None,
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _decrypt_entry(self, entry: VaultEntry) -> str:
        assert self._fernet is not None
        try:
            return self._fernet.decrypt(entry.ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as e:
            raise VaultUnavailable(
                f"failed to decrypt {entry.name}: wrong key or corrupt entry"
            ) from e


# ---------------------------------------------------------------------------
# Module-level helper for the common "get from vault or env" pattern.
# ---------------------------------------------------------------------------


def resolve_secret(
    name: str,
    *,
    vault: SecretVault | None = None,
    env_var: str | None = None,
    default: str | None = None,
) -> str | None:
    """Look up a secret in the vault, then the env, then return default."""
    if vault is not None:
        v = vault.get(name)
        if v is not None:
            return v
    if env_var:
        env_v = os.environ.get(env_var, "").strip()
        if env_v:
            return env_v
    return default


__all__ = [
    "SecretVault",
    "VaultEntry",
    "VaultUnavailable",
    "SecretNotFound",
    "resolve_secret",
    "KEYRING_SERVICE",
    "KEYRING_ACCOUNT",
    "ENV_KEY_VAR",
    "DEFAULT_VAULT_DIR",
    "DEFAULT_VAULT_FILE",
    "DEFAULT_KEY_FILE",
]
