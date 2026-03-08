# Frigate Anomaly Handler - Production-Grade Surveillance Extension

## Overview

A lightweight, ARM-optimized Python service that extends Frigate NVR with real-time anomaly detection, smart alerting, and a web dashboard. Designed for **Raspberry Pi 5** (8GB, Bookworm 64-bit) with minimal resource footprint.

### Key Features

✅ **Real-Time MQTT Listener** - Consumes Frigate events from `frigate/events` topic
✅ **Anomaly Detection Engine** - Loitering, static objects, potential weapons
✅ **Smart Media Processing** - Digital zoom/crop + clip retrieval from Frigate API
✅ **Multi-Channel Alerts** - HTTP webhooks + Telegram notifications
✅ **Flask Web Dashboard** - Recent anomalies, live MJPEG streams, clip playback
✅ **Production Hardening** - Graceful shutdown, logging, memory limits, systemd integration
✅ **Memory Efficient** - <800 MB idle footprint on ARM

---

## Architecture

```
┌─────────────────┐
│    Frigate      │
│ MQTT Events     │
└────────┬────────┘
         │ frigate/events
         ▼
┌─────────────────────────────────────────┐
│  Anomaly Handler Service                │
├─────────────────────────────────────────┤
│  ┌─────────────────────────────────┐   │
│  │ MQTT Listener (Background)      │   │
│  └──────────────┬──────────────────┘   │
│                 │                       │
│  ┌──────────────▼──────────────────┐   │
│  │ Anomaly Detection Engine        │   │
│  │ - Loitering                     │   │
│  │ - Static Object                 │   │
│  │ - Weapon Detection (optional)   │   │
│  └──────────────┬──────────────────┘   │
│                 │                       │
│  ┌──────────────▼──────────────────┐   │
│  │ Media Processing (async)        │   │
│  │ - Fetch snapshot               │   │
│  │ - Apply zoom/crop              │   │
│  │ - Download clip                │   │
│  └──────────────┬──────────────────┘   │
│                 │                       │
│  ┌──────────────▼──────────────────────────┬──────────────┐
│  │ Alert Manager                          │ Flask Server │
│  │ - POST webhook                         │ - /events    │
│  │ - Telegram message                     │ - /live      │
│  │ - Database storage                     │ - /clips     │
│  └────────────────────────────────────────┴──────────────┘
│                 │
└─────────────────┼─────────────────┐
                  ▼                 ▼
          ┌──────────────┐  ┌──────────────┐
          │ PostgreSQL   │  │  Filesystem  │
          │  Metadata    │  │  Clips/Snaps │
          └──────────────┘  └──────────────┘
```

---

## Installation (Quick Start)

### Prerequisites

- Raspberry Pi 5 (8GB recommended)
- Raspberry Pi OS Bookworm 64-bit
- Frigate running with MQTT broker
- PostgreSQL 13+ installed

### Step-by-Step Setup

```bash
# 1. SSH into Raspberry Pi
ssh pi@$RPI_IP

# 2. Clone/navigate to monitoring directory
cd /home/saras/monitoring

# 3. Run installation script
bash install.sh

# 4. Edit configuration
sudo nano /etc/systemd/system/anomaly-handler.service
# Update:
#   - POSTGRES_URL: postgresql://saras:YOUR_PASSWORD@localhost/5432/saras
#   - FRIGATE_MQTT_HOST, FRIGATE_API_URL
#   - Optional: TELEGRAM_TOKEN, ANOMALY_WEBHOOK_URL

# 5. Start the service
sudo systemctl daemon-reload
sudo systemctl start anomaly-handler.service
sudo systemctl enable anomaly-handler.service

# 6. Check logs
journalctl -u anomaly-handler.service -f
```

---

## Configuration

All configuration via **environment variables** (no config files to maintain):

### MQTT Connection

```bash
FRIGATE_MQTT_HOST=localhost           # MQTT broker hostname
FRIGATE_MQTT_PORT=1883                # MQTT broker port
```

### Frigate API

```bash
FRIGATE_API_URL=http://localhost:5000 # Frigate API endpoint
FRIGATE_RTSP_URL=rtsp://localhost:8554 # For live stream proxy
```

### Database

```bash
POSTGRES_URL=postgresql://saras:pass@localhost/saras
```

### Storage

```bash
CLIPS_DIR=/var/lib/saras/anomalies    # Where to save clips/snapshots
```

### Anomaly Thresholds

```bash
LOITER_THRESHOLD=30                   # Seconds before loitering alert
STATIC_OBJECT_THRESHOLD=120           # Seconds before static object alert
WEAPON_CONFIDENCE=0.5                 # YOLO confidence for weapons
ZOOM_FACTOR=2.5                       # Digital zoom on subject (2x-4x)
```

### Alerting

```bash
ANOMALY_WEBHOOK_URL=http://alerts.com/hook  # Optional webhook
TELEGRAM_TOKEN=123:ABC...                    # Optional Telegram bot
TELEGRAM_CHAT_ID=-123456789                  # Telegram group/chat ID
```

