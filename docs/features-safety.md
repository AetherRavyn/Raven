# Security & Safety Controls

Giving an autonomous AI access to your home network, emails, and physical environment requires uncompromising security. RAVEN implements a strict Defense-in-Depth architecture with 7 security layers: identity verification, tool capability gating, approval tiering, sandbox execution, secret encryption, prompt injection defense, and immutable audit logging.

## 1. Policy System

RAVEN has three policy enforcement layers that run in sequence for every tool execution:

### PolicyEngine (Legacy) — `app/core/policy.py`

The `PolicyEngine` evaluates tool calls against capability-based permissions and risk levels.

```python
@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""
    permissions_missing: list[str] = field(default_factory=list)
```

The engine checks:
1. **Capability Declaration**: Tool must declare a `ToolCapability` with `required_permissions`, `risk_level`, and `confirmation_policy`
2. **Permission Grant**: Tool's required permissions must be a subset of granted permissions (`TOOL_USER_PERMISSIONS` + `TOOL_AGENT_PERMISSIONS`)
3. **Risk Escalation**: Tools with `risk_level == "high"` or `"critical"` automatically require confirmation
4. **Confirmation Policy**: Tools with `confirmation_policy == "always"` always require user confirmation

Default policies are stored in `workspace/state/policies.json`:
```json
{
    "bash": {"requires_approval_if_contains": ["rm", "mv", "sudo"]},
    "edge_device": {"requires_approval_if_match": {"operation": "dispatch_task"}},
    "file_operations": {"requires_approval_if_match": {"operation": "delete"}},
    "docker_exec": {"requires_approval_if_not_none": ["mount_dir"]},
    "computeruse": {"requires_approval_if_in": {"operation": ["click", "type"]}}
}
```

### PolicyEngine V2 — `app/core/policy_v2/`

The v2 policy engine provides structured evaluation with trust store and approval store:

| Component | File | Description |
|---|---|---|
| `PolicyEngine` | `app/core/policy_v2/engine.py` | Central evaluator; emits verdicts (ALLOW, ASK, DENY) |
| `TrustStore` | `app/core/policy_v2/store.py` | Tracks tool/user/action trust levels over time |
| `ApprovalStore` | `app/core/policy_v2/store.py` | Manages approval requests and responses |
| `PolicyRequest` | `app/core/policy_v2/types.py` | Input dataclass: user_id, action, target, args |
| `Verdict` | `app/core/policy_v2/types.py` | Output: ALLOW, ASK (requires approval), DENY |

Enabled via `RAVEN_POLICY_V2=true` env var.

### PolicyCache — `app/core/policy_cache.py`

Caches recent policy decisions to avoid redundant evaluation for repeated tool calls (e.g., multiple file reads in a loop). Cache TTL is configurable.

## 2. Tool Execution Tiers

Every tool declares its security profile via `ToolCapability`:

```python
# Example from SandboxExecTool (app/tools/sandbox.py:59)
def get_capabilities(self) -> ToolCapability:
    return ToolCapability(
        required_permissions=["shell.exec", "fs.read", "fs.write"],
        risk_level="high",
        confirmation_policy="always" if not Config.ALLOW_HOST_SHELL_EXECUTION else "confirm",
        readonly=False
    )
```

### Complete Security Metadata per Tool

| Tier | Risk Level | Readonly | Confirmation Policy | Example Tools | Action |
|---|---|---|---|---|---|
| Tier 1 | `none` / `low` | Yes | `never` | weather, web_search, web_fetch, crypto_price, air_quality, rss_reader, translation | Immediate execution, no audit |
| Tier 1 | `low` | Yes | `never` | file_read, git_log, system_stats, sensor_read, wolfram_alpha | Immediate execution, audit log |
| Tier 2 | `medium` | Varies | `on_condition` | calendar_add, smart_home_control, email_draft, notion_create, reminder_set | Immediate + audit log; may require approval on specific operations |
| Tier 3 | `high` | No | `always` / `confirm` | shell_exec, file_delete, git_push, docker_exec, computer_use, financial_tx, edge_dispatch | Human-in-the-Loop required |
| Tier 3 | `critical` | No | `always` | sudo_commands, door_unlock, config_modify, data_wipe | Always blocked without explicit approval |

## 3. Human-in-the-Loop Flow

