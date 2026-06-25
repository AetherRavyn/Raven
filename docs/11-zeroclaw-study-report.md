# ZeroClaw Study Report

Date: 2026-02-16  
Studied repo: `https://github.com/zeroclaw-labs/zeroclaw`  
Analyzed commit: `9d21e2b28c210cc643cf02abfb13c09353c7821b`

## 1. What ZeroClaw Is Doing

ZeroClaw is building a low-footprint Rust agent runtime that can:

- run as CLI, gateway, daemon, or channel worker
- connect to many model providers (OpenRouter, OpenAI, Anthropic, Gemini, Ollama, and many OpenAI-compatible endpoints)
- connect to many channels (Telegram, Discord, Slack, Matrix, iMessage, WhatsApp, etc.)
- execute tools (shell/file/git/http/browser/memory/schedule/screenshot/image/composio/delegation)
- enforce security policy around command execution, filesystem scope, and gateway auth

Main entry and command router:

- `src/main.rs`

Core reusable module exports:

- `src/lib.rs`

---

## 2. Architecture Pattern

ZeroClaw uses a **trait-driven architecture**. Most systems are pluggable interfaces:

- Provider trait: `src/providers/traits.rs`
- Channel trait: `src/channels/traits.rs`
- Tool trait: `src/tools/traits.rs`
- Memory trait: `src/memory/traits.rs`
- Runtime trait: `src/runtime/traits.rs`
- Observer trait: `src/observability/traits.rs`

This allows swapping implementations without rewriting the agent loop.

---

## 3. Runtime Flow (What Happens on a Message)

### Channel side

In `src/channels/mod.rs`, ZeroClaw:

1. starts listeners per channel with restart/backoff
2. receives messages into an internal queue
3. builds memory context from recall hits
4. runs tool-calling loop (`run_tool_call_loop`)
5. sends final response back through the same channel

### Gateway side

In `src/gateway/mod.rs`, ZeroClaw:

1. starts an Axum HTTP server
2. enforces body limits, timeout, and auth checks
3. applies rate limit + idempotency handling
4. runs the same provider/tool pipeline
5. returns normalized response

---

## 4. Providers (How LLM Access Is Built)

Provider factory and mapping:

- `src/providers/mod.rs`

Key points:

- has dedicated providers for major platforms
- supports many OpenAI-compatible providers via one adapter (`OpenAiCompatibleProvider`)
- resolves API key from provider-specific env vars first, then generic fallback env vars
- includes provider router (`src/providers/router.rs`) that can route `hint:*` model strings to specific provider/model combos

---

## 5. Tools (What Agent Can Do)

Tool registry assembly:

- `src/tools/mod.rs`

Tool sets:

- default tools: shell, file_read, file_write
- full tools: memory tools, schedule, git, browser, HTTP request, image/screenshot, composio, delegate

Security-aware tool implementations:

- shell: `src/tools/shell.rs`
- file read: `src/tools/file_read.rs`
- file write: `src/tools/file_write.rs`

---

## 6. Memory System

Memory factory:

- `src/memory/mod.rs`

Backends:

- sqlite (hybrid-style behavior with embedding + keyword support layers)
- markdown fallback

Includes hygiene and chunking modules:

- `src/memory/hygiene.rs`
- `src/memory/chunker.rs`
- `src/memory/sqlite.rs`

---

## 7. Security Model (Current Implementation)

Security policy and command risk model:

- `src/security/policy.rs`

Gateway pairing + bearer token flow:

- `src/security/pairing.rs`

Important behavior in code:

- command risk classification (low/medium/high)
- allowed command list and forbidden paths
- action rate limiting
- workspace-constrained file access
- gateway pairing with one-time code and stored token hashes
- shell tool clears environment and whitelists only safe env vars before execution

---

## 8. Runtime Adapters

Runtime factory:

- `src/runtime/mod.rs`

Implemented kinds:

- native: `src/runtime/native.rs`
- docker: `src/runtime/docker.rs`

Unsupported runtime kinds fail fast with explicit error.

---

## 9. Integrations Catalog

Integration registry:

- `src/integrations/registry.rs`

The catalog includes chat platforms, AI vendors, productivity apps, media/home integrations, and platform categories.  
Not all listed integrations are active implementations; some are `ComingSoon`.

---

## 10. CI/Operational Setup

Workflows folder:

- `.github/workflows/`

Has CI, security, docker, release, labeling, stale, and hygiene workflows.  
CI behavior documentation exists in:

- `docs/ci-map.md`

---

## 11. What Passed / What Failed in Study

### Passed

Library tests passed during study:

- command run: `cargo test --lib --quiet`
- result: `1439 passed; 0 failed`

### Failed

Full target compile failed:

- command run: `cargo check --all-targets`
- blocker found: duplicate `ModelCommands` enum definitions in `src/main.rs`
- references:
  - `src/main.rs:262`
  - `src/main.rs:276`

Minor warning also observed:

- unused import in `src/tools/git_operations.rs:558`

---

## 12. Key Strengths

- strong modular architecture via traits
- very broad tool/channel/provider surface
- serious security-aware implementation for shell/file/gateway
- high test volume and fast test execution for libs
- runtime and deployment flexibility (native + docker)

---

## 13. Key Risks / Gaps

- current HEAD has compile-blocking duplication in CLI enum
- docs include roadmap/proposal items that are not fully implemented yet
- very large module files (maintenance complexity risk), e.g.:
  - `src/onboard/wizard.rs`
  - `src/config/schema.rs`
  - `src/channels/mod.rs`
  - `src/tools/browser.rs`

---

## 14. Practical Takeaways for RAVEN

Useful patterns to reuse in RAVEN:

1. trait/interface boundaries for provider, channel, tool, memory
2. one central tool registry constructor
3. supervised channel worker loop with backoff and timeout
4. explicit gateway pairing/auth/rate-limit/idempotency layer
5. shell/file tool hardening (path canonicalization + env scrubbing)

This study report is meant as a direct implementation reference, not only a conceptual overview.
