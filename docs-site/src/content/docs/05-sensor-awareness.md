---
title: "05 - Sensor Awareness"
---

# 05 - Sensor Awareness

## Overview

RAVEN extends its intelligence into the physical world through a sensor network. Rather
than being a passive chatbot that only responds when spoken to, RAVEN continuously
monitors its environment -- temperature, humidity, motion, door states, air quality,
light levels, and camera feeds -- and uses this information to proactively assist its
user. If the temperature in your server room spikes at 3am, RAVEN does not wait for you
to ask about it. It wakes you up.

The sensor layer is **Layer 5** in the RAVEN architecture. It sits below the brain and
above the physical hardware, acting as the nervous system that gives RAVEN spatial and
environmental awareness.

**Design principles:**

- Sensors are read-only inputs (actuation is handled by the IoT layer in doc 06)
- All sensor data flows through MQTT for uniform ingestion
- Raw readings are stored in PostgreSQL; latest values cached in Redis
- Anomaly detection runs continuously, not just on user queries
- The brain receives sensor context automatically -- no special commands needed

---

## Sensor Network Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      SENSOR AWARENESS ARCHITECTURE                          │
│                                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐   │
│  │ ESP32 +  │ │ ESP32 +  │ │ RPi Zero │ │ Zigbee   │ │ IP Camera      │   │
│  │ DHT22    │ │ PIR /    │ │ + BME280 │ │ Door     │ │ (RTSP/ONVIF)   │   │
│  │ (temp/   │ │ mmWave   │ │ + MQ-2   │ │ Contact  │ │                │   │
│  │  humid)  │ │ (motion) │ │ (gas)    │ │ Sensor   │ │ Snapshots +    │   │
│  │          │ │          │ │          │ │          │ │ motion detect  │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └───────┬────────┘   │
│       │WiFi        │WiFi        │WiFi        │Zigbee2MQTT     │RTSP        │
│       ▼            ▼            ▼            ▼                ▼            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                 MOSQUITTO MQTT BROKER (localhost:1883)               │   │
│  │  raven/sensors/{device_id}/temperature | humidity | motion | door   │   │
│  │  raven/sensors/{device_id}/gas | light | camera/snapshot | status   │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│                                 │                                           │
│                                 ▼                                           │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  MQTT LISTENER (aiomqtt) ──▶ Parse JSON into SensorReading objects  │   │
│  └──────────────────────────────┬───────────────────────────────────────┘   │
│              ┌──────────────────┼──────────────────┐                        │
│              ▼                  ▼                   ▼                        │
│  ┌────────────────┐  ┌──────────────────┐  ┌───────────────────┐           │
│  │  PostgreSQL    │  │  Redis Cache     │  │  Anomaly Detector │           │
│  │  sensor_       │  │  sensor:{id}:*   │  │  Threshold /      │           │
│  │  readings      │  │  TTL: 5 min      │  │  Rate-of-change / │           │
│  │  (time-series) │  │                  │  │  Z-score           │           │
│  └────────────────┘  └──────────────────┘  └────────┬──────────┘           │
│                                                      │ alerts              │
│                                                      ▼                     │
│                                             ┌──────────────────┐           │
│                                             │   RAVEN BRAIN    │           │
│                                             │  context inject  │           │
│                                             │  + proactive     │           │
│                                             │  notifications   │           │
│                                             └──────────────────┘           │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Supported Sensor Types

RAVEN supports any sensor that publishes MQTT. These types have first-class support
with dedicated parsing, anomaly rules, and context injection.

