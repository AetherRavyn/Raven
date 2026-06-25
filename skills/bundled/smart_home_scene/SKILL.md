---
name: Smart Home Scene Manager
module_id: skill.bundled.smart_home_scene
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "create.*scene|activate.*scene"
    confidence: 0.85
  - pattern: "turn.*lights|dim.*lights"
    confidence: 0.80
capabilities: [scene-management, device-control, automation]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Smart Home Scene Manager

Create, activate, and manage smart home scenes and automations.

## Procedure
1. Use `smart_home` tool to list entities or call services
2. For scenes: `create_scene` with device states
3. For automations: `create_automation` with triggers and actions
4. For groups: `group_control` to control multiple devices