### Flask Web Server

```bash
FLASK_PORT=8080                       # Web dashboard port
LOG_LEVEL=INFO                        # DEBUG, INFO, WARNING, ERROR
```

---

## API Endpoints

### Web Dashboard

- **GET `/`** - Home + endpoint list
- **GET `/events`** - Recent anomalies (HTML table with thumbnails)
- **GET `/api/events`** - Recent anomalies (JSON)
- **GET `/clips/<filename>`** - Download snapshot or clip
- **GET `/live/<camera>`** - MJPEG live stream from Frigate
- **GET `/health`** - Service health check (JSON)

### Example Requests

```bash
# View recent anomalies
curl http://localhost:8080/api/events | jq '.[0]'

# Check service health
curl http://localhost:8080/health

# Stream camera
ffplay http://localhost:8080/live/cam_01
```

---

## Anomaly Detection Rules

### 1. Loitering Detection

**Trigger:** Person remains in zone for > `LOITER_THRESHOLD` seconds (default: 30s)
**Action:** Fetch snapshot, zoom on subject, store metadata, send alert
**Use Case:** Detect suspicion loiterers, security zone violations

### 2. Static Object Detection

**Trigger:** Unattended bag/suitcase for > `STATIC_OBJECT_THRESHOLD` seconds (default: 120s)
**Action:** Fetch snapshot, save clip, send alert
**Use Case:** Detect abandoned baggage, dropped items

### 3. Potential Weapon Detection (Optional)

**Trigger:** YOLO secondary inference detects knife/gun with confidence > `WEAPON_CONFIDENCE` (default: 0.5)
**Action:** High-priority alert, Telegram notification
**Requires:** ultralytics YOLO library and yolo26n.pt model

---

## Alert Formats

### Webhook POST (JSON)

```json
{
  "event_id": "frigate_event_abc123",
  "timestamp": "2025-02-21T10:45:23.123456",
  "camera": "cam_01",
  "anomaly_type": "loitering",
  "confidence": 0.95,
  "message": "Loitering detected on cam_01"
}
```

### Telegram Message

```
🚨 *ANOMALY DETECTED*
Type: `Loitering`
Camera: `Main Entrance`
Time: `2025-02-21 10:45:23`
Confidence: `95%`
Track ID: `456`
```

### Database Record (PostgreSQL)

```sql
SELECT * FROM anomalies WHERE camera='cam_01' ORDER BY timestamp DESC LIMIT 5;

id | event_id | timestamp | camera | anomaly_type | confidence | track_id | snapshot_path | clip_path
---|----------|-----------|--------|--------------|------------|----------|---------------|----------
1  | evt_123  | 2025-02-21| cam_01 | loitering    | 0.95       | 456      | /path/snap.jpg| /path/clip.mp4
```

---

## Testing & Troubleshooting

### Run Test Suite

```bash
bash test_anomaly_handler.sh
```

Tests:

1. Python dependencies ✅
2. PostgreSQL connection ✅
3. MQTT connection ✅
4. Flask endpoints (requires running service)
5. Anomaly detection logic ✅
6. Database schema ✅
7. Configuration loading ✅

### Manual Testing - Simulate Loitering Event

```bash
# 1. Start service
sudo systemctl start anomaly-handler.service

# 2. In another terminal, publish test MQTT event
mosquitto_pub -h localhost -t "frigate/events" -m '{
  "type": "update",
  "after": {
    "id": "test_event_1",
    "camera": "cam_01",
    "label": "person",
    "track_id": 999,
    "box": [0.3, 0.4, 0.2, 0.3],
    "top_score": 0.95
  }
}'

# 3. Repeat this message 3+ times with 15 second intervals
# (After 30s total, anomaly should trigger)

# 4. Check logs
journalctl -u anomaly-handler.service -n 20

# Expected output:
# [INFO] Anomaly detected: loitering on cam_01
# [INFO] Snapshot saved: /var/lib/saras/anomalies/cam_01_2025...jpg
# [INFO] Webhook alert sent: test_event_1
# [INFO] Telegram alert sent: test_event_1
```

### Check Service Status

```bash
# View service status
systemctl status anomaly-handler.service

# Follow live logs
journalctl -u anomaly-handler.service -f

# Restart if needed
sudo systemctl restart anomaly-handler.service
```

### Common Issues

| Issue                               | Solution                                                                           |
| ----------------------------------- | ---------------------------------------------------------------------------------- |
| MQTT connection failing             | Check Frigate MQTT broker is running: `mosquitto_pub -h localhost -t test -m "ok"` |
| PostgreSQL connection error         | Verify user/password: `psql -h localhost -U saras -d saras`                        |
| Permission denied on /var/lib/saras | Fix ownership: `sudo chown -R saras:saras /var/lib/saras`                          |
| Memory limit exceeded               | Increase MemoryMax in systemd service or disable YOLO                              |
| Flask port already in use           | Change FLASK_PORT environment variable                                             |

