---
title: "Sensor Awareness & IoT Integration"
---

# Sensor Awareness & IoT Integration

RAVEN operates as an ambient intelligence, constantly aware of its physical surroundings through MQTT, webhooks, camera feeds, and Home Assistant integration. It ingests sensor data from multiple sources, translates raw values into semantic context, and triggers proactive actions based on environmental conditions.

## 1. MQTT Subscriber Architecture

**File**: `app/sensors/mqtt_listener.py`

The async MQTT subscriber connects to any MQTT broker (Mosquitto, EMQX, etc.) using the `gmqtt` library. It subscribes to configured topics, parses incoming telemetry, stores readings in an in-memory state dict, and fires BotSignal alerts for anomalous values.

### Topic Subscription

```python
async def run_mqtt_listener(
    broker_url: str,
    topics: list[str],
    username: str = "",
    password: str = "",
) -> None:
```

The subscriber connects to the broker, subscribes to all configured topics (supporting MQTT wildcards `+` and `#`), and enters a receive loop. Each message is parsed as JSON (with fallback to raw string), stored in `_sensor_state[topic]`, and evaluated for anomaly conditions.

### Message Parsing

Messages are parsed with the following priority:
1. JSON object → stored as-is (supports nested sensor readings)
2. Numeric string → stored as `{"value": float_value}`
3. Raw string → stored as `{"value": string_value}`

Each stored reading is annotated with a timestamp.

### State Storage

The in-memory state is accessible via:
```python
def get_sensor_state() -> dict[str, dict]:
    """Return in-memory snapshot of all known sensor topics."""
    # Returns: {"raven/living_room/temp": {"temperature": 22.5, "unit": "c"}, ...}

def get_recent_readings() -> list[dict]:
    """Return recent readings as a list of dicts for the action engine."""
    # Returns: [{"topic": "...", "value": ..., "timestamp": "...", "payload": {...}}, ...]
```

### Alert Triggers

The MQTT listener evaluates incoming readings against threshold-based alerts:
- **Motion detected**: Payload containing `"motion": true` or `"event": "motion"` triggers an alert
- **Temperature extremes**: Values outside `TEMP_MIN`/`TEMP_MAX` (configurable, default: 10C-40C)
- **Security events**: Topics matching `security/` or `alarm/` patterns always trigger alerts
- **Custom patterns**: Configurable via `MQTT_ALERT_PATTERNS` env var (comma-separated topic patterns)

Alerts are dispatched as BotSignal messages to configured admin channels.

### MQTT Topic Structure Convention

RAVEN recommends a hierarchical topic structure:

```
raven/{zone}/{sensor_type}/{attribute}
```

| Example Topic | Description | Value Format |
|---|---|---|
| `raven/living_room/temp` | Living room temperature | `22.5` (float) |
| `raven/living_room/humidity` | Living room humidity | `45` (integer, percent) |
| `raven/kitchen/motion` | Kitchen motion sensor | `{"motion": true, "since": "2026-06-29T10:00:00Z"}` |
| `raven/front_door/contact` | Front door open/closed | `{"open": false}` |
| `raven/outside/temperature` | Outdoor temperature | `18.2` (float) |
| `raven/bedroom/light` | Bedroom ambient light | `320` (integer, lux) |
| `raven/office/air_quality` | Office air quality (VOC) | `{"voc": 120, "co2": 450, "pm25": 5}` |
| `raven/garage/door` | Garage door state | `{"position": "open"}` |
| `security/camera/front` | Front camera event | `{"event": "motion", "confidence": 0.95}` |
| `alarm/panic` | Panic alarm trigger | `{"triggered": true}` |

### Configuration

```ini
# MQTT broker
MQTT_BROKER_URL=mqtt://192.168.1.100:1883
MQTT_USERNAME=raven
MQTT_PASSWORD=your-mqtt-password
MQTT_TOPICS=raven/+/+,sensors/#,security/#

# Alert thresholds
MQTT_TEMP_MIN=10
MQTT_TEMP_MAX=40
MQTT_ALERT_PATTERNS=security/+,alarm/+
MQTT_ALERT_COOLDOWN_SECONDS=60
```

## 2. Webhook Server

**File**: `app/sensors/webhook_server.py`

A minimal FastAPI server (port 8765 by default) that accepts external sensor data, camera alerts, and Prometheus metrics scrapes.

### Endpoints

