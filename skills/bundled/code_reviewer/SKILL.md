---
name: Code Reviewer
module_id: skill.code_reviewer
version: 1.0.0
category: skill
description: Analyzes code for bugs, style, performance, and security issues
tags: [code-review, quality, bugs, security, style]
capabilities: [code-analysis, bug-detection, style-check, security-review]
trust_level: workspace
enabled_by_default: true
---

# Code Reviewer

## When to Use
Activate when the user asks to review code, check a PR, or analyze code quality.

## Procedure

### Step 1: Gather Context
1. Read the code file(s) using `file_operations`
2. Check git diff if available using `git_ops`
3. Identify the language and framework

### Step 2: Analyze
Review the code for:
- **Bugs**: Logic errors, null references, off-by-one errors, race conditions
- **Security**: SQL injection, XSS, hardcoded secrets, insecure deserialization
- **Performance**: N+1 queries, unnecessary loops, memory leaks, blocking I/O
- **Style**: Naming conventions, function length, code duplication, dead code
- **Architecture**: SOLID violations, tight coupling, missing abstractions

### Step 3: Report
Format findings as:
```
## Code Review Summary

### 🔴 Critical (must fix)
- [file:line] Description of issue
  → Suggested fix

### 🟡 Warning (should fix)
- [file:line] Description of issue
  → Suggested fix

### 🔵 Suggestion (nice to have)
- [file:line] Description of improvement
  → Suggested approach

### ✅ What's Good
- Positive observations about the code
```

## Example
**User**: "Review this Python function"
**Response**: Structured review with severity-tagged findings, code examples, and actionable fixes.