| Sensor              | Hardware                | Topic suffix        | Payload example                             | Interval     | Anomaly rule                    |
|---------------------|-------------------------|---------------------|---------------------------------------------|--------------|---------------------------------|
| Temperature/humidity| DHT22, BME280 on ESP32  | `temperature`, `humidity` | `{"value": 23.5, "unit": "C"}`        | 30s          | Threshold, rate-of-change       |
| Motion              | PIR, HLK-LD2410 mmWave  | `motion`            | `{"detected": true, "type": "pir"}`         | Event-driven | Time-based (3am = alert)        |
| Door/window         | Reed switch, Zigbee     | `door`              | `{"state": "open", "name": "front"}`        | Event-driven | Duration (open > 10min)         |
| Smoke/gas           | MQ-2, MQ-135 on ESP32   | `gas`               | `{"value": 320, "unit": "ppm", "gas": "co"}`| 10s          | Threshold (>1000ppm = critical) |
| Light level         | LDR, BH1750             | `light`             | `{"value": 450, "unit": "lux"}`             | 60s          | Contextual                      |
| Camera snapshot     | IP cam, ESP32-CAM       | `camera/snapshot`   | `{"image_path": "/tmp/snap.jpg"}`           | On trigger   | Motion-triggered + VLM          |

Gas sensors are **safety-critical** -- alerts bypass normal routing and fire on all
platforms simultaneously. mmWave sensors provide continuous presence detection (not
just motion), which is valuable for occupancy awareness.

---

## MQTT Listener Implementation

```python
# raven/sensors/mqtt_listener.py

import asyncio, json, logging
from datetime import datetime, timezone
import aiomqtt
from raven.sensors.processor import SensorProcessor

logger = logging.getLogger(__name__)


class MQTTListener:
    """Subscribes to raven/sensors/# and routes readings to the processing pipeline.
    Reconnects with exponential backoff on broker disconnect."""

    def __init__(self, config: dict, processor: SensorProcessor):
        self.processor = processor
        mqtt_config = config.get("mqtt", {})
        self.broker = mqtt_config.get("broker", "localhost")
        self.port = mqtt_config.get("port", 1883)
        self.topic_prefix = mqtt_config.get("topic_prefix", "raven/sensors")

    async def start(self):
        backoff = 1
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self.broker, port=self.port, keepalive=60,
                    will=aiomqtt.Will(
                        topic=f"{self.topic_prefix}/_raven/status",
                        payload=b"offline", retain=True),
                ) as client:
                    backoff = 1
                    await client.publish(
                        f"{self.topic_prefix}/_raven/status", payload=b"online", retain=True)
                    await client.subscribe(f"{self.topic_prefix}/#")

                    async for message in client.messages:
                        try:
                            await self._handle(message)
                        except Exception:
                            logger.exception("Error on %s", message.topic)
            except aiomqtt.MqttError as e:
                logger.warning("MQTT lost: %s. Retry in %ds", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _handle(self, msg: aiomqtt.Message):
        """Topic format: raven/sensors/{device_id}/{sensor_type}"""
        parts = str(msg.topic).split("/")
        if len(parts) < 4 or parts[2].startswith("_"):
            return

        device_id = parts[2]
        sensor_type = "/".join(parts[3:])

        if sensor_type == "status":
            await self.processor.handle_device_status(device_id, msg.payload.decode())
            return

        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        from raven.sensors.models import SensorReading
        await self.processor.process_reading(SensorReading(
            device_id=device_id, sensor_type=sensor_type,
            value=payload.get("value"), unit=payload.get("unit", ""),
            location=payload.get("location", ""), detected=payload.get("detected"),
            metadata=payload, timestamp=datetime.now(timezone.utc),
        ))
```

### Data Models

```python
# raven/sensors/models.py

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

@dataclass
class SensorReading:
    device_id: str
    sensor_type: str                      # "temperature", "motion", "door"
    value: Optional[float] = None         # Numeric sensors
    unit: str = ""                        # "C", "%RH", "lux", "ppm"
    location: str = ""
    detected: Optional[bool] = None       # Binary sensors (motion, door)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class SensorAlert:
    alert_type: str                       # "threshold", "rate_of_change", "anomaly"
    severity: str                         # "info", "warning", "critical"
    device_id: str
    sensor_type: str
    message: str
    current_value: Any
    threshold_value: Any = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
```

