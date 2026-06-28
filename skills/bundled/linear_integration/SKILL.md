---
name: Linear Integration
module_id: skill.bundled.linear_integration
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "linear.*issue|create.*ticket|linear.*task"
    confidence: 0.90
  - pattern: "list.*linear.*issues|linear.*status"
    confidence: 0.85
capabilities: [linear, project-management, issue-tracking]
trust_level: user_config
enabled_by_default: false
stability: stable
---

# Linear Integration

Manage issues and projects in Linear via the Linear API.

## When to Use
Use when the user asks about Linear issues, wants to create/update issues, or search their Linear workspace.

## Procedure

### Create Issue
- Call `linear` with `action=create_issue`, `title=<title>`, and optional `description`, `team_id`, `priority`, `assignee`

### List Issues
- Call `linear` with `action=list_issues`, optional `team_id`, `status`, `assignee` filters

### Update Issue
- Call `linear` with `action=update_issue`, `issue_id=<id>`, and fields to update

### Search Issues
- Call `linear` with `action=search`, `query=<text>` to find issues by content

## Configuration
Requires `LINEAR_API_KEY` environment variable.
