---
name: code_reviewer
description: A workflow to systematically review code and suggest improvements.
version: 1.0.0
author: RAVEN
type: workflow
---

# Code Reviewer Workflow

## Overview
This workflow instructs the agent on how to properly review software code to ensure quality, security, and adherence to best practices.

## Workflow Steps

1. **Understand Context**: Read the provided code snippet or the modified files. Identify the core language and framework.
2. **Security Check**: Look for obvious security vulnerabilities like hardcoded secrets, SQL injections, XSS patterns, and unsafe dependencies.
3. **Performance Check**: Identify nested loops, unnecessary API calls, and missing indexes or memory leaks.
4. **Style Check**: Verify that the code follows standard idioms for the language (e.g., PEP 8 for Python).
5. **Report**: Format the findings using Markdown with clear headers for Security, Performance, and Style. Provide actionable suggestions for each finding.