---

## ESP32 Sensor Node Firmware

### MicroPython (DHT22 Temperature + Humidity)

```python
# main.py -- ESP32 MicroPython for DHT22 sensor node

import machine, dht, time, json, network
from umqtt.simple import MQTTClient

MQTT_BROKER  = "192.168.1.100"
DEVICE_ID    = "esp32-bedroom-01"
TOPIC_PREFIX = "raven/sensors"
LOCATION     = "bedroom"

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect("your-ssid", "your-pass")
    for _ in range(20):
        if wlan.isconnected(): return True
        time.sleep(1)
    return False

def create_mqtt():
    c = MQTTClient(DEVICE_ID, MQTT_BROKER, keepalive=60)
    c.set_last_will(f"{TOPIC_PREFIX}/{DEVICE_ID}/status", b"offline", retain=True)
    c.connect()
    c.publish(f"{TOPIC_PREFIX}/{DEVICE_ID}/status", b"online", retain=True)
    # Self-register for auto-discovery
    c.publish(f"{TOPIC_PREFIX}/{DEVICE_ID}/register", json.dumps({
        "device_id": DEVICE_ID, "device_name": "Bedroom Sensor",
        "device_type": "esp32", "location": LOCATION,
        "sensors": ["temperature", "humidity"],
    }), retain=True)
    return c

def main():
    if not connect_wifi(): machine.reset()
    sensor = dht.DHT22(machine.Pin(4))
    client = create_mqtt()

    while True:
        try:
            sensor.measure()
            for stype, val, unit in [("temperature", sensor.temperature(), "C"),
                                      ("humidity", sensor.humidity(), "%RH")]:
                client.publish(f"{TOPIC_PREFIX}/{DEVICE_ID}/{stype}",
                    json.dumps({"value": val, "unit": unit, "location": LOCATION}))
        except OSError:
            pass
        except Exception:
            client = create_mqtt()
        time.sleep(30)

main()
```

### Arduino/C++ (PIR Motion Sensor)

```cpp
// esp32_motion_sensor.ino | Board: ESP32 DevKit | Libs: PubSubClient, ArduinoJson
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

const char* MQTT_BROKER = "192.168.1.100";
const char* DEVICE_ID   = "esp32-hallway-pir";
const char* PREFIX      = "raven/sensors";
const int PIR_PIN = 27;
const unsigned long DEBOUNCE_MS = 5000;

WiFiClient wc; PubSubClient mqtt(wc);
bool lastState = false; unsigned long lastTime = 0;

void mqtt_connect() {
    mqtt.setServer(MQTT_BROKER, 1883);
    String lwt = String(PREFIX) + "/" + DEVICE_ID + "/status";
    while (!mqtt.connected()) {
        if (mqtt.connect(DEVICE_ID, lwt.c_str(), 1, true, "offline")) {
            mqtt.publish(lwt.c_str(), "online", true);
            // Self-register
            StaticJsonDocument<256> r;
            r["device_id"] = DEVICE_ID; r["device_type"] = "esp32";
            r["location"] = "hallway";
            r.createNestedArray("sensors").add("motion");
            char buf[256]; serializeJson(r, buf);
            String t = String(PREFIX) + "/" + DEVICE_ID + "/register";
            mqtt.publish(t.c_str(), buf, true);
        } else delay(5000);
    }
}

void setup() {
    pinMode(PIR_PIN, INPUT);
    WiFi.begin("ssid", "pass");
    while (WiFi.status() != WL_CONNECTED) delay(500);
    mqtt_connect();
}

void loop() {
    if (!mqtt.connected()) mqtt_connect();
    mqtt.loop();
    bool motion = digitalRead(PIR_PIN);
    unsigned long now = millis();
    if (motion != lastState && (now - lastTime > DEBOUNCE_MS)) {
        StaticJsonDocument<64> d;
        d["detected"] = motion; d["type"] = "pir"; d["location"] = "hallway";
        char p[64]; serializeJson(d, p);
        String t = String(PREFIX) + "/" + DEVICE_ID + "/motion";
        mqtt.publish(t.c_str(), p);
        lastState = motion; lastTime = now;
    }
}
```

