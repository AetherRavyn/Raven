---
name: Git PR Review
module_id: skill.bundled.git_pr_review
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "review.*PR"
    confidence: 0.90
  - pattern: "review.*pull request"
    confidence: 0.90
  - pattern: "code review.*PR"
    confidence: 0.85
  - pattern: "check.*PR"
    confidence: 0.75
capabilities: [code-review, diff-analysis, pr-checking, git-log-analysis]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Git PR Review

Analyze git pull request diffs and provide structured code review feedback.

## When to Use
This skill activates when the user asks to review a PR, either by PR number/URL or by comparing git branches. It reads the diff, analyzes changes, and produces a structured review.

## Procedure

### Step 1: Get the Diff
1. If PR URL/number given: use `GitTool` with `gh` CLI to fetch PR diff
2. If branch names given: use `git diff main...feature-branch`
3. Parse the diff to understand: files changed, additions/deletions, file types

### Step 2: Analyze Changes
For each changed file:
1. Summarize what the change does (1-2 sentences)
2. Check for:
   - **Bugs**: logic errors, off-by-one, race conditions, null safety
   - **Security**: injection risks, hardcoded secrets, auth bypass
   - **Style**: violates project conventions, dead code, debug artifacts
   - **Performance**: N+1 queries, memory leaks, unnecessary allocations
   - **Testing**: missing tests, untested edge cases, low coverage
3. Rate each file: ✅ Looks good / ⚠ Minor issues / ❌ Needs work

### Step 3: Compose Review
```
🔍 PR Review — [#N] PR Title
📁 Files changed: [N] | ++[N] --[N]

📝 Overview
[1-3 sentence summary of what this PR does]

📂 Per-File Notes
  • path/to/file.py ✅ — [brief assessment]
  • path/to/file2.py ⚠ — [issue description]

🔴 Issues to Address
  • [severity] [file:line] — description
  • [suggestion for fix]

✅ What's Good
  • [well-structured aspect]
  • [good test coverage]
  • [clean implementation]

Decision: Approve / Changes requested / Comment
```

## Example

**Output:**
```
🔍 PR Review — [#42] Add user rate limiting
📁 Files changed: 3 | ++124 --12

📝 Overview
Implements token bucket rate limiting for the /api/v1/users endpoint
using Redis as the backend store.

📂 Per-File Notes
  • src/middleware/ratelimit.py ✅ — Clean implementation, well-documented
  • src/config.py ⚠ — RATE_LIMIT_DEFAULT env var missing default
  • tests/test_ratelimit.py ✅ — Good coverage, includes edge cases

🔴 Issues to Address
  • 🔴 src/middleware/ratelimit.py:47 — KeyError if REDIS_URL not set; add fallback
  • 🟡 src/config.py:12 — RATE_LIMIT_DEFAULT should default to 100, not empty string

✅ What's Good
  • Token bucket algorithm is correct
  • Redis TTL properly set
  • Unit tests cover burst and steady-state scenarios

Decision: Changes requested (2 minor items)
```

## Lessons Learned
- Always check for hardcoded test tokens/secrets in diffs
- Flag large PRs (>400 lines) — suggest splitting
- Check that new code follows existing patterns in the codebase
- Test files are as important as source files in reviews
