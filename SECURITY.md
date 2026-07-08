# Security Policy

> **Last updated**: 2026-06-30

---

## Supported Versions

| Version | Supported | Status |
|---------|-----------|--------|
| 1.0.x | ✅ Fully supported | Current stable release |
| 0.5.x | ⚠️ Security patches only | End of life |
| < 0.5 | ❌ Not supported | End of life |

Users are strongly encouraged to run the latest stable release. Security patches are backported to the previous minor version for 90 days after a new minor release.

---

## Reporting a Vulnerability

We take security seriously. If you discover a vulnerability in Raven, please report it privately.

### How to Report

**DO NOT** file a public GitHub issue for security vulnerabilities.

Instead, contact the maintainers directly:

- **Email**: security@ravynai.com (PGP key available on request)
- **GitHub**: Use the Security Advisory feature at `https://github.com/AetherRavyn/Raven/security/advisories/new`

### What to Include

- Type of vulnerability (XSS, command injection, privilege escalation, etc.)
- Full reproduction steps — include environment details, configuration, and payload
- Affected versions and components
- Potential impact
- Suggested fix (if known)

### Response Timeline

| Timeframe | Action |
|-----------|--------|
| 24 hours | Acknowledgment of receipt |
| 7 days | Initial assessment and severity classification |
| 30 days | Fix developed and tested (critical) |
| 90 days | Fix released (moderate/low) |

### Disclosure Policy

We follow **coordinated disclosure**:

1. Reporter submits vulnerability
2. Maintainers develop and test a fix
3. Fix is released in a new version
4. CVE is published
5. Reporter is credited (if desired)
6. Full details are published 30 days after the fix

---

## Security Practices in the Codebase

### 1. Tool Execution — 4-Layer Security Pipeline

Every tool execution goes through four security layers:

```
Layer 1: Policy Engine (capability-based)
  └── Checks if the tool is allowed for the current context
Layer 2: Approval Manager (risk-tiered)
  └── Tier 0-3: auto-approve → human confirmation required
Layer 3: Command Sanitizer (pattern-based)
  └── Validates arguments against allow/deny patterns
Layer 4: Audit Logger (immutable JSONL)
  └── Records all tool calls for forensic analysis
```

**Risk Tiers:**

| Tier | Description | Action Required |
|------|-------------|----------------|
| 0 | Read-only, informational | Auto-approved |
| 1 | Non-destructive write | Auto-approved |
| 2 | Destructive write | Human confirmation |
| 3 | System modification | Strict human confirmation |

### 2. Outbound-Only Architecture

Raven requires **zero inbound ports**. All communication is outbound:
- WebSocket connections to platforms (Telegram, Discord, etc.)
- Long-polling for dashboard events
- HTTP client calls for APIs

This means:
- No open firewall ports required
- Works behind NAT and corporate proxies
- No surface for network-level attacks

### 3. Secret Management

- API keys and tokens stored in `.env` (excluded from git via `.gitignore`)
- `SecretVault` class provides Fernet AES-128-CBC encryption for sensitive data at rest
- Tokens are never logged or exposed in error messages
- `detect-secrets` pre-commit hook prevents accidental credential commits

### 4. Sandboxed Execution

- Shell commands run through `shlex.split()` to prevent injection
- Docker containers for sandboxed code execution when available
- Edge node tasks execute with restricted capabilities
- No `eval()` or `exec()` on untrusted input

### 5. Input Sanitization

- All platform messages are sanitized before processing
- HTML/emoji stripping for safety
- Command injection prevention via parameterized arguments
- Path traversal detection for file operations

### 6. Audit Logging

- All tool executions are logged to immutable JSONL files
- Log includes: timestamp, user_id, tool name, action, parameters, result, success/failure
- Logs cannot be modified after writing (append-only)
- Audit dashboard for review and export

### 7. Privacy Zones

Consent-gated data classification system:
- **Public**: No restrictions
- **Internal**: Restricted to authenticated users
- **Confidential**: Requires explicit consent
- **Restricted**: Requires admin approval

### 8. Dependency Security

- All dependencies audited via `pip-audit` in CI
- `detect-secrets` pre-commit hook
- Bandit SAST scanner for Python code
- Regular `uv sync` for dependency updates
- `pyproject.toml` pins major versions with range upper bounds

### 9. CI/CD Security

- GitHub Actions run on every PR and push to main
- `ruff` + `pyright` + `pytest` gates
- Secrets are never exposed in CI logs
- Dependabot configured for automated dependency updates
- Supply chain integrity via `uv.lock` and checksum verification

### 10. Identity & Authentication

- **Dashboard API**: Optional Bearer token authentication (`API_BEARER_TOKEN`)
- **Edge Nodes**: Capability-based registration with server-side validation
- **Platform Connectors**: Bot tokens with platform-native permission scopes
- **DM Pairing**: Six-digit code + manual approval flow

---

## Responsible Disclosure

We encourage:

- **Researchers** to report vulnerabilities through the process above
- **Users** to keep their installations updated
- **Administrators** to follow the principle of least privilege
- **Everyone** to use strong, unique API tokens

### What We Promise

- We will respond promptly and professionally
- We will fix confirmed vulnerabilities
- We will credit researchers (with permission)
- We will be transparent about impact

### Bug Bounties

Raven is a community open-source project and does not currently offer a bug bounty program. We are grateful for responsible disclosure and will publicly acknowledge contributors who report valid security issues.

---

## Security-Related Configuration

```bash
# Required: Set admin user IDs
ADMIN_USER_IDS=user_id_1,user_id_2

# Recommended: Enable dashboard authentication
API_BEARER_TOKEN=your_secure_token_here

# Optional: Enable sandboxed Docker execution
RAVEN_DOCKER_ENABLED=true

# Security monitoring
HIBP_API_KEY=  # Have I Been Pwned breach check
VIRUSTOTAL_API_KEY=  # URL/file scanning
```

---

## Known Security Limitations

- **Local mode**: When running with local models only, the system does not encrypt prompts (runs on your hardware)
- **Cloud providers**: Data sent to configured cloud LLM providers is subject to their privacy policies
- **Edge nodes**: Communication between server and edge nodes is HTTP (not HTTPS) in default configuration
- **Voice pipeline**: Wake word detection runs locally; voice data is processed on-device
