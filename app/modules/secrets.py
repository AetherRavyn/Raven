"""SecretResolver — presence-only checks against the Secret Vault.

Resolves a module's ``required_secrets`` by checking key *presence* in the
``SecretVault`` before registration. It only ever calls ``SecretVault.has`` /
``SecretVault.list_keys`` and never ``retrieve`` — no secret value is read,
logged, or placed in any output. Absent required secrets block registration and
are reported by key name only (Req 4.4, 4.5, 4.6, 13.3).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.modules.models import SecretCheck

if TYPE_CHECKING:
    from app.core.secret_vault import SecretVault

logger = logging.getLogger(__name__)


class SecretResolver:
    """Checks required-secret presence without reading any secret value."""

    def __init__(self, vault: SecretVault) -> None:
        self._vault = vault

    def check_presence(self, keys: list[str]) -> SecretCheck:
        """Return which of ``keys`` are present/absent in the Secret Vault.

        Uses ``SecretVault.has`` only — never ``retrieve`` — so no secret value
        is read or exposed. Key order is preserved and duplicates are collapsed
        to a single result per key. Only key names appear in the returned
        ``SecretCheck`` and in any log entry (Req 4.4, 4.5, 4.6, 13.3).
        """
        result = SecretCheck()
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            if self._vault.has(key):
                result.present.append(key)
            else:
                result.absent.append(key)

        if result.absent:
            logger.debug(
                "Secret presence check: %d present, absent keys=%s",
                len(result.present),
                result.absent,
            )
        return result