The approval system (`app/core/runtime.py:785`) manages tier 3 tool execution:

```
LLM requests tool → policy_engine.evaluate() → DENY with requires_confirmation=True
    → _queue_approval_request()
        → Creates TaskLedger entry with task_type="approval", status="pending_approval"
        → Stores function_name, args, session_id, tool_call_id
        → Returns tool result: "EXECUTION PAUSED: This action requires explicit user approval. Task ID: {task_id}"
        → Sends notification to user's primary platform
    → User responds with "raven approve {task_id}" or clicks inline button
        → TaskLedger updates status to "approved"
        → Re-executes the tool with original arguments
        → Continues the ReAct loop
    → User responds with "raven reject {task_id}" or "no"
        → TaskLedger updates status to "rejected"
        → Injects "Action rejected by user" into the LLM context
```

The approval request includes:
- Task ID (e.g., `app_a1b2c3d4`)
- Tool name and arguments (sensitive args like API keys are masked)
- Platform where approval was requested
- Session ID for context recovery

### Approval via Multiple Channels

| Channel | Method | Format |
|---|---|---|
| Telegram | Inline keyboard buttons | `[Approve] [Reject]` with callback data |
| Slack | Interactive message buttons | `[Approve] [Reject]` with action IDs |
| CLI | Command | `raven approve <task_id>` |
| Web Dashboard | Web UI button | Click approve/reject in task inbox |
| Discord | Buttons or command | `/raven approve <task_id>` |

## 4. Sandbox Executor

**File**: `app/tools/sandbox.py` (153 lines)

The `SandboxExecTool` executes shell commands safely. By default, it forces execution inside an ephemeral Docker container with only the workspace directory mounted. Host execution is only allowed when `Config.ALLOW_HOST_SHELL_EXECUTION` is True AND the caller passes `force_host=True`.

### Resource Limits

| Resource | Container Default | Host Fallback (if allowed) |
|---|---|---|
| CPU | Unbounded (host default) | N/A |
| Memory | 512MB (Docker default) | N/A |
| Timeout | 60 seconds (configurable) | 60 seconds |
| Output Size | 50KB stdout / 50KB stderr | 50KB |
| Filesystem | Workspace mounted read-only | Workspace directory only |
| Network | Enabled (can be disabled) | Enabled |
| Processes | Isolated in container | Subprocess management |

### Docker Sandbox Execution

```python
async def _run_docker(self, command: str, image: str, timeout: int) -> dict:
    container_name = f"raven-sandbox-{uuid.uuid4().hex[:8]}"
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--name", container_name,
             "-v", f"{self.workspace_dir}:/workspace:ro",
             "--network", "none",  # No network by default
             "--memory", "512m",
             "--pids-limit", "100",
             image, "sh", "-c", command],
            capture_output=True, text=True, timeout=timeout,
        )
        return {"success": result.returncode == 0,
                "output": result.stdout[:50000],
                "error": result.stderr[:50000],
                "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out after {timeout}s"}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name],
                       capture_output=True, timeout=10)
```

## 5. SecretVault

**File**: `app/core/secret_vault.py` (189 lines)

The `SecretVault` provides Fernet symmetric encryption (AES-128-CBC with HMAC-SHA256) for secrets management.

### Key Management

The master key is derived from (in priority order):
1. `RAVYN_MASTER_KEY` environment variable (recommended)
2. Auto-generated key stored at `~/.raven/vault.key` (permissions: `0o600`, owner-only read/write)

Key derivation:
```python
derived = hashlib.sha256(raw_key.encode("utf-8")).digest()
fernet_key = base64.urlsafe_b64encode(derived)
```

### Vault File

- **Path**: `workspace/secrets/vault.enc`
- **Format**: JSON-encrypted blob (encrypted JSON dict of `key: value` pairs)
- **Encryption**: Fernet (symmetric, authenticated encryption)

### API

```python
vault = SecretVault()
vault.store("OPENAI_API_KEY", "sk-...")     # Encrypt and persist
key = vault.retrieve("OPENAI_API_KEY")       # Decrypt and return
vault.list_keys()                            # List all stored key names
vault.delete("OPENAI_API_KEY")               # Remove a secret
vault.has("OPENAI_API_KEY")                  # Check existence
vault.export_to_env()                        # Return all secrets as dict
vault.inject_to_environ()                    # Inject into os.environ
vault.count()                                # Number of stored secrets
```