---

## Performance & Memory Usage

### Idle Footprint (Raspberry Pi 5)

```
Memory: ~150-200 MB
CPU:    ~2-5% (waiting for events)
```

### Under Load (During Clip Processing)

```
Memory: ~400-600 MB (within 800 MB limit)
CPU:    60-80% (media encoding, YOLO inference)
```

### Optimization Tips

1. **Disable YOLO** if weapon detection not needed (saves ~300 MB)
2. **Reduce video quality** in Frigate to minimize clip size
3. **Set retention_days** to lower value (default: 7 days)
4. **Use go2rtc proxy** in Frigate for MJPEG streaming (lighter than direct RTSP)

---

## Production Deployment Checklist

- [ ] Database: Create user, set secure password, verify connectivity
- [ ] Storage: Create `/var/lib/saras/anomalies` with proper permissions
- [ ] MQTT: Verify Frigate MQTT broker is running
- [ ] Service user: Create `saras` user with correct shell
- [ ] Systemd: Install and enable service file
- [ ] Config: Set all environment variables in service file
- [ ] Logs: Configure log rotation in `/var/log/saras`
- [ ] Firewall: Open port 8080 for dashboard (restrict to LAN if needed)
- [ ] Backup: Schedule database backups (PostgreSQL `pg_dump`)
- [ ] Monitoring: Set up alerting on systemd service failures
- [ ] Testing: Run full test suite before going to production

---

## Expected Log Output

### Successful Startup

```
2025-02-21 10:30:45 [INFO] [AnomalyHandler] Database connected
2025-02-21 10:30:45 [INFO] [AnomalyHandler] YOLO model loaded: yolo26n.pt
2025-02-21 10:30:46 [INFO] [AnomalyHandler] Service started successfully
2025-02-21 10:30:47 [INFO] [AnomalyHandler] MQTT connected
2025-02-21 10:30:47 [INFO] [AnomalyHandler] Starting Flask server on 0.0.0.0:8080
```

### Loitering Anomaly Trigger

```
2025-02-21 10:35:12 [INFO] [AnomalyHandler] Anomaly detected: loitering on cam_01
2025-02-21 10:35:13 [INFO] [AnomalyHandler] Snapshot saved: /var/lib/saras/anomalies/cam_01_20250221_103513_snap.jpg
2025-02-21 10:35:13 [INFO] [AnomalyHandler] Webhook alert sent: evt_abc123
2025-02-21 10:35:14 [INFO] [AnomalyHandler] Telegram alert sent: evt_abc123
2025-02-21 10:35:25 [INFO] [AnomalyHandler] Clip saved: /var/lib/saras/anomalies/cam_01_20250221_103513_clip.mp4
```

### Service Shutdown

```
2025-02-21 10:40:00 [INFO] [AnomalyHandler] Received signal 15, shutting down...
2025-02-21 10:40:01 [INFO] [AnomalyHandler] MQTT disconnect
2025-02-21 10:40:02 [INFO] [AnomalyHandler] Database connection closed
2025-02-21 10:40:02 [INFO] [AnomalyHandler] Service shutdown complete
```

---

## Development & Customization

### Adding New Anomaly Rules

Edit `AnomalyDetector.process_event()` in `anomaly_handler.py`:

```python
# Add new rule
elif label == "car" and duration > CONFIG["thresholds"]["car_park_threshold"]:
    anomaly_key = f"{event_id}_parked_car"
    last_alert = self.last_alert_time.get(anomaly_key, 0)
    if now - last_alert > CONFIG["alerts"]["alert_cooldown"]:
        anomaly_type = "parked_vehicle"
        confidence = 0.75
        self.last_alert_time[anomaly_key] = now
```

### Adding New Alert Channels

Edit `AlertManager` class:

```python
def _send_slack(self, data: Dict):
    """Send alert to Slack webhook."""
    webhook = self.config["alerts"]["slack_webhook"]
    payload = {"text": f"⚠️ {data['anomaly_type']} on {data['camera']}"}
    requests.post(webhook, json=payload)
```

### Integrating Neo4j (Optional)

For relationship tracking (person -> zone -> camera):

```python
from neo4j import GraphDatabase

# In AnomalyHandlerService.__init__
self.neo4j_driver = GraphDatabase.driver("neo4j://localhost:7687", auth=("neo4j", "password"))

# Log events
with self.neo4j_driver.session() as session:
    session.run("""
        MATCH (p:Person {track_id: $tid}), (c:Camera {id: $cid})
        CREATE (p)-[:DETECTED_IN {timestamp: $ts}]->(c)
    """, tid=track_id, cid=camera, ts=datetime.now())
```

---

## License & Support

SARAS Surveillance System - Production Deployment Documentation

Last Updated: 2025-02-21
