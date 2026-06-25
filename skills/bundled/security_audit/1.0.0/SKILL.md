---
name: Security Audit
module_id: skill.security_audit
version: 1.0.0
category: skill
description: Comprehensive security audit for codebases and infrastructure
tags: [security, audit, vulnerabilities, scanning]
enabled_by_default: true
---

# Security Audit

## When to Use
Activate when the user requests a security audit, vulnerability scan, or
when new code is being deployed to production.

## Procedure

### Step 1: Scope Assessment
1. Identify what to audit (codebase, infrastructure, network, or all)
2. Check for dependency manifest files (requirements.txt, package.json, Cargo.toml)
3. Identify exposed services and ports

### Step 2: Dependency Scan
1. Check for known CVEs in dependencies
2. Identify outdated packages with known vulnerabilities
3. Flag packages with no recent maintenance

### Step 3: Code Analysis
1. Search for hardcoded secrets (API keys, passwords, tokens)
2. Check for SQL injection vectors
3. Review authentication and authorization patterns
4. Identify insecure deserialization
5. Check for path traversal vulnerabilities

### Step 4: Infrastructure Review
1. Check Docker configurations for security issues
2. Review network exposure (open ports, firewall rules)
3. Verify TLS/SSL configurations
4. Check file permissions

### Step 5: Report
```
🔒 Security Audit Report — [Date]

## Scope: [what was audited]

### 🔴 Critical Findings
- [CVE or issue with remediation steps]

### 🟡 Warnings
- [Security concern with recommendation]

### ✅ Passing Checks
- [What's secure and well-configured]

### 📋 Recommendations
1. [Priority action item]
2. [Secondary action item]

Overall Risk Level: [LOW/MEDIUM/HIGH/CRITICAL]
```
