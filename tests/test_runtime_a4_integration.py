"""Integration tests for A4 (vault + audit + policy v2) wiring in the runtime.

The runtime is a 1500-line beast that builds a lot of components at
construction.  These tests focus narrowly on the A4 integration
points:

- A4 components are constructed when their feature flags are on.
- A4 components are ``None`` when flags are off (legacy path).
- ``_audit`` is a no-op when audit is disabled.
- ``_policy_v2_check`` honors the verdict.
- ``_resolve_credential`` prefers the vault over env vars.

We don't construct the full ``AgentRuntime`` (it pulls in providers,
embeddings, etc. that are slow and depend on external services).
Instead we instantiate the small pieces of the runtime we care
about by manipulating module state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Lightweight runtime stub — bypasses heavy construction in AgentRuntime
# ---------------------------------------------------------------------------


def _make_runtime_stub(
    tmp_path: Path,
    *,
    vault: bool = False,
    audit: bool = False,
    policy: bool = False,
) -> Any:
    """Build just the A4 components without instantiating the full runtime.

    The runtime module exposes the A4 builders as module-level
    functions so we can wire them up in isolation.  The stub is a
    small namespace that the helper methods are bound onto.
    """
    from app.core.runtime import (
        _env_flag,
        _build_audit_log_v2,
        _build_policy_v2,
    )

    # Apply env flags for the duration of the test.
    saved = {}
    for name, want in (
        ("RAVEN_VAULT_ENABLED", vault),
        ("RAVEN_AUDIT_V2", audit),
        ("RAVEN_POLICY_V2", policy),
    ):
        saved[name] = os.environ.pop(name, None)
        if want:
            os.environ[name] = "1"

    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)
    audit_path = tmp_path / "audit.jsonl"
    os.environ["RAVEN_POLICY_STATE_DIR"] = str(state_dir)
    os.environ["RAVEN_AUDIT_PATH"] = str(audit_path)

    try:
        # Use ephemeral keys and per-test paths so the vault doesn't
        # bleed state across tests (the default vault file lives at
        # ~/.raven/vault.json which would persist forever).
        from app.core.vault import SecretVault

        secret_vault = SecretVault(
            vault_file=tmp_path / "vault.json",
            key_file=tmp_path / "vault.key",
            ephemeral_key=True,
        )
        audit_log_v2 = _build_audit_log_v2()
        policy_engine_v2 = _build_policy_v2(audit_log=audit_log_v2, state_dir=state_dir)

        # Build a small "namespace" object that mimics the relevant
        # attributes of AgentRuntime, so the tests can call the
        # A4 helpers directly.  Use ``__annotations__`` so pyright
        # sees the types.
        class _Stub:
            secret_vault: Any
            audit_log_v2: Any
            policy_engine_v2: Any
            _use_vault_v2: bool
            _use_audit_v2: bool
            _use_policy_v2: bool

            def _audit(self, **kwargs: Any) -> None: ...

            def _policy_v2_check(
                self, function_name: str, args: dict[str, Any], user_id: str
            ) -> tuple[bool, str, str | None]: ...

            def _resolve_credential(
                self, name: str, env_var: str, default: str | None = None
            ) -> str | None: ...

        s = _Stub()
        s.secret_vault = secret_vault
        s.audit_log_v2 = audit_log_v2
        s.policy_engine_v2 = policy_engine_v2
        s._use_vault_v2 = _env_flag("RAVEN_VAULT_ENABLED")
        s._use_audit_v2 = _env_flag("RAVEN_AUDIT_V2")
        s._use_policy_v2 = _env_flag("RAVEN_POLICY_V2")
        # Bind the methods (so the tests can call them like methods).
        from app.core.runtime import AgentRuntime

        s._audit = AgentRuntime._audit.__get__(s, type(s))
        s._policy_v2_check = AgentRuntime._policy_v2_check.__get__(s, type(s))
        s._resolve_credential = AgentRuntime._resolve_credential.__get__(s, type(s))
        return s
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestA4Construction:
    def test_default_all_disabled(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path)
        assert s._use_vault_v2 is False
        assert s._use_audit_v2 is False
        assert s._use_policy_v2 is False
        # Builders still return objects (they're cheap & lazy), but
        # the flag-gated behavior should be no-op.
        assert s.secret_vault is not None  # lazy constructor
        assert s.audit_log_v2 is not None
        assert s.policy_engine_v2 is not None

    def test_vault_enabled(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, vault=True)
        assert s._use_vault_v2 is True

    def test_audit_enabled(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, audit=True)
        assert s._use_audit_v2 is True

    def test_policy_enabled(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, policy=True)
        assert s._use_policy_v2 is True

    def test_all_enabled(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, vault=True, audit=True, policy=True)
        assert s._use_vault_v2 is True
        assert s._use_audit_v2 is True
        assert s._use_policy_v2 is True


# ---------------------------------------------------------------------------
# _audit
# ---------------------------------------------------------------------------


class TestAuditHelper:
    def test_noop_when_disabled(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, audit=False)
        s._audit(
            kind="tool_attempt",
            actor="u1",
            action="list_files",
        )
        # Nothing to query — audit is disabled, log is empty.
        assert len(s.audit_log_v2.query(limit=100)) == 0

    def test_records_when_enabled(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, audit=True)
        s._audit(
            kind="tool_call",
            actor="u1",
            action="list_files",
            context={"foo": "bar"},
        )
        events = s.audit_log_v2.query(limit=10)
        assert len(events) == 1
        e = events[0]
        assert e.action == "list_files"
        assert e.actor == "u1"
        assert e.context.get("foo") == "bar"

    def test_audit_failure_does_not_raise(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, audit=True)
        # Pass an invalid kind — should be caught and logged, not raised.
        s._audit(kind="not-a-real-kind", actor="u1", action="x")
        # The audit module's enum coercion will raise, but the
        # _audit helper wraps it in a try/except and silently
        # no-ops.  Either way: no exception propagates.


# ---------------------------------------------------------------------------
# _policy_v2_check
# ---------------------------------------------------------------------------


class TestPolicyV2Check:
    def test_disabled_returns_allow(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, policy=False)
        # Even a destructive action returns allow when v2 is off.
        allowed, reason, approval = s._policy_v2_check("rm", {"path": "/etc/passwd"}, "u1")
        assert allowed is True
        assert reason == ""
        assert approval is None

    def test_deny_destructive_action(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, policy=True)
        allowed, reason, approval = s._policy_v2_check("rm", {"path": "/etc/passwd"}, "u1")
        assert allowed is False
        assert approval is None
        assert "policy v2" in reason

    def test_admin_bypasses(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, policy=True)
        s.policy_engine_v2.trust.set_tier("admin1", "admin")
        allowed, reason, approval = s._policy_v2_check("rm", {"path": "/etc/passwd"}, "admin1")
        assert allowed is True
        assert approval is None

    def test_args_are_filtered(self, tmp_path: Path) -> None:
        """Non-primitive arg values (e.g. _request object) must be filtered out."""
        s = _make_runtime_stub(tmp_path, policy=True)
        # Pass an args dict with a non-primitive value that would break
        # the engine's signature.  The helper should drop it.
        args = {
            "path": "/tmp",
            "_request": object(),  # not a primitive — must be dropped
            "command": "ls",  # primitive — kept
            "user_data": {"nested": "dict"},  # not primitive — dropped
        }
        allowed, reason, approval = s._policy_v2_check("exec", args, "u1")
        # Should not raise; the engine should still process the call.
        assert allowed in (True, False)
        assert reason is not None
        assert (approval is None) or isinstance(approval, str)

    def test_ask_emits_approval_id(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, policy=True)
        # Set up the engine so git_push on an ESTABLISHED user is ASK.
        s.policy_engine_v2.trust.set_tier("u1", "established")
        # git_push base = 65; established * 0.9 = 58 → ASK
        allowed, reason, approval = s._policy_v2_check("git_push", {"branch": "main"}, "u1")
        assert allowed is False
        assert approval is not None
        pending = s.policy_engine_v2.approvals.pending()
        assert any(p.id == approval for p in pending)


# ---------------------------------------------------------------------------
# _resolve_credential
# ---------------------------------------------------------------------------


class TestResolveCredential:
    def test_env_fallback_when_vault_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MY_TEST_KEY", "env_value")
        s = _make_runtime_stub(tmp_path, vault=False)
        v = s._resolve_credential("my_test", "MY_TEST_KEY")
        assert v == "env_value"

    def test_returns_none_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MY_MISSING_KEY", raising=False)
        s = _make_runtime_stub(tmp_path, vault=False)
        v = s._resolve_credential("my_missing", "MY_MISSING_KEY")
        assert v is None

    def test_vault_takes_precedence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TEST_KEY", "env_value")
        s = _make_runtime_stub(tmp_path, vault=True)
        s.secret_vault.set("my_test", "vault_value")
        v = s._resolve_credential("my_test", "MY_TEST_KEY")
        assert v == "vault_value"

    def test_env_used_when_vault_lacks_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MY_TEST_KEY", "env_value")
        s = _make_runtime_stub(tmp_path, vault=True)
        # Vault enabled but doesn't have the entry → env wins.
        v = s._resolve_credential("my_test", "MY_TEST_KEY")
        assert v == "env_value"


# ---------------------------------------------------------------------------
# Pending approvals — small utility
# ---------------------------------------------------------------------------


class TestApprovalStoreIntegration:
    def test_engine_pending_ids(self, tmp_path: Path) -> None:
        """The runtime helper should work with engine.pending_approvals().

        ``pending_ids`` is a small convenience we add for the test.
        """
        s = _make_runtime_stub(tmp_path, policy=True)
        s.policy_engine_v2.trust.set_tier("u1", "established")
        s._policy_v2_check("git_push", {"branch": "main"}, "u1")
        s._policy_v2_check("git_push", {"branch": "dev"}, "u1")
        assert len(s.policy_engine_v2.pending_approvals()) == 2

    def test_resolve_via_engine(self, tmp_path: Path) -> None:
        s = _make_runtime_stub(tmp_path, policy=True)
        s.policy_engine_v2.trust.set_tier("u1", "established")
        _, _, approval_id = s._policy_v2_check("git_push", {}, "u1")
        assert approval_id is not None
        approval = s.policy_engine_v2.resolve_approval(
            approval_id, approved=True, resolved_by="admin1"
        )
        assert approval.status == "approved"

    def test_audit_picks_up_deny(self, tmp_path: Path) -> None:
        """When policy v2 denies, the runtime's audit log records it."""
        s = _make_runtime_stub(tmp_path, audit=True, policy=True)
        # Simulate the runtime's deny path manually.
        s._audit(
            kind="policy",
            actor="u1",
            action="rm",
            success=False,
            detail="v2 denied rm",
            context={"gate": "v2", "verdict": "deny"},
            risk_level="critical",
        )
        events = s.audit_log_v2.query(kind="policy")
        assert len(events) == 1
        assert events[0].action == "rm"
        assert events[0].success is False
        # risk_level is enum-like (str subclass); compare against the
        # value rather than the type to keep the test robust.
        assert str(events[0].risk_level) == "critical"