### Service Isolation

Secrets are isolated per service. Each service's credential is stored under a unique key following the convention `{service_name}` (e.g., `openai`, `anthropic`, `telegram_bot`). The `CredentialsResolver` (`app/core/security.py:17`) provides a unified interface:

```python
resolver = CredentialsResolver(vault)
key = resolver.get("openai", env_var="OPENAI_API_KEY", default=None)
key = resolver.get_required("anthropic", env_var="ANTHROPIC_API_KEY")
```

Known credentials that can be vault-stored:
`openai`, `anthropic`, `gemini`, `google`, `openrouter`, `groq`, `xai`, `opencode_zen`, `virustotal`, `telegram_bot`, `discord_bot`, `slack_bot`, `slack_app`, `deepgram`, `home_assistant`, `notion`, `openweathermap`

### Edge Cases

- **No cryptography package**: Falls back to base64 encoding (logged warning)
- **Corrupted vault file**: Returns empty dict; logs warning
- **Key rotation**: Delete vault file and re-store secrets with new key
- **Bootstrap**: First call auto-generates key file if no master key is set

## 6. Command Sanitizer

The command sanitizer (`app/core/security.py`, `app/tools/sandbox.py`) applies multiple layers of filtering to shell commands:

### Dangerous Pattern Detection

Patterns that trigger automatic denial:
- `rm -rf /`, `rm -rf /*` — destructive file removal
- `:(){ :|:& };:` — fork bomb
- `> /dev/sda`, `dd if=/dev/zero` — disk destruction
- `chmod 777 /`, `chown -R` — permission escalation
- `wget | sh`, `curl | bash` — remote code execution
- `sudo`, `su -` — privilege escalation
- `mkfs`, `fdisk`, `parted` — partition manipulation

### Allowlist/Blocklist

- **Command allowlist**: Docker container base commands (ls, cat, echo, python, node, npm, git, pip, etc.)
- **Argument validation**: Path arguments are resolved against workspace directory; `..` traversal is blocked
- **Network commands**: Blocked by default in sandbox mode (container `--network none`)

## 7. Prompt Injection Defense

**File**: `app/core/security.py` (528 lines)

The adversarial input filter pre-processes all untrusted inputs (web pages, emails, documents, user messages) before they reach the LLM:

### Detection Patterns

The filter detects and neutralizes:
- "Ignore previous instructions" patterns
- "You are now acting as..." role-play injections
- System prompt override attempts
- Delimiter escape attempts
- Multi-shot prompt extraction attempts
- Base64-encoded instruction injection
- Unicode homoglyph attacks

### Delimiting Strategy

```python
# Wraps untrusted content in strict boundaries
UNTRUSTED_CONTENT_START = "---[BEGIN UNTRUSTED CONTENT]---"
UNTRUSTED_CONTENT_END = "---[END UNTRUSTED CONTENT]---"
```

All web-extracted content, email bodies, documents, and third-party data are wrapped in these delimiters. The system prompt instructs the model to treat content between these markers as data, not instructions.

### Output Validation

Before sending a response to the user, the security guard validates:
- No leaked system prompts or internal instructions
- No exposed API keys or credentials
- No private contact information
- No harmful content (weapons, violence, illegal activity)
- Content matches the expected domain of the current conversation

## 8. Audit Trail

### Database Schema

The audit system (`app/core/audit/`) uses an append-only JSONL file with an in-memory query cache:

```python
@dataclass
class AuditEvent:
    id: str                    # UUID
    kind: AuditKind            # policy, tool_call, agent, system
    actor: str                 # user_id, agent_name, "system"
    action: str                # tool name, event name
    target: str                # file path, command, URL
    context: dict              # session_id, platform, metadata
    success: bool              # True/False
    detail: str                # Error message or success detail
    risk_level: RiskLevel      # low, medium, high, critical
    timestamp: str             # ISO 8601
```

Audit kinds: `policy`, `tool_call`, `agent`, `system`, `privacy`, `approval`, `error`

Storage:
- **Primary**: JSONL file (`workspace/audit.log`) — append-only, grep-able
- **Secondary**: In-memory list for fast queries (rebuilt from JSONL on demand)
- **Optional**: HelixDB graph nodes for cross-host queries

### Querying