---

## Sensor Data Flow

```
  MQTT Message ──▶ PARSE (topic → device_id + sensor_type, JSON → SensorReading)
       │
       ▼
  VALIDATE ──▶ Check value within sane bounds. Drop corrupted readings.
       │
       ▼
  STORE ──▶ INSERT INTO sensor_readings (PostgreSQL, append-only)
       │
       ▼
  CACHE ──▶ SET sensor:{device_id}:{type} in Redis (TTL 5 min)
       │
       ▼
  DETECT ──▶ Anomaly check (threshold + rate + z-score)
       │
       ├── normal ──▶ Done
       └── anomaly ─▶ Route alert to brain → proactive notification
```

### Sensor Processor

```python
# raven/sensors/processor.py

import json, logging
import asyncpg, redis.asyncio as aioredis
from raven.sensors.models import SensorReading, SensorAlert
from raven.sensors.anomaly import AnomalyDetector

SANE_BOUNDS = {"temperature": (-50, 80), "humidity": (0, 100),
               "light": (0, 200000), "gas": (0, 50000)}

class SensorProcessor:
    def __init__(self, db: asyncpg.Pool, redis: aioredis.Redis,
                 anomaly: AnomalyDetector, alert_cb: callable):
        self.db, self.redis, self.anomaly, self.alert_cb = db, redis, anomaly, alert_cb

    async def process_reading(self, r: SensorReading):
        if r.value is not None and r.sensor_type in SANE_BOUNDS:
            lo, hi = SANE_BOUNDS[r.sensor_type]
            if not (lo <= r.value <= hi):
                return  # drop out-of-bounds

        await self.db.execute(
            """INSERT INTO sensor_readings (device_id,sensor_type,value,unit,location,timestamp)
               VALUES ($1,$2,$3,$4,$5,$6)""",
            r.device_id, r.sensor_type, r.value, r.unit, r.location, r.timestamp)

        await self.redis.set(f"sensor:{r.device_id}:{r.sensor_type}", json.dumps({
            "value": r.value, "unit": r.unit, "detected": r.detected,
            "location": r.location, "timestamp": r.timestamp.isoformat()}), ex=300)

        for alert in await self.anomaly.check(r):
            await self.alert_cb(alert)

    async def handle_device_status(self, device_id: str, status: str):
        is_online = status.strip().lower() == "online"
        await self.db.execute(
            "UPDATE devices SET is_online=$1, last_seen=NOW() WHERE device_id=$2",
            is_online, device_id)
        if not is_online:
            await self.alert_cb(SensorAlert(
                "device_offline", "warning", device_id, "status",
                f"Device '{device_id}' went offline.", "offline"))
```

---

## Device Registry

Devices self-register by publishing a retained message to
`raven/sensors/{device_id}/register`. RAVEN upserts this into PostgreSQL.

### Database Schema

The canonical schema for these tables is defined in `01-system-architecture.md`.
The definitions below are reproduced for reference and must stay in sync with doc 01.

