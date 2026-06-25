#!/bin/bash
# Quick Start Guide for Anomaly Handler Deployment
# Run this step-by-step to get the service up and running

echo "=========================================="
echo "Anomaly Handler - Quick Start"
echo "=========================================="
echo ""

# Check if user is on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "⚠️  Warning: Not running on Raspberry Pi"
    echo "   This may still work on other systems but ARM optimization may not apply"
fi

echo ""
echo "STEP 1: Install Dependencies"
echo "=========================================="
echo "Run this:"
echo "  sudo apt-get update"
echo "  sudo apt-get install -y python3 python3-pip python3-venv postgresql postgresql-contrib"
echo ""
read -p "Press Enter after dependencies are installed..."

echo ""
echo "STEP 2: Create Python Virtual Environment"
echo "=========================================="
cd /home/raven/monitoring
python3 -m venv venv
source venv/bin/activate
echo "✅ Virtual environment created and activated"
echo ""

echo "STEP 3: Install Python Packages"
echo "=========================================="
echo "Installing lightweight packages for Raspberry Pi..."
pip install --upgrade pip setuptools wheel
pip install \
    paho-mqtt==1.6.1 \
    flask==3.0.0 \
    psycopg2-binary==2.9.9 \
    requests==2.31.0 \
    opencv-python-headless==4.8.0.76 \
    numpy==1.24.3 \
    pillow==10.0.0

echo ""
echo "Optional: YOLO for weapon detection:"
echo "  pip install ultralytics==8.0.200"
echo "  # Download model: wget https://github.com/ultralytics/assets/releases/download/v0.0.1/yolo26n.pt"
echo ""

echo "STEP 4: Setup PostgreSQL"
echo "=========================================="
echo "Create database user and database:"
echo ""
echo "  sudo -u postgres postgres -c \"CREATE USER raven WITH PASSWORD 'YOUR_SECURE_PASSWORD'\""
echo "  sudo -u postgres psql -c \"CREATE DATABASE raven OWNER raven\""
echo ""
read -p "Press Enter after PostgreSQL is configured..."

echo ""
echo "STEP 5: Create System Directories"
echo "=========================================="
sudo mkdir -p /var/lib/raven/anomalies
sudo mkdir -p /var/log/raven
sudo chown -R raven:raven /var/lib/raven
sudo chown -R raven:raven /var/log/raven
sudo chmod 755 /var/lib/raven/anomalies
sudo chmod 755 /var/log/raven
echo "✅ Directories created"
echo ""

echo "STEP 6: Install Systemd Service"
echo "=========================================="
sudo cp /home/raven/monitoring/anomaly-handler.service /etc/systemd/system/
echo "✅ Service file installed to /etc/systemd/system/anomaly-handler.service"
echo ""
echo "IMPORTANT: Edit the service file to configure environment variables:"
echo "  sudo nano /etc/systemd/system/anomaly-handler.service"
echo ""
echo "Key variables to update:"
echo "  - POSTGRES_URL: Add your PostgreSQL password"
echo "  - FRIGATE_MQTT_HOST: Set to your MQTT broker IP"
echo "  - FRIGATE_API_URL: Set to your Frigate instance URL"
echo "  - Optional: TELEGRAM_TOKEN, ANOMALY_WEBHOOK_URL"
echo ""
read -p "Press Enter after editing the service file..."

echo ""
echo "STEP 7: Enable & Start Service"
echo "=========================================="
sudo systemctl daemon-reload
sudo systemctl enable anomaly-handler.service
sudo systemctl start anomaly-handler.service

echo "✅ Service enabled and started"
echo ""

echo "STEP 8: Verify Service Status"
echo "=========================================="
echo "Checking service status..."
if sudo systemctl is-active anomaly-handler.service > /dev/null 2>&1; then
    echo "✅ Service is running!"
else
    echo "❌ Service failed to start. Check logs:"
    journalctl -u anomaly-handler.service -n 20
fi

echo ""
echo "View live logs:"
echo "  journalctl -u anomaly-handler.service -f"
echo ""

echo "STEP 9: Test Web Dashboard"
echo "=========================================="
echo "Open a browser and visit:"
echo "  http://localhost:8080       # Home"
echo "  http://localhost:8080/events # Recent anomalies"
echo "  http://localhost:8080/health # Service health"
echo ""

echo "STEP 10: Test with Synthetic MQTT Event"
echo "=========================================="
echo "Run this in another terminal to simulate an event:"
echo ""
echo '  mosquitto_pub -h localhost -t "frigate/events" -m '"'"'{
    "type": "update",
    "after": {
      "id": "test_event_1",
      "camera": "cam_01",
      "label": "person",
      "track_id": 999,
      "box": [0.3, 0.4, 0.2, 0.3],
      "top_score": 0.95
    }
  }'"'"''
echo ""
echo "Repeat event 3 times with 15-second delays (total 30+ seconds) to trigger loitering alert"
echo ""

echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "NEXT STEPS:"
echo ""
echo "1. Monitor the service:"
echo "   journalctl -u anomaly-handler.service -f"
echo ""
echo "2. Test MQTT connection:"
echo "   mosquitto_sub -h localhost -t 'frigate/events' | head"
echo ""
echo "3. Check database:"
echo "   psql -h localhost -U raven -d raven"
echo "   SELECT * FROM anomalies LIMIT 5;"
echo ""
echo "4. Configure alerts:"
echo "   Set TELEGRAM_TOKEN or ANOMALY_WEBHOOK_URL in systemd service"
echo "   sudo systemctl edit anomaly-handler.service"
echo "   sudo systemctl restart anomaly-handler.service"
echo ""
echo "5. Run full test suite:"
echo "   bash test_anomaly_handler.sh"
echo ""
echo "Documentation:"
echo "  See README_ANOMALY_HANDLER.md for detailed configuration"
echo ""
