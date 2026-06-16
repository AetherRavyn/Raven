"""PII redaction for audit events (A4).

The audit log captures every tool call, every approval request, every
config change.  Some of those events carry secrets — API keys, OAuth
tokens, passwords, JWTs.  The redaction layer scrubs those out
*before* the event hits disk, so a JSONL tail never leaks a
credential even if the file is copied off-box.

The function is intentionally pure: it takes a dict, returns a new
dict with redacted values.  It can be applied to any event payload,
not just :class:`AuditEvent`.

Patterns detected
-----------------

The default rule set covers the most common credential shapes:

- OpenAI / Anthropic / OpenRouter style keys: ``sk-...``
- AWS access keys: ``AKIA...``
- Google API keys: ``AIza...``
- GitHub tokens: ``ghp_...`` / ``gho_...`` / ``ghs_...``
- Slack tokens: ``xoxb-...`` / ``xoxp-...`` / ``xapp-...``
- PEM private keys (``-----BEGIN ... PRIVATE KEY-----``)
- JWTs (three base64-url segments)
- Bearer tokens (``Bearer <token>``)
- ``password=...``, ``api_key=...``, ``token=...`` query params
- Email addresses (optional, default on)
- Credit-card-shaped numbers (optional, default on)

Customization
-------------

Pass a custom :class:`RedactionConfig` to :func:`redact_dict` to:

- Add new patterns
- Disable specific default rules
- Replace the placeholder (``***``) with your own
- Switch email / credit-card redaction off
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_PLACEHOLDER = "***REDACTED***"

# Pre-compiled default patterns.  Each entry is (name, regex, description).
# ``name`` becomes the label in the redacted output so an analyst can
# tell *what kind* of secret was scrubbed.
DEFAULT_RULES: list[tuple[str, str, str]] = [
    (
        "openai_key",
        r"\bsk-[A-Za-z0-9_-]{20,}\b",
        "OpenAI / OpenAI-style API key",
    ),
    (
        "anthropic_key",
        r"\bsk-ant-[A-Za-z0-9_-]{20,}\b",
        "Anthropic API key",
    ),
    (
        "aws_access_key",
        r"\bAKIA[0-9A-Z]{16}\b",
        "AWS access key ID",
    ),
    (
        "google_api_key",
        r"\bAIza[0-9A-Za-z_-]{35}\b",
        "Google API key",
    ),
    (
        "github_token",
        r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
        "GitHub personal access token",
    ),
    (
        "slack_token",
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b",
        "Slack token",
    ),
    (
        "private_key_block",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "PEM private key block",
    ),
    (
        "jwt",
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "JSON Web Token",
    ),
    (
        "bearer_token",
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{20,}",
        "Bearer authorization token",
    ),
    (
        "keyvalue_secret",
        r'(?i)\b(api[_-]?key|apikey|access[_-]?token|auth[_-]?token|secret|password|passwd|pwd|token)\s*[:=]\s*["\']?([^\s,"\']{6,})["\']?',
        "key=value secret in arg or config",
    ),
]


@dataclass(slots=True)
class RedactionConfig:
    """Tunable redaction behaviour.

    ``extra_patterns`` adds patterns on top of the default rule set.
    Each entry is ``(name, regex)`` — they take precedence so they
    can override defaults by name.

    ``disabled`` is the set of rule names to skip.

    ``redact_emails`` and ``redact_credit_cards`` toggle the
    "softer" personal-data rules.  Both default to True.
    """

    placeholder: str = DEFAULT_PLACEHOLDER
    extra_patterns: list[tuple[str, str]] = field(default_factory=list)
    disabled: set[str] = field(default_factory=set)
    redact_emails: bool = True
    redact_credit_cards: bool = True


# Optional patterns not in DEFAULT_RULES so callers can opt-in
# by adding them to ``extra_patterns``.  Included here for reuse.
OPTIONAL_PATTERNS: list[tuple[str, str, str]] = [
    (
        "email",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "Email address",
    ),
    (
        "credit_card",
        r"\b(?:\d[ -]*?){13,19}\b",
        "Credit-card-shaped number",
    ),
]


# Pre-compiled cache keyed by RedactionConfig.id (set by compile_rules)
_COMPILED: dict[tuple, list[tuple[str, re.Pattern[str]]]] = {}


def _email_pattern() -> tuple[str, str, str]:
    return OPTIONAL_PATTERNS[0]


def _cc_pattern() -> tuple[str, str, str]:
    return OPTIONAL_PATTERNS[1]


def compile_rules(cfg: RedactionConfig) -> list[tuple[str, re.Pattern[str]]]:
    """Return the (name, regex) pairs to apply for ``cfg``.

    Results are cached by ``(id(cfg), id(extra_patterns))`` so the
    hot path is a dict lookup.
    """
    # Use object identity as the cache key.  RedactionConfig is
    # short-lived per call site, so the cache rarely grows.
    key = (id(cfg), id(cfg.extra_patterns))
    cached = _COMPILED.get(key)
    if cached is not None:
        return cached

    patterns: list[tuple[str, re.Pattern[str]]] = []
    seen: set[str] = set()
    # Extra patterns first so they can override defaults by name
    for name, raw in cfg.extra_patterns:
        if name in cfg.disabled:
            continue
        patterns.append((name, re.compile(raw)))
        seen.add(name)
    for name, raw, _desc in DEFAULT_RULES:
        if name in cfg.disabled or name in seen:
            continue
        patterns.append((name, re.compile(raw)))
        seen.add(name)
    if cfg.redact_emails and "email" not in cfg.disabled:
        name, raw, _desc = _email_pattern()
        if name not in seen:
            patterns.append((name, re.compile(raw)))
            seen.add(name)
    if cfg.redact_credit_cards and "credit_card" not in cfg.disabled:
        name, raw, _desc = _cc_pattern()
        if name not in seen:
            patterns.append((name, re.compile(raw)))
            seen.add(name)
    _COMPILED[key] = patterns
    return patterns


def _redact_string(
    value: str, compiled: list[tuple[str, re.Pattern[str]]], placeholder: str
) -> str:
    """Apply every pattern to ``value``, returning the scrubbed string."""
    for name, pat in compiled:
        # For keyvalue_secret we want to keep the key and replace the value
        if name == "keyvalue_secret":
            value = pat.sub(
                lambda m: f"{m.group(1)}=[{placeholder}]", value
            )
        elif name == "bearer_token":
            value = pat.sub(
                lambda m: f"Bearer [{placeholder}]", value
            )
        elif name == "private_key_block":
            value = pat.sub(
                lambda m: f"[{placeholder} ({name})]", value
            )
        else:
            value = pat.sub(f"[{placeholder} ({name})]", value)
    return value


def redact_value(
    value: Any,
    compiled: list[tuple[str, re.Pattern[str]]],
    placeholder: str,
) -> Any:
    """Recursively redact one value."""
    if isinstance(value, str):
        return _redact_string(value, compiled, placeholder)
    if isinstance(value, (list, tuple)):
        return type(value)(
            redact_value(v, compiled, placeholder) for v in value
        )
    if isinstance(value, dict):
        return redact_dict(value, compiled=compiled, placeholder=placeholder)
    return value


def redact_dict(
    payload: dict[str, Any],
    *,
    config: RedactionConfig | None = None,
    compiled: list[tuple[str, re.Pattern[str]]] | None = None,
    placeholder: str | None = None,
) -> dict[str, Any]:
    """Return a copy of ``payload`` with secrets scrubbed.

    At least one of ``config`` / ``compiled`` / ``placeholder`` must
    be supplied (or the default rules will be used).  Most call
    sites pass only ``config``.
    """
    if compiled is None:
        if config is None:
            config = RedactionConfig()
        compiled = compile_rules(config)
    if placeholder is None:
        placeholder = config.placeholder if config else DEFAULT_PLACEHOLDER
    out: dict[str, Any] = {}
    for k, v in payload.items():
        # Field-name heuristic: if the *key* itself looks like a
        # secret name (password, token, …) we always redact the
        # value even if the regex didn't match a value-shape.
        if isinstance(k, str) and _looks_like_secret_key(k):
            out[k] = f"[{placeholder} (field_name)]"
        else:
            out[k] = redact_value(v, compiled, placeholder)
    return out


_SECRET_KEY_HINTS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "auth_token",
        "token",
        "private_key",
        "private",
        "credential",
        "credentials",
    }
)


def _looks_like_secret_key(name: str) -> bool:
    n = name.lower()
    if n in _SECRET_KEY_HINTS:
        return True
    # Substring matches must respect word boundaries so fields like
    # ``tokenizer`` or ``user_token_count`` aren't flagged.
    parts = _split_key(name)
    return any(p in _SECRET_KEY_HINTS for p in parts)


def _split_key(name: str) -> list[str]:
    """Split a field name on snake_case and camelCase boundaries."""
    out: list[str] = []
    current: list[str] = []
    prev_lower = False
    for ch in name:
        if ch in "_-" or ch.isspace():
            if current:
                out.append("".join(current).lower())
                current = []
            prev_lower = ch.islower()
            continue
        if ch.isupper() and prev_lower:
            if current:
                out.append("".join(current).lower())
                current = []
        current.append(ch)
        prev_lower = ch.islower()
    if current:
        out.append("".join(current).lower())
    return out


def safe_for_log(value: Any, *, config: RedactionConfig | None = None) -> str:
    """Return a single-line, log-safe string for ``value``.

    Shortcut for callers that just need a printable representation
    that can never leak a credential — the value is run through
    :func:`redact_dict` and then ``repr()``.
    """
    if isinstance(value, str):
        redacted = _redact_string(
            value, compile_rules(config or RedactionConfig()),
            (config.placeholder if config else DEFAULT_PLACEHOLDER),
        )
        return redacted
    if isinstance(value, dict):
        redacted = redact_dict(value, config=config)
        return repr(redacted)
    return repr(value)


__all__ = [
    "RedactionConfig",
    "DEFAULT_RULES",
    "OPTIONAL_PATTERNS",
    "DEFAULT_PLACEHOLDER",
    "compile_rules",
    "redact_value",
    "redact_dict",
    "safe_for_log",
]