```sql
CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(255) UNIQUE NOT NULL,
    device_name VARCHAR(255) NOT NULL,
    device_type VARCHAR(100) NOT NULL,       -- "esp32", "rpi", "zigbee"
    location VARCHAR(100),
    connection_type VARCHAR(50),             -- "mqtt", "homeassistant", "http"
    capabilities JSONB NOT NULL DEFAULT '{}',
    sensors TEXT[],                           -- {"temperature", "humidity"}
    config JSONB DEFAULT '{}',
    firmware_version VARCHAR(50),
    is_online BOOLEAN DEFAULT FALSE,
    last_seen TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE sensor_readings (
    id BIGSERIAL PRIMARY KEY,
    device_id VARCHAR(255) NOT NULL REFERENCES devices(device_id),
    sensor_type VARCHAR(100) NOT NULL,
    value DOUBLE PRECISION,
    unit VARCHAR(20),
    location VARCHAR(100),                   -- Denormalized for query speed
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_readings_device ON sensor_readings(device_id, timestamp DESC);
CREATE INDEX idx_readings_type ON sensor_readings(sensor_type, timestamp DESC);

CREATE TABLE sensor_alerts (
    id BIGSERIAL PRIMARY KEY,
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    device_id VARCHAR(255) NOT NULL,
    sensor_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    current_value TEXT,
    threshold_value TEXT,
    acknowledged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Registration and Watchdog

```python
# raven/sensors/registry.py

import asyncio, logging, asyncpg
from raven.sensors.models import SensorAlert

class DeviceRegistry:
    def __init__(self, db: asyncpg.Pool):
        self.db = db

    async def register(self, p: dict):
        await self.db.execute("""
            INSERT INTO devices (device_id,device_name,device_type,location,
                                 sensors,firmware_version,is_online,last_seen)
            VALUES ($1,$2,$3,$4,$5,$6,TRUE,NOW())
            ON CONFLICT (device_id) DO UPDATE SET
                device_name=EXCLUDED.device_name, location=EXCLUDED.location,
                sensors=EXCLUDED.sensors, is_online=TRUE, last_seen=NOW()
        """, p["device_id"], p.get("device_name",""), p.get("device_type","esp32"),
            p.get("location",""), p.get("sensors",[]), p.get("firmware_version",""))


async def device_watchdog(registry, alert_cb, interval=120, stale_min=10):
    """Background: detect stale devices (online but not reporting) and alert."""
    while True:
        await asyncio.sleep(interval)
        rows = await registry.db.fetch("""
            SELECT device_id FROM devices
            WHERE is_online AND last_seen < NOW() - INTERVAL '1 minute' * $1
        """, stale_min)
        for r in rows:
            did = r["device_id"]
            await registry.db.execute(
                "UPDATE devices SET is_online=FALSE WHERE device_id=$1", did)
            await alert_cb(SensorAlert("device_stale", "warning", did, "status",
                f"Device '{did}' not reporting for {stale_min}min.", "stale"))
```

### LWT-Based Offline Detection

When an ESP32 connects, it registers an MQTT Last Will and Testament:

```
Topic:   raven/sensors/esp32-bedroom-01/status
Payload: "offline"
Retain:  true
```

If the device drops (power loss, WiFi failure), the broker publishes this message
automatically. The watchdog task catches cases where LWT was not delivered by scanning
for devices with `last_seen` older than 10 minutes.

---

## Alert System

### Anomaly Detector

```python
# raven/sensors/anomaly.py

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta
from raven.sensors.models import SensorReading, SensorAlert

@dataclass
class ThresholdRule:
    sensor_type: str
    min_value: float | None = None
    max_value: float | None = None
    severity: str = "warning"

@dataclass
class RateRule:
    sensor_type: str
    max_delta: float
    window_seconds: int
    severity: str = "warning"

DEFAULT_THRESHOLDS = [
    ThresholdRule("temperature", min_value=2.0, max_value=40.0),
    ThresholdRule("temperature", min_value=-10.0, max_value=55.0, severity="critical"),
    ThresholdRule("gas", max_value=1000.0, severity="critical"),
]
DEFAULT_RATES = [
    RateRule("temperature", max_delta=5.0, window_seconds=600),
    RateRule("gas", max_delta=500.0, window_seconds=300, severity="critical"),
]