| Endpoint | Method | Description | Payload Format |
|---|---|---|---|
| `/internal/camera-alert` | POST | Camera motion/anomaly alert | `{"event": "person_detected", "camera": "front_door", "confidence": 0.92, "snapshot_path": "/tmp/snap.jpg"}` |
| `/webhook/{source}` | POST | Generic webhook integration | Arbitrary JSON (passed to BotSignal as event) |
| `/health` | GET | Server health check | `{"status": "ok"}` |
| `/metrics` | GET | Prometheus metrics endpoint | Prometheus text format |

### Camera Alert Processing

```python
@app.post("/internal/camera-alert")
async def camera_alert(request: Request):
    data = await request.json()
    from app.sensors.camera_bridge import handle_camera_alert
    asyncio.create_task(handle_camera_alert(data))
    return {"status": "queued"}
```

The webhook server runs on `127.0.0.1:8765` by default, configurable via `WEBHOOK_HOST` and `WEBHOOK_PORT` env vars. It is intended for internal network use only (localhost by default).

### Authentication

Webhook endpoints support optional authentication:
- **Static token**: `WEBHOOK_AUTH_TOKEN` env var; clients must pass `Authorization: Bearer <token>` header
- **IP whitelisting**: `WEBHOOK_ALLOWED_IPS` comma-separated list of allowed source IPs
- **Disabled by default**: No authentication required (intended for internal use)

## 3. Camera Bridge

**File**: `app/sensors/camera_bridge.py` (62 lines)

The camera bridge connects the external monitoring system (which runs YOLO detection on RTSP camera streams) to RAVEN's BotSignal.

### Alert Processing Flow

```
External monitoring → POST /internal/camera-alert → handle_camera_alert()
    → Parse event data (event type, camera name, confidence, snapshot path)
    → Format message for user
    → Send to all admin users via BotSignal
    → Broadcast to event digest system
```

```python
async def handle_camera_alert(event_data: dict) -> None:
    event = event_data.get("event", "unknown")
    camera = event_data.get("camera", "unknown")
    confidence = event_data.get("confidence", 0.0)
    snapshot_path = event_data.get("snapshot_path")

    text = f"Camera Alert — {event} detected on {camera} (confidence: {confidence:.0%})"
    botsignal = get_botsignal()

    for admin_id in Config.ADMIN_USER_IDS:
        # Format: "platform:chat_id" (e.g., "telegram:123456")
        if ":" in admin_id:
            platform, chat_id = admin_id.split(":", 1)
        else:
            platform, chat_id = "telegram", admin_id

        target = ReplyTarget(platform=platform, chat_id=chat_id)
        if snapshot_path:
            payload = SignalPayload(text=text, file_path=snapshot_path, caption=text)
        else:
            payload = SignalPayload(text=text)
        await botsignal.send(target, payload)
```

### Snapshot Forwarding

If `snapshot_path` is provided, the snapshot image is attached to the alert message. The image is sent as a file attachment through the platform connector (Telegram photo, Discord attachment, etc.).

### Event Digest

All camera alerts are broadcast to the event digest system (`app/core/event_digest.py`), which aggregates events over time and generates periodic digest reports. This prevents alert fatigue by grouping multiple events from the same camera into a single summary.

## 4. Home Assistant Integration

RAVEN integrates with Home Assistant via REST API and WebSocket.

### REST API (`app/tools/smarthometool.py`)

- **Read entity states**: `GET /api/states` → returns all entity states as JSON
- **Read single entity**: `GET /api/states/{entity_id}` → returns state, attributes, last_changed
- **Call service**: `POST /api/services/{domain}/{service}` → actuate devices
- **GET /api/config**: Home Assistant configuration metadata

```python
# Example: Toggle a light
result = await smart_home_tool.execute(
    operation="call_service",
    domain="light",
    service="toggle",
    service_data={"entity_id": "light.living_room"}
)
```

### WebSocket API (`app/sensors/ha_websocket.py`)

- Real-time event stream for instant state change notification
- Subscribes to `state_changed` events for monitored entities
- Pushes updates to BotSignal without polling
- Reconnects automatically on disconnect with exponential backoff

### SmartHomeTool (`app/tools/smarthometool.py`)

Agent-callable tool for querying and controlling Home Assistant entities:

| Operation | Description | Parameters |
|---|---|---|
| `get_states` | Get all entity states | None |
| `get_state` | Get single entity state | `entity_id` (string, required) |
| `call_service` | Call any HA service | `domain`, `service`, `service_data` (dict) |
| `turn_on` | Turn on an entity | `entity_id` (string, required) |
| `turn_off` | Turn off an entity | `entity_id` (string, required) |
| `toggle` | Toggle an entity | `entity_id` (string, required) |
| `set_value` | Set numeric value | `entity_id`, `value` (number) |

```python
ToolCapability(
    required_permissions=["home_automation"],
    risk_level="medium",
    cost_tier=CostTier.CHEAP,
    confirmation_policy="on_condition",
    readonly=True
)
```

### SensorReadTool (`app/tools/sensorreadtool.py`)

Direct sensor value queries — reads from both Home Assistant and MQTT sensor state:

```python
result = await sensor_read_tool.execute(
    entity_id="sensor.living_room_temperature"
)
# Returns: {"entity_id": "sensor.living_room_temperature",
#           "state": "22.5",
#           "attributes": {"unit_of_measurement": "°C", "friendly_name": "Living Room Temperature"},
#           "last_changed": "2026-06-29T10:00:00Z"}
```

## 5. Sensor Fusion & Context Injection

### Data Flow

```
Raw Sensor Data → Semantic Translation → Context Injection → LLM Awareness
```

**Step 1 — Raw Data Ingestion**: MQTT topic `home/living_room/temp` reports value `22.5`. This is stored in the in-memory sensor state dict as `{"temperature": 22.5, "unit": "c", "timestamp": "2026-06-29T10:00:00Z"}`.

**Step 2 — Semantic Translation**: The `EnvironmentalSensor` (`app/core/environmental_sensors.py:57`) translates raw readings into structured `SensorReading` objects and aggregates them into an `EnvironmentState`:

```python
@dataclass(slots=True)
class EnvironmentState:
    temperature: float | None = None    # Celsius
    humidity: float | None = None       # Percent (0-100)
    light_level: float | None = None    # Lux (0 to bright)
    noise_level: float | None = None    # Decibels
    air_quality: int | None = None      # AQI (0-500)
    presence: bool | None = None        # True if someone is home
    last_updated: str                   # ISO 8601
```

**Step 3 — Context Injection**: When a user asks a context-aware question, the environmental state is injected into the LLM's context:

```
User: "Is it hot in here?"
LLM Context: "Current environment: Living Room is 22.5°C (72.5°F), humidity 45%. 
              Outdoor temperature: 18°C."
```

**Step 4 — Proactive Action**: If temperature drops below threshold and no occupancy is detected, the system may trigger an energy-saving action (turn down thermostat).

### Supported Telemetry Types

| Sensor Type | Units | Source | Proactive Triggers |
|---|---|---|---|
| Temperature | °C / °F | MQTT, HA | Freeze warning, heat advisory |
| Humidity | % (0-100) | MQTT, HA | Mold risk (high), comfort (low) |
| Light Level | lux | MQTT, HA | Evening lighting suggestion |
| Noise Level | dB | Microphone | Silence for voice commands |
| Air Quality (VOC) | ppb | MQTT, HA | Ventilation suggestion |
| Air Quality (CO2) | ppm | MQTT, HA | Stale air warning |
| Air Quality (PM2.5) | ug/m3 | MQTT, HA | Air purifier recommendation |
| Presence | boolean | MQTT, Bluetooth | Away mode, arrival greeting |
| Motion | boolean | MQTT, Camera | Security alert, light automation |
| Contact (door/window) | open/closed | MQTT, HA | Security alert, energy saving |
| Power Usage | watts | HA | Energy monitoring, anomaly detection |

## 6. Location Awareness

**File**: `app/core/location_awareness.py` (183 lines)

The `LocationAwareness` module tracks the user's location for context-aware responses.

### Zone Detection

Defined zones (via `LOCATION_ZONES` env var):
```json
{
  "home": {"latitude": 37.7749, "longitude": -122.4194, "radius_meters": 200},
  "work": {"latitude": 37.7849, "longitude": -122.4094, "radius_meters": 100},
  "gym": {"latitude": 37.7649, "longitude": -122.4294, "radius_meters": 50}
}
```

The system detects zone entry/exit by comparing current location against zone boundaries using haversine distance calculation.

### Presence Tracking