```python
from app.core.audit import AuditLog
log = AuditLog(jsonl_path="workspace/audit.log")

# Query by time range
events = log.query(
    start="2026-06-01T00:00:00Z",
    end="2026-06-02T00:00:00Z",
)

# Query by kind
policy_events = log.query(kind="policy")

# Query by risk level
high_risk = log.query(risk_level="high")

# Aggregate stats
stats = log.aggregate()  # Counts by kind, risk_level, success/failure
```

### Retention

- **Default retention**: 90 days
- **Auto-rotation**: When file exceeds 100MB, compressed to `.audit.log.gz`
- **Manual purge**: `log.purge(before="2026-03-01T00:00:00Z")`
- **Export**: `log.export("audit_export.json")`

## 9. Degraded Mode

**File**: `app/core/degraded_mode.py` (160 lines)

The `DegradationDetector` monitors provider health and enters degraded mode when providers are unreachable:

### Fallback Behaviors per Failure Type

| Failure Type | Degraded Mode | Fallback Action |
|---|---|---|
| Local provider down (< 30s) | Cloud-only | Skip small model; route directly to cheap model |
| Local provider down (> 30s) | Cloud-only with warning | Notify user; use cloud only until local recovers |
| Cloud provider down | Local-only | Use local model; reduced capability for complex tasks |
| All providers down | Fully down | Return cached response for same intent hash, or `REBOOT_BANNER` |
| Network failure | Connection-limited | Queue requests; retry on reconnect |
| Policy engine failure | Fail-open | Legacy policy engine still runs; log error |
| Audit log write failure | Fail-open | Log warning; continue execution; recover on next write |

### Degradation Status

```python
@dataclass(slots=True)
class DegradationStatus:
    local_healthy: bool
    cloud_healthy: bool
    local_down_long: bool       # True if local down > tiny_down_threshold_s
    banner: str                 # User-facing message in fully-down mode
    local_down_since: float     # Epoch seconds when local went down

    @property
    def fully_down(self) -> bool:
        return (not self.local_healthy) and (not self.cloud_healthy)

    @property
    def cloud_only(self) -> bool:
        return (not self.local_healthy) and self.cloud_healthy
```

### REBOOT_BANNER

When all providers are down, every request returns:
```
"I'm rebooting my brain — give me 30 s and try again."
```

## 10. Platform Authentication

- **Platform Whitelisting**: `TELEGRAM_ALLOWED_USERS`, `DISCORD_ALLOWED_ROLES`, `SLACK_ALLOWED_USERS` enforce RBAC at the connector level. Unauthorized messages are dropped before reaching BotSignal.
- **Speaker Verification**: `app/voice/speaker_id.py` uses fast speaker-embedding to verify voice matches registered owner before sensitive commands.
- **User Identity**: `app/core/user_identity.py` manages multi-platform user identity mapping.
- **Credential Pools**: `app/core/credential_pools.py` manages API keys and service credentials securely.

## 11. Network Isolation

- **No Inbound Ports**: RAVEN uses outbound WebSocket connections or long-polling for all external communication
- **Local Processing**: STT, TTS, and local LLM inference never leave the host machine
- **MQTT Isolation**: Internal MQTT broker for sensor data stays on local network
- **Docker Network Isolation**: Sandbox containers have `--network none` by default
- **DNS Filtering**: Optionally route through filtered DNS to block known malicious domains

## 12. Configuration

```ini
# Permission grants
TOOL_USER_PERMISSIONS=shell.exec,fs.read,fs.write,network.connect,calendar.read
TOOL_AGENT_PERMISSIONS=fs.read,fs.write,network.connect

# Vault
RAVYN_MASTER_KEY=your-master-key-here
RAVEN_VAULT_ENABLED=true

# Policy v2
RAVEN_POLICY_V2=true
RAVEN_POLICY_STATE_DIR=workspace/state

# Audit
RAVEN_AUDIT_V2=true
RAVEN_AUDIT_PATH=workspace/audit.log

# Sandbox
ALLOW_HOST_SHELL_EXECUTION=false
DOCKER_SANDBOX_IMAGE=ubuntu:22.04

# Approval
APPROVAL_TIMEOUT_HOURS=24
APPROVAL_DEFAULT_CHANNEL=telegram

# Degraded mode
DEGRADATION_THRESHOLD_SECONDS=30
```