class AnomalyDetector:
    """Three strategies: threshold, rate-of-change, z-score."""

    def __init__(self, zscore_threshold=3.0, history_size=200):
        self.zscore_threshold = zscore_threshold
        self._hist: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=history_size))

    async def check(self, r: SensorReading) -> list[SensorAlert]:
        if r.value is None:
            return self._binary(r)

        key = (r.device_id, r.sensor_type)
        h = self._hist[key]
        alerts = self._thresholds(r) + self._rate(r, h) + self._zscore(r, h)
        h.append((r.timestamp, r.value))
        return alerts

    def _thresholds(self, r):
        out = []
        for t in DEFAULT_THRESHOLDS:
            if t.sensor_type != r.sensor_type: continue
            if t.max_value is not None and r.value > t.max_value:
                out.append(SensorAlert("threshold", t.severity, r.device_id,
                    r.sensor_type, f"{r.sensor_type.title()} = {r.value}{r.unit} "
                    f"(max {t.max_value})", r.value, t.max_value))
            if t.min_value is not None and r.value < t.min_value:
                out.append(SensorAlert("threshold", t.severity, r.device_id,
                    r.sensor_type, f"{r.sensor_type.title()} = {r.value}{r.unit} "
                    f"(min {t.min_value})", r.value, t.min_value))
        return out

    def _rate(self, r, h):
        if len(h) < 2: return []
        out = []
        for rule in DEFAULT_RATES:
            if rule.sensor_type != r.sensor_type: continue
            cutoff = r.timestamp - timedelta(seconds=rule.window_seconds)
            for ts, val in h:
                if ts >= cutoff:
                    delta = abs(r.value - val)
                    if delta > rule.max_delta:
                        out.append(SensorAlert("rate_of_change", rule.severity,
                            r.device_id, r.sensor_type,
                            f"{r.sensor_type.title()} changed {delta:.1f}{r.unit} "
                            f"in {rule.window_seconds//60}min", r.value, rule.max_delta))
                    break
        return out

    def _zscore(self, r, h):
        if len(h) < 30: return []
        vals = [v for _, v in h]
        mean = sum(vals) / len(vals)
        std = math.sqrt(sum((v-mean)**2 for v in vals) / len(vals))
        if std == 0: return []
        z = abs(r.value - mean) / std
        if z > self.zscore_threshold:
            return [SensorAlert("anomaly", "warning", r.device_id, r.sensor_type,
                f"Statistical anomaly: {r.sensor_type}={r.value}{r.unit} "
                f"(z={z:.1f}, mean={mean:.1f})", r.value, f"z>{self.zscore_threshold}")]
        return []

    def _binary(self, r):
        if r.sensor_type == "motion" and r.detected and 0 <= r.timestamp.hour < 6:
            return [SensorAlert("contextual", "warning", r.device_id, "motion",
                f"Motion at {r.location} at {r.timestamp:%H:%M} (outside normal hours)",
                True)]
        return []
```

### Alert Routing

Alerts route by severity. Critical goes everywhere, warning to Telegram + web, info
to web dashboard only.

```python
ROUTES = {
    "critical": ["telegram", "discord", "web"],
    "warning":  ["telegram", "web"],
    "info":     ["web"],
}

class AlertRouter:
    async def route(self, alert, send_fn):
        platforms = ROUTES.get(alert.severity, ["web"])
        prefix = {"critical":"[CRITICAL]","warning":"[WARNING]","info":"[INFO]"}
        msg = f"{prefix.get(alert.severity,'[ALERT]')} {alert.message}"
        for p in platforms:
            await send_fn(platform=p, message=msg, priority=alert.severity)
```

---

## Proactive Notifications

Instead of sending raw sensor data, RAVEN feeds alerts through the brain to produce
natural-language notifications.

```
  SensorAlert ──▶ Brain generates: "Hey, your bedroom just hit 41C --
                   that's unusual for 3am. Check if the heating is stuck."
                       │
                       ▼
                  AlertRouter ──▶ Telegram
```

```python
# raven/sensors/proactive.py

