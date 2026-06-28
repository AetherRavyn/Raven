---
name: ACP Protocol
module_id: skill.bundled.acp_protocol
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "ide.*connect|acp.*protocol|agent.*protocol"
    confidence: 0.90
  - pattern: "external.*tool|editor.*integration"
    confidence: 0.80
capabilities: [acp, ide-integration, protocol]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Agent Communication Protocol (ACP)

Communicate with external tools (IDEs, editors, CI/CD) via the ACP endpoint.

## When to Use
Use when the user wants to integrate with an IDE, check ACP connectivity, execute commands on external request, or search conversations for an external tool.

## Procedure

### Check Connectivity
- Call `acp` with `action=ping` to verify ACP is responding

### Execute Commands
- Call `acp` with `action=execute` and `command=<shell command>`
- Returns stdout, stderr, and return code (max 30s timeout)

### List Available Tools
- Call `acp` with `action=list_tools` to discover what tools the agent has

### Read Files
- Call `acp` with `action=read_file` and `filepath=<path>`
- Returns file contents (max 100KB)

### Search Conversations
- Call `acp` with `action=search` and `query=<text>`
- Searches across all conversation sessions

## External Usage
External tools (IDEs, editors) can POST directly to the `/acp` endpoint:
```json
POST /acp
{
  "action": "execute",
  "params": {"command": "python script.py"}
}
```

## Dependencies
- FastAPI server running
