---
name: Code Review Pipeline
module_id: skill.bundled.code_review_pipeline
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "review.*code|code.*review"
    confidence: 0.85
  - pattern: "check.*diff|what.*changed"
    confidence: 0.80
capabilities: [code-review, security-scan, quality-check]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Code Review Pipeline

Automated multi-stage code review with security scanning.

## Procedure

### Step 1: Get the Diff
Use `git_tool` to get recent changes (diff, log, changed files)

### Step 2: Analyze Changes
1. Read changed files and understand context
2. Check for security issues (hardcoded secrets, injection risks)
3. Check for code quality (naming, complexity, duplication)

### Step 3: Run Tests
Use `sandbox_exec` to run the test suite if available

### Step 4: Generate Review
Format as structured review:
- Summary of changes
- Security findings (if any)
- Code quality observations
- Suggested improvements
- Test results