class ProactiveNotifier:
    def __init__(self, brain, router):
        self.brain, self.router = brain, router

    async def handle_alert(self, alert, send_fn):
        # Safety-critical alerts skip brain for speed
        if alert.severity == "critical" and alert.sensor_type in ("gas", "smoke"):
            await self.router.route(alert, send_fn)
            return

        ctx = (f"Sensor alert. Generate a brief, natural notification.\n"
               f"Sensor: {alert.sensor_type}, Value: {alert.current_value}, "
               f"Threshold: {alert.threshold_value}, Time: {alert.timestamp:%I:%M %p}\n"
               f"Raw: {alert.message}\nDo not use device IDs. Suggest action.")
        try:
            alert.message = await self.brain.generate_system_response(
                system_context=ctx, max_tokens=150)
        except Exception:
            pass
        await self.router.route(alert, send_fn)
```

---

## Sensor Context Injection

Latest sensor values from Redis are injected into every LLM context window so RAVEN
can answer questions like "What's the temperature?" without a tool call.

```python
# raven/sensors/context.py

import json
import redis.asyncio as aioredis

class SensorContextBuilder:
    """Builds a text block of current readings for LLM context injection."""

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    async def build_context(self) -> str:
        """Returns e.g.:
            ## Current Environment
            - Bedroom: temperature 23.5C, humidity 45%RH
            - Hallway: motion detected
        """
        keys = [k async for k in self.redis.scan_iter(match="sensor:*")]
        if not keys: return ""

        locs: dict[str, list[str]] = {}
        for key in keys:
            raw = await self.redis.get(key)
            if not raw: continue
            data = json.loads(raw)
            parts = (key if isinstance(key, str) else key.decode()).split(":")
            if len(parts) < 3: continue
            stype, loc = parts[2], data.get("location", "unknown")
            v, u, d = data.get("value"), data.get("unit",""), data.get("detected")

            if stype in ("temperature","humidity","light") and v is not None:
                text = f"{stype} {v}{u}"
            elif stype == "motion":
                text = "motion detected" if d else "no motion"
            elif stype == "gas" and v is not None:
                lvl = "normal" if v<500 else "elevated" if v<1000 else "HIGH"
                text = f"gas {v}{u} ({lvl})"
            elif v is not None:
                text = f"{stype} {v}{u}"
            else: continue
            locs.setdefault(loc, []).append(text)

        if not locs: return ""
        lines = ["## Current Environment"]
        for loc in sorted(locs):
            lines.append(f"- {loc.replace('_',' ').title()}: {', '.join(locs[loc])}")
        return "\n".join(lines)
```

This is called in `RavenBrain.build_full_context()` -- sensor data appears after the
system prompt and before conversation history:

```python
# raven/brain/core.py (excerpt)
class RavenBrain:
    async def build_full_context(self, user_message, user_id):
        parts = [self.personality.get_system_prompt()]
        sensor_ctx = await self.sensor_ctx.build_context()
        if sensor_ctx: parts.append(sensor_ctx)
        parts.append(self._format_memories(
            await self.memory.search_relevant(user_message, user_id)))
        parts.append(self._format_history(
            await self.memory.get_recent_messages(user_id, limit=20)))
        return "\n\n".join(parts)
```

---

## Camera Integration

### RTSP Snapshot Capture

```python
# raven/sensors/camera.py

import asyncio
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_DIR = Path("/var/raven/snapshots")

