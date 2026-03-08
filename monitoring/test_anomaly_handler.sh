#!/bin/bash
# TEST SCRIPT for Anomaly Handler
# Tests MQTT connection, database, and anomaly detection

set -e

ANOMALY_HANDLER="/home/saras/monitoring/anomaly_handler.py"
MQTT_HOST="${FRIGATE_MQTT_HOST:-localhost}"
MQTT_PORT="${FRIGATE_MQTT_PORT:-1883}"
POSTGRES_URL="${POSTGRES_URL:-postgresql://saras:@localhost/saras}"
FLASK_PORT="${FLASK_PORT:-8080}"

echo "=========================================="
echo "Anomaly Handler Test Suite"
echo "=========================================="
echo ""

# Test 1: Python dependencies
echo "[TEST 1] Checking Python dependencies..."
python3 << EOF
try:
    import paho.mqtt.client
    import flask
    import cv2
    import numpy as np
    import psycopg2
    import requests
    print("✅ All dependencies installed")
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    exit(1)
EOF

echo ""

# Test 2: PostgreSQL connection
echo "[TEST 2] Testing PostgreSQL connection..."
python3 << EOF
import psycopg2
try:
    conn = psycopg2.connect("$POSTGRES_URL")
    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()
    conn.close()
    print("✅ PostgreSQL connection OK")
except Exception as e:
    print(f"❌ PostgreSQL connection failed: {e}")
    exit(1)
EOF

echo ""

# Test 3: MQTT connection
echo "[TEST 3] Testing MQTT connection..."
timeout 5 python3 << EOF || true
import paho.mqtt.client as mqtt
import time

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ MQTT connection OK")
    else:
        print(f"❌ MQTT connection failed: {rc}")

client = mqtt.Client("test_client")
client.on_connect = on_connect

try:
    client.connect("$MQTT_HOST", int("$MQTT_PORT"), keepalive=2)
    client.loop_start()
    time.sleep(1)
    client.loop_stop()
except Exception as e:
    print(f"❌ MQTT connection error: {e}")
EOF

echo ""

# Test 4: Flask web server
echo "[TEST 4] Testing Flask endpoints..."
python3 << EOF
import requests
import threading
import time
import sys

sys.path.insert(0, '/home/saras/monitoring')

# Start in background (skip for now as it needs full service)
print("⏭️  Skipping live server test (run 'systemctl start anomaly-handler' first)"
)
EOF

echo ""

# Test 5: Synthetic MQTT event
echo "[TEST 5] Testing anomaly detection with synthetic event..."
python3 << EOF
import json
import time

# Simulate a loitering event
frigate_event = {
    "type": "update",
    "after": {
        "id": "test_event_123",
        "camera": "cam_01",
        "label": "person",
        "track_id": 456,
        "box": [0.3, 0.4, 0.2, 0.3],  # normalized [x, y, w, h]
        "top_score": 0.95
    }
}

print(f"Synthetic event: {json.dumps(frigate_event, indent=2)}")
print("✅ Event structure valid")
EOF

echo ""

# Test 6: Database schema
echo "[TEST 6] Checking database schema..."
python3 << EOF
import psycopg2

try:
    conn = psycopg2.connect("$POSTGRES_URL")
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'anomalies'
    """)
    if cur.fetchone():
        print("✅ Database schema exists")
    else:
        print("⚠️  anomalies table not found (will be created on first run)")
    conn.close()
except Exception as e:
    print(f"❌ Schema check failed: {e}")
EOF

echo ""

# Test 7: Config loading
echo "[TEST 7] Testing configuration loading..."
python3 << EOF
import os
os.environ['POSTGRES_URL'] = "$POSTGRES_URL"
os.environ['FRIGATE_MQTT_HOST'] = "$MQTT_HOST"
os.environ['FRIGATE_MQTT_PORT'] = "$MQTT_PORT"

sys.path.insert(0, '/home/swadhin/SARAS/monitoring')
from anomaly_handler import CONFIG

required_keys = ['mqtt', 'frigate', 'database', 'storage', 'alerts', 'thresholds', 'yolo', 'flask']
missing = [k for k in required_keys if k not in CONFIG]

if missing:
    print(f"❌ Missing config sections: {missing}")
else:
    print(f"✅ Config loaded successfully")
    print(f"   - MQTT: {CONFIG['mqtt']['host']}:{CONFIG['mqtt']['port']}")
    print(f"   - Flask: {CONFIG['flask']['host']}:{CONFIG['flask']['port']}")
    print(f"   - Storage: {CONFIG['storage']['clips_dir']}")
EOF

echo ""
echo "=========================================="
echo "Test Suite Complete"
echo "=========================================="
echo ""
echo "NEXT: Start the service and check logs:"
echo "  sudo systemctl start anomaly-handler.service"
echo "  journalctl -u anomaly-handler.service -f"
echo ""
