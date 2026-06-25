"""DM Pairing — Access control for unknown DM senders.

When an unknown user DMs the bot, they receive a 6-character pairing code.
The admin must approve the code before the user can interact. Pairing codes
expire after a configurable timeout.

Inspired by OpenClaw's DM pairing security model.
"""

from __future__ import annotations

import json
import logging
import secrets
import string
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CODE_CHARS = string.ascii_uppercase + string.digits
_CODE_LENGTH = 6
_DEFAULT_EXPIRY_MINUTES = 10


@dataclass(slots=True)
class PairingRequest:
    """A pending or completed pairing request."""

    user_id: str
    platform: str
    code: str
    created_at: str  # ISO format
    approved: bool = False
    approved_by: str = ""
    approved_at: str = ""
    expires_at: str = ""  # ISO format


@dataclass(slots=True)
class PairedUser:
    """A user that has been paired and verified."""

    user_id: str
    platform: str
    paired_at: str
    approved_by: str = ""
    display_name: str = ""


class DMPairingManager:
    """Manages DM pairing codes for unknown senders.

    Flow:
    1. Unknown user sends DM → bot calls ``generate_pairing_code()``
    2. Bot replies with the code: "Send this code to your admin: XYZABC"
    3. Admin approves via ``ravyn approve-pairing XYZABC`` or in chat
    4. User is now paired and can interact freely

    Storage: JSONL files in ``workspace/memory/pairing/``
    """

    def __init__(
        self,
        store_dir: str | Path | None = None,
        expiry_minutes: int = _DEFAULT_EXPIRY_MINUTES,
    ) -> None:
        if store_dir is None:
            from app.settings.config import Config
            store_dir = Path(Config.MEMORY_ROOT) / "pairing"
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._expiry_minutes = expiry_minutes

        self._pending_file = self._store_dir / "pending.jsonl"
        self._paired_file = self._store_dir / "paired.jsonl"

        # In-memory caches
        self._paired_cache: dict[str, PairedUser] = {}
        self._pending_cache: dict[str, PairingRequest] = {}
        self._load_caches()

    # ── Public API ──────────────────────────────────────────────────

    def is_paired(self, user_id: str, platform: str) -> bool:
        """Check if a user has been paired on a platform."""
        key = self._make_key(user_id, platform)
        return key in self._paired_cache

    def generate_pairing_code(self, user_id: str, platform: str) -> str:
        """Generate a pairing code for an unknown user.

        If a pending code already exists and hasn't expired, returns it.
        Otherwise generates a new one.
        """
        key = self._make_key(user_id, platform)

        # Check for existing pending code
        existing = self._pending_cache.get(key)
        if existing and not self._is_expired(existing):
            return existing.code

        # Generate new code
        code = self._generate_code()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=self._expiry_minutes)

        request = PairingRequest(
            user_id=user_id,
            platform=platform,
            code=code,
            created_at=now.isoformat(),
            expires_at=expires.isoformat(),
        )

        self._pending_cache[key] = request
        self._append_jsonl(self._pending_file, asdict(request))

        logger.info(
            "Generated pairing code %s for %s on %s (expires %s)",
            code, user_id, platform, expires.isoformat(),
        )
        return code

    def approve_code(self, code: str, approved_by: str = "admin") -> bool:
        """Approve a pairing code. Returns True if successful."""
        # Find the pending request with this code
        target_key: str | None = None
        target_request: PairingRequest | None = None

        for key, request in self._pending_cache.items():
            if request.code == code.upper().strip():
                if self._is_expired(request):
                    logger.warning("Pairing code %s has expired", code)
                    return False
                target_key = key
                target_request = request
                break

        if target_key is None or target_request is None:
            logger.warning("Pairing code %s not found", code)
            return False

        # Mark as approved
        now = datetime.now(timezone.utc)
        target_request.approved = True
        target_request.approved_by = approved_by
        target_request.approved_at = now.isoformat()

        # Add to paired users
        paired = PairedUser(
            user_id=target_request.user_id,
            platform=target_request.platform,
            paired_at=now.isoformat(),
            approved_by=approved_by,
        )
        self._paired_cache[target_key] = paired
        self._append_jsonl(self._paired_file, asdict(paired))

        # Remove from pending
        del self._pending_cache[target_key]
        # Persist the removal to disk so a bot restart does
        # not re-load the approved request from pending.jsonl.
        # Without this, a re-launched bot would issue a fresh
        # code for the same user_id+platform pair.
        self._rewrite_pending()

        logger.info(
            "Approved pairing for %s on %s (code: %s, by: %s)",
            target_request.user_id, target_request.platform, code, approved_by,
        )
        return True

    def revoke_pairing(self, user_id: str, platform: str) -> bool:
        """Revoke a user's pairing."""
        key = self._make_key(user_id, platform)
        if key in self._paired_cache:
            del self._paired_cache[key]
            self._rewrite_paired()
            logger.info("Revoked pairing for %s on %s", user_id, platform)
            return True
        return False

    def get_pending_requests(self) -> list[PairingRequest]:
        """Return all non-expired pending requests."""
        self.cleanup_expired()
        return list(self._pending_cache.values())

    def get_paired_users(self) -> list[PairedUser]:
        """Return all paired users."""
        return list(self._paired_cache.values())

    def cleanup_expired(self) -> int:
        """Remove expired pairing requests. Returns count removed."""
        expired_keys: list[str] = []
        for key, request in self._pending_cache.items():
            if self._is_expired(request):
                expired_keys.append(key)

        for key in expired_keys:
            del self._pending_cache[key]

        if expired_keys:
            logger.debug("Cleaned up %d expired pairing requests", len(expired_keys))
        return len(expired_keys)

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _make_key(user_id: str, platform: str) -> str:
        return f"{platform}:{user_id}"

    @staticmethod
    def _generate_code() -> str:
        return "".join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_LENGTH))

    @staticmethod
    def _is_expired(request: PairingRequest) -> bool:
        if not request.expires_at:
            return False
        try:
            expires = datetime.fromisoformat(request.expires_at)
            return datetime.now(timezone.utc) > expires
        except Exception:
            return False

    def _load_caches(self) -> None:
        """Load paired users and pending requests from disk."""
        # Load paired users
        if self._paired_file.exists():
            for line in self._paired_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    user = PairedUser(**data)
                    key = self._make_key(user.user_id, user.platform)
                    self._paired_cache[key] = user
                except Exception:
                    continue

        # Load pending requests (skip expired)
        if self._pending_file.exists():
            for line in self._pending_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    request = PairingRequest(**data)
                    if not request.approved and not self._is_expired(request):
                        key = self._make_key(request.user_id, request.platform)
                        self._pending_cache[key] = request
                except Exception:
                    continue

    @staticmethod
    def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(data) + "\n")
        except Exception as exc:
            logger.warning("Failed to write to %s: %s", path, exc)

    def _rewrite_paired(self) -> None:
        """Rewrite the paired file from cache (after revocations)."""
        try:
            with self._paired_file.open("w", encoding="utf-8") as fh:
                for user in self._paired_cache.values():
                    fh.write(json.dumps(asdict(user)) + "\n")
        except Exception as exc:
            logger.warning("Failed to rewrite paired file: %s", exc)

    def _rewrite_pending(self) -> None:
        """Rewrite the pending file from cache.  Called after an
        approval so a bot restart does not re-load the approved
        request as still-pending."""
        try:
            with self._pending_file.open("w", encoding="utf-8") as fh:
                for request in self._pending_cache.values():
                    fh.write(json.dumps(asdict(request)) + "\n")
        except Exception as exc:
            logger.warning("Failed to rewrite pending file: %s", exc)


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_PAIRING: DMPairingManager | None = None


def get_dm_pairing_manager() -> DMPairingManager:
    """Get or create the global DMPairingManager."""
    global _GLOBAL_PAIRING
    if _GLOBAL_PAIRING is None:
        _GLOBAL_PAIRING = DMPairingManager()
    return _GLOBAL_PAIRING