async def capture_rtsp_snapshot(rtsp_url: str, device_id: str, timeout=10) -> str|None:
    """Capture one JPEG frame from RTSP stream via ffmpeg."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out = SNAPSHOT_DIR / f"{device_id}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.jpg"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-rtsp_transport", "tcp", "-i", rtsp_url,
        "-frames:v", "1", "-q:v", "2", "-f", "image2", str(out),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return str(out) if proc.returncode == 0 and out.exists() else None
    except asyncio.TimeoutError:
        proc.kill(); return None
```

### ONVIF PTZ Control

```python
from onvif import ONVIFCamera

class ONVIFClient:
    def __init__(self, host, port, user, passwd):
        self.cam = ONVIFCamera(host, port, user, passwd)

    async def connect(self):
        await self.cam.update_xaddrs()
        media = await self.cam.create_media_service()
        self.ptz = await self.cam.create_ptz_service()
        self.token = (await media.GetProfiles())[0].token

    async def move(self, pan, tilt, zoom):
        req = self.ptz.create_type("AbsoluteMove")
        req.ProfileToken = self.token
        req.Position = {"PanTilt": {"x": pan, "y": tilt}, "Zoom": {"x": zoom}}
        await self.ptz.AbsoluteMove(req)
```

### Motion-Triggered Capture

When a motion sensor fires, a snapshot is captured from the nearest camera:

```python
CAMERA_MAP = {"hallway": "rtsp://192.168.1.50:554/stream1",
              "front_door": "rtsp://192.168.1.51:554/stream1"}

async def on_motion(reading):
    if reading.sensor_type == "motion" and reading.detected:
        url = CAMERA_MAP.get(reading.location)
        if url: return await capture_rtsp_snapshot(url, f"motion-{reading.device_id}")
```

---

## Dashboard API Endpoints

| Method | Path                               | Description                        |
|--------|------------------------------------|------------------------------------|
| GET    | `/api/sensors`                     | List all devices with latest values|
| GET    | `/api/sensors/{device_id}`         | Latest readings for one device     |
| GET    | `/api/sensors/{device_id}/history` | Historical readings (time range)   |
| GET    | `/api/sensors/alerts`              | Recent alerts, filterable          |
| GET    | `/api/sensors/snapshot/{device_id}`| Trigger camera snapshot            |

The history endpoint supports `sensor_type`, `hours` (1-168), and `limit` (1-5000)
query parameters, returning time-ordered readings from `sensor_readings`.

---

## Bootstrapping

```python
async def start_sensor_layer(config, db_pool, redis, brain):
    if not config.mqtt.enabled:
        return
    anomaly = AnomalyDetector()
    notifier = ProactiveNotifier(brain=brain, router=AlertRouter())
    processor = SensorProcessor(db=db_pool, redis=redis, anomaly=anomaly,
        alert_cb=lambda a: notifier.handle_alert(a, brain.send_to_platform))
    registry = DeviceRegistry(db_pool)
    listener = MQTTListener(config, processor)
    await asyncio.gather(listener.start(), device_watchdog(registry, processor.alert_cb))
```

### Configuration

```yaml
mqtt:
  enabled: true
  broker: "localhost"
  port: 1883
  topic_prefix: "raven/sensors"

sensors:
  cache_ttl_seconds: 300
  zscore_threshold: 3.0
  thresholds:
    temperature: {warning_max: 40, warning_min: 5, critical_max: 55}
    gas: {critical_max: 1000}
  rate_of_change:
    temperature: {max_delta: 5.0, window_seconds: 600}
    gas: {max_delta: 500, window_seconds: 300}
  alerts:
    critical_platforms: [telegram, discord, web]
    warning_platforms: [telegram, web]
    info_platforms: [web]
  cameras:
    snapshot_dir: /var/raven/snapshots
    snapshot_retention_days: 7
  watchdog:
    check_interval_seconds: 120
    stale_threshold_minutes: 10
```

---

## Summary

1. **MQTT as universal transport** -- any device that publishes MQTT becomes a sensor.
2. **Dual storage** -- PostgreSQL for historical trends, Redis for real-time access.
3. **Always-on context injection** -- the LLM always knows the environment state.
4. **Multi-strategy anomaly detection** -- thresholds, rate-of-change, z-scores.
5. **Brain-mediated notifications** -- natural language alerts, not raw sensor dumps.
6. **Self-registering devices** -- nodes announce themselves, no manual config.
