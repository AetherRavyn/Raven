---
name: Home Protection
module_id: skill.home.protection
version: 1.2.0
category: tool
origin: community
trust_level: community
---

# Home Protection

Camera-based home surveillance module and the platform's driving worked example:
a single `module.yaml` manifest contributes **five** capabilities from one module.

| Contribution         | Type                | Entry point                  | Notes |
| -------------------- | ------------------- | ---------------------------- | ----- |
| `front_door_camera`  | `event_source`      | `sources.py:FrontDoorCamera` | Emits frame events for the front-door camera. |
| `stranger_detector`  | `anomaly_detector`  | `detectors.py:StrangerDetector` | Listens to `front_door_camera`, raises a CRITICAL event for strangers. |
| `snapshot_tool`      | `tool`              | `tools.py:SnapshotTool`      | Captures a still frame on demand. |
| `intruder_response`  | `proactive_reaction`| _(manifest condition only)_  | When a high-confidence stranger appears, snapshot + notify the operator. |
| `camera_panel`       | `ui_surface`        | `panel.py:render_panel`      | Renders a small dashboard panel. |

## Trust and least privilege

- `trust_level: community` — the least-trusted tier.
- `enabled_by_default: false` — a community module that reads a camera must be
  explicitly enabled by the operator; nothing starts watching on install.
- `required_permissions: [camera.read, notify.operator]` — brokered before the
  capability bundle is registered.
- `required_secrets: [CAMERA_RTSP_URL]` — presence is checked (never the value)
  before registration.

## Compatibility note

The design document writes `min_ravyn_version: "2.0.0"`, but the running
platform reports version ~`0.1.0` (see `loader._running_version`). Because
`validate_manifest` rejects a manifest whose `min_ravyn_version` exceeds the
running version, this module pins `compatibility.min_ravyn_version: "0.1.0"` so
the worked example actually validates and loads today.

See `module.yaml` for the full specification.