Presence is determined through multiple signals:
1. **Phone WiFi connection**: Connected to home WiFi → user is home
2. **MQTT presence sensor**: Dedicated MQTT topic for presence
3. **HA person entity**: Home Assistant person tracking
4. **Bluetooth beacon**: BLE beacon proximity
5. **Last known location**: Fallback to IP geolocation

### Location Data Model

```python
@dataclass(slots=True)
class Location:
    city: str = ""
    region: str = ""
    country: str = ""
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = "UTC"
    source: str = "manual"  # manual, ip, gps
    updated_at: str = field(...)
```

### Proactive Location-Based Actions

- **Leave home**: Phone disconnects from WiFi + front door locks → arm security system, turn off lights, adjust thermostat
- **Arrive home**: Phone connects to WiFi → disarm security, turn on lights, restore temperature
- **Unknown location**: Ask user for location update; use IP geolocation as fallback

## 7. Environmental Sensor Data Model

The full sensor data model hierarchy:

```
EnvironmentalSensor
  ├── readings: dict[str, SensorReading]  # sensor_type → reading
  ├── state: EnvironmentState             # Current aggregated state
  ├── history: list[SensorReading]        # Recent readings (max 1000)
  │
  ├── update_from_mqtt()
  ├── update_from_ha()
  ├── get_context() → str                 # For LLM context injection
  ├── get_alerts() → list[str]            # Current active alerts
  └── get_summary() → str                 # Human-readable summary
```

The `get_context()` method produces a formatted block for LLM injection:
```
[Environmental Context]
Temperature: 22.5°C (Living Room)
Humidity: 45% (Living Room)
Outdoor: 18°C, partly cloudy
Air Quality: AQI 42 (Good)
Presence: Home (detected via WiFi)
Time: 10:00 AM (America/New_York)
```

## 8. Proactive Ambient Actions

The Ambient Loop evaluates sensor states against safety and comfort heuristics:

| Condition | Action | Risk Level |
|---|---|---|
| User leaves + front door unlocked | Alert user; suggest locking | HIGH (alert) |
| Temperature < 5°C + no occupancy | Turn down thermostat | MEDIUM (auto) |
| Temperature > 35°C + no occupancy | Turn on cooling | MEDIUM (auto) |
| CO2 > 1000ppm | Suggest opening windows | LOW (notify) |
| Motion detected while away | Security alert with camera snapshot | HIGH (alert) |
| Door open > 5 minutes | Check if intentional | LOW (remind) |
| Humidity > 70% | Suggest running dehumidifier | LOW (suggest) |
| Presence changes to away | Arm security, save energy | LOW (auto) |
| Light level < 10 lux + present | Option to turn on lights | LOW (offer) |
| Noise level > 70dB for 5 min | Suggest quiet environment | LOW (suggest) |

## 9. Configuration Reference

```ini
# MQTT
MQTT_BROKER_URL=mqtt://192.168.1.100:1883
MQTT_USERNAME=raven
MQTT_PASSWORD=your-password
MQTT_TOPICS=raven/+/+,sensors/#
MQTT_ALERT_PATTERNS=security/+,alarm/+
MQTT_TEMP_MIN=10
MQTT_TEMP_MAX=40
MQTT_ALERT_COOLDOWN_SECONDS=60

# Webhook server
WEBHOOK_HOST=127.0.0.1
WEBHOOK_PORT=8765
WEBHOOK_AUTH_TOKEN=
WEBHOOK_ALLOWED_IPS=

# Home Assistant
HOME_ASSISTANT_URL=http://192.168.1.101:8123
HOME_ASSISTANT_TOKEN=your-long-lived-token
HOME_ASSISTANT_WEBSOCKET=true

# Camera monitoring
MONITORING_ENABLED=true
CAMERA_RTSP_URLS=rtsp://camera1.local/stream,rtsp://camera2.local/stream
YOLO_CONFIDENCE_THRESHOLD=0.5

# Location
LOCATION_DEFAULT_CITY=San Francisco
LOCATION_DEFAULT_TIMEZONE=America/Los_Angeles
LOCATION_ZONES={"home": {"lat": 37.77, "lon": -122.42, "radius": 200}}

# Admin users (for alerts)
ADMIN_USER_IDS=telegram:123456,discord:789012

# Environmental context
ENVIRONMENTAL_CONTEXT_ENABLED=true
ENVIRONMENTAL_HISTORY_SIZE=1000
```
